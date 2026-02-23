import asyncio
import os

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from .db import get_db, engine
from .models import Base, DailySummary
from .ml_service import BurnoutModelService, NotebookBurnoutModelService
from .schemas import HealthKitIn, DailySummaryOut, RiskOut, NotebookPredictIn

app = FastAPI(title="Burnout Project Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple “migration”: create tables on startup (fine for FYP MVP)
Base.metadata.create_all(bind=engine)
model_service = BurnoutModelService()
model_service.load()
notebook_model_service = NotebookBurnoutModelService()
notebook_model_service.load()

AUTO_SYNC_ENABLED = os.getenv("GARMIN_AUTO_SYNC_ENABLED", "false").lower() == "true"
AUTO_SYNC_INTERVAL_MINUTES = int(os.getenv("GARMIN_AUTO_SYNC_INTERVAL_MINUTES", "180"))
AUTO_SYNC_RUN_ON_STARTUP = os.getenv("GARMIN_AUTO_SYNC_RUN_ON_STARTUP", "true").lower() == "true"

_garmin_sync_task: asyncio.Task | None = None
_garmin_sync_status: dict[str, object] = {
    "enabled": AUTO_SYNC_ENABLED,
    "interval_minutes": max(1, AUTO_SYNC_INTERVAL_MINUTES),
    "run_on_startup": AUTO_SYNC_RUN_ON_STARTUP,
    "last_run_started_at": None,
    "last_run_finished_at": None,
    "last_run_success": None,
    "last_error": None,
    "last_result": None,
}


def _run_garmin_sync_once_blocking() -> dict[str, object]:
    from sync_garmin_to_railway import run_sync

    return run_sync()


async def _run_garmin_sync_once_safe() -> None:
    _garmin_sync_status["last_run_started_at"] = datetime.now(timezone.utc).isoformat()
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _run_garmin_sync_once_blocking)
        _garmin_sync_status["last_run_success"] = True
        _garmin_sync_status["last_error"] = None
        _garmin_sync_status["last_result"] = result
        print("[Garmin Auto Sync] Sync completed")
    except Exception as exc:
        _garmin_sync_status["last_run_success"] = False
        _garmin_sync_status["last_error"] = str(exc)
        print(f"[Garmin Auto Sync] Sync failed: {exc}")
    finally:
        _garmin_sync_status["last_run_finished_at"] = datetime.now(timezone.utc).isoformat()


async def _garmin_sync_loop() -> None:
    if AUTO_SYNC_RUN_ON_STARTUP:
        await _run_garmin_sync_once_safe()

    while True:
        await asyncio.sleep(max(1, AUTO_SYNC_INTERVAL_MINUTES) * 60)
        await _run_garmin_sync_once_safe()


@app.on_event("startup")
async def _startup_auto_sync() -> None:
    global _garmin_sync_task
    if not AUTO_SYNC_ENABLED:
        print("[Garmin Auto Sync] Disabled (set GARMIN_AUTO_SYNC_ENABLED=true to enable)")
        return

    _garmin_sync_task = asyncio.create_task(_garmin_sync_loop())
    print(
        f"[Garmin Auto Sync] Enabled every {max(1, AUTO_SYNC_INTERVAL_MINUTES)} minute(s)"
    )


@app.on_event("shutdown")
async def _shutdown_auto_sync() -> None:
    global _garmin_sync_task
    if _garmin_sync_task is None:
        return

    _garmin_sync_task.cancel()
    try:
        await _garmin_sync_task
    except asyncio.CancelledError:
        pass
    _garmin_sync_task = None

SOURCE_PRIORITY = ["healthkit", "garmin_export"]  # prefer healthkit if both exist

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sync/status")
def sync_status():
    return {
        "sync": {
            "enabled": _garmin_sync_status["enabled"],
            "interval_minutes": _garmin_sync_status["interval_minutes"],
            "run_on_startup": _garmin_sync_status["run_on_startup"],
            "task_running": _garmin_sync_task is not None and not _garmin_sync_task.done(),
            "last_run_started_at": _garmin_sync_status["last_run_started_at"],
            "last_run_finished_at": _garmin_sync_status["last_run_finished_at"],
            "last_run_success": _garmin_sync_status["last_run_success"],
            "last_error": _garmin_sync_status["last_error"],
            "last_result": _garmin_sync_status["last_result"],
        }
    }

def upsert_daily_summary(db: Session, user_id: str, date: str, source: str, **fields):
    # If there are existing records for this user+date, keep one canonical row.
    # This gracefully handles accidental duplicates from earlier runs/races.
    matches = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id, DailySummary.date == date)
        .order_by(DailySummary.id.desc())
        .all()
    )

    existing = matches[0] if matches else None
    if len(matches) > 1:
        for duplicate in matches[1:]:
            db.delete(duplicate)

    if existing:
        existing_pri = SOURCE_PRIORITY.index(existing.source) if existing.source in SOURCE_PRIORITY else 999
        new_pri = SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else 999
        if new_pri <= existing_pri:
            # overwrite with better/equal source
            existing.source = source
            for k, v in fields.items():
                setattr(existing, k, v)
            db.add(existing)
            db.commit()
            db.refresh(existing)
        else:
            db.commit()
        return existing

    row = DailySummary(user_id=user_id, date=date, source=source, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _avg(values: list[float | int | None]) -> float | None:
    numeric = [float(v) for v in values if v is not None]
    if not numeric:
        return None
    return sum(numeric) / len(numeric)


def _compute_risk(latest: DailySummary, baseline_rows: list[DailySummary]) -> RiskOut:
    baseline_sleep = _avg([r.sleep_minutes for r in baseline_rows])
    baseline_resting_hr = _avg([r.resting_hr for r in baseline_rows])
    baseline_steps = _avg([r.steps for r in baseline_rows])

    score = 20
    factors: list[str] = []

    if latest.sleep_minutes is not None and baseline_sleep is not None and baseline_sleep > 0:
        sleep_ratio = latest.sleep_minutes / baseline_sleep
        if sleep_ratio < 0.70:
            score += 35
            factors.append("sleep is much lower than 7-day baseline")
        elif sleep_ratio < 0.85:
            score += 20
            factors.append("sleep is below 7-day baseline")
        elif sleep_ratio < 0.95:
            score += 10
            factors.append("sleep is slightly below baseline")

    if latest.resting_hr is not None and baseline_resting_hr is not None and baseline_resting_hr > 0:
        hr_delta = latest.resting_hr - baseline_resting_hr
        if hr_delta >= 8:
            score += 30
            factors.append("resting heart rate is significantly higher than baseline")
        elif hr_delta >= 4:
            score += 18
            factors.append("resting heart rate is above baseline")
        elif hr_delta >= 2:
            score += 10
            factors.append("resting heart rate is slightly above baseline")

    if latest.steps is not None and baseline_steps is not None and baseline_steps > 0:
        steps_ratio = latest.steps / baseline_steps
        if steps_ratio < 0.50:
            score += 20
            factors.append("steps are far below baseline")
        elif steps_ratio < 0.75:
            score += 12
            factors.append("steps are below baseline")

    score = max(0, min(100, score))

    if score >= 70:
        label = "High"
    elif score >= 40:
        label = "Medium"
    else:
        label = "Low"

    if not factors:
        factors.append("no major negative deviation versus baseline detected")

    return RiskOut(
        user_id=latest.user_id,
        date=latest.date,
        risk_label=label,
        risk_score=score,
        explanation=factors,
    )

@app.post("/ingest/healthkit", response_model=DailySummaryOut)
def ingest_healthkit(payload: HealthKitIn, db: Session = Depends(get_db)):
    collected_at = payload.collected_at or datetime.now(timezone.utc)

    row = upsert_daily_summary(
        db=db,
        user_id=payload.user_id,
        date=payload.date,
        source="healthkit",
        collected_at=collected_at,
        steps=payload.steps,
        sleep_minutes=payload.sleep_minutes,
        resting_hr=payload.resting_hr,
        avg_hr=payload.avg_hr,
        hr_samples_count=payload.hr_samples_count,
    )
    return DailySummaryOut.model_validate({
        "user_id": row.user_id,
        "date": row.date,
        "source": row.source,
        "collected_at": row.collected_at,
        "steps": row.steps,
        "sleep_minutes": row.sleep_minutes,
        "resting_hr": row.resting_hr,
        "avg_hr": row.avg_hr,
        "hr_samples_count": row.hr_samples_count,
    })

@app.post("/ingest/garmin-export")
async def ingest_garmin_export(
    user_id: str,
    date: str,  # "YYYY-MM-DD" for the day this export corresponds to (keep it simple)
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # MVP: don’t parse yet — just store metadata.
    row = upsert_daily_summary(
        db=db,
        user_id=user_id,
        date=date,
        source="garmin_export",
        collected_at=datetime.now(timezone.utc),
    )
    return {"ok": True, "saved": {"user_id": row.user_id, "date": row.date, "source": row.source}}

@app.get("/summary/latest", response_model=DailySummaryOut)
def summary_latest(user_id: str, db: Session = Depends(get_db)):
    row = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="No data for user_id")
    return DailySummaryOut.model_validate({
        "user_id": row.user_id,
        "date": row.date,
        "source": row.source,
        "collected_at": row.collected_at,
        "steps": row.steps,
        "sleep_minutes": row.sleep_minutes,
        "resting_hr": row.resting_hr,
        "avg_hr": row.avg_hr,
        "hr_samples_count": row.hr_samples_count,
    })


@app.get("/risk/latest", response_model=RiskOut)
def risk_latest(user_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .limit(8)
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No data for user_id")

    latest = rows[0]
    baseline_rows = rows[1:8]
    if not baseline_rows:
        baseline_rows = [latest]

    model_prediction = model_service.predict(latest, baseline_rows)
    if model_prediction is not None:
        return RiskOut(
            user_id=latest.user_id,
            date=latest.date,
            risk_label=model_prediction.risk_label,
            risk_score=model_prediction.risk_score,
            explanation=model_prediction.explanation,
        )

    return _compute_risk(latest, baseline_rows)


@app.post("/risk/notebook", response_model=RiskOut)
def risk_notebook(payload: NotebookPredictIn):
    prediction = notebook_model_service.predict(
        resting_hr=payload.resting_hr,
        avg_hr=payload.avg_hr,
        hrv_avg=payload.hrv_avg,
    )

    if prediction is None:
        if not notebook_model_service.is_ready:
            raise HTTPException(
                status_code=503,
                detail="Notebook model is not loaded. Expected notebooks/burnout_model.pkl and notebooks/scaler.pkl",
            )
        raise HTTPException(status_code=400, detail="Valid resting_hr (or avg_hr) and hrv_avg are required")

    risk_date = payload.date or datetime.now(timezone.utc).date().isoformat()
    risk_user_id = payload.user_id or "demo-user"

    return RiskOut(
        user_id=risk_user_id,
        date=risk_date,
        risk_label=prediction.risk_label,
        risk_score=prediction.risk_score,
        explanation=prediction.explanation,
        confidence=prediction.confidence,
    )

@app.get("/summaries", response_model=list[DailySummaryOut])
def summaries(user_id: str, limit: int = 30, db: Session = Depends(get_db)):
    rows = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .limit(limit)
        .all()
    )
    return [
        DailySummaryOut.model_validate({
            "user_id": r.user_id,
            "date": r.date,
            "source": r.source,
            "collected_at": r.collected_at,
            "steps": r.steps,
            "sleep_minutes": r.sleep_minutes,
            "resting_hr": r.resting_hr,
            "avg_hr": r.avg_hr,
            "hr_samples_count": r.hr_samples_count,
        })
        for r in rows
    ]
