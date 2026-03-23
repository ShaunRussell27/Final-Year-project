import asyncio
import os

from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from .db import get_db, engine
from .models import Base, DailySummary
from .ml_service import BurnoutModelService, NotebookBurnoutModelService
from .schemas import HealthKitIn, DailySummaryOut, RiskOut, NotebookPredictIn, ChatRequestIn, ChatResponseOut

app = FastAPI(title="Burnout Project Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple “migration”: create tables on startup (fine for FYP MVP)
Base.metadata.create_all(bind=engine)
model_service = BurnoutModelService()
model_service.load()
notebook_model_service = NotebookBurnoutModelService()
notebook_model_service.load()


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    return max(minimum, value)

AUTO_SYNC_ENABLED = os.getenv("GARMIN_AUTO_SYNC_ENABLED", "false").lower() == "true"
AUTO_SYNC_INTERVAL_MINUTES = _int_env("GARMIN_AUTO_SYNC_INTERVAL_MINUTES", 180, minimum=1)
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
    try:
        from sync_garmin_to_railway import run_sync
    except ModuleNotFoundError:
        from backend.sync_garmin_to_railway import run_sync

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

SOURCE_PRIORITY = ["garmin_export", "healthkit"]  # garmin watch sync takes priority over manual entries

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

    if latest.avg_stress is not None:
        if latest.avg_stress >= 90:
            score += 35
            factors.append(f"watch stress score is critically high ({latest.avg_stress}/100)")
        elif latest.avg_stress >= 75:
            score += 25
            factors.append(f"watch stress score is high ({latest.avg_stress}/100)")
        elif latest.avg_stress >= 60:
            score += 15
            factors.append(f"watch stress score is elevated ({latest.avg_stress}/100)")
        elif latest.avg_stress >= 50:
            score += 8
            factors.append(f"watch stress score is above normal ({latest.avg_stress}/100)")
        elif latest.avg_stress <= 25:
            score -= 8
            factors.append(f"watch stress score is low ({latest.avg_stress}/100)")

    if latest.body_battery_max is not None:
        if latest.body_battery_max <= 5:
            score += 35
            factors.append(f"body battery is empty ({latest.body_battery_max}/100)")
        elif latest.body_battery_max <= 20:
            score += 20
            factors.append(f"body battery is critically low ({latest.body_battery_max}/100)")
        elif latest.body_battery_max <= 40:
            score += 10
            factors.append(f"body battery is low ({latest.body_battery_max}/100)")
        elif latest.body_battery_max >= 80:
            score -= 8
            factors.append(f"body battery is high ({latest.body_battery_max}/100)")

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
        elif hr_delta <= -4:
            score -= 8
            factors.append("resting heart rate is well below baseline — good recovery sign")

    if latest.steps is not None and baseline_steps is not None and baseline_steps > 0:
        steps_ratio = latest.steps / baseline_steps
        if steps_ratio < 0.50:
            score += 20
            factors.append("steps are far below baseline")
        elif steps_ratio < 0.75:
            score += 12
            factors.append("steps are below baseline")
        elif steps_ratio >= 1.25:
            score -= 5
            factors.append("activity level is well above baseline")

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


def _build_chatbot_reply(message: str, summary: DailySummary | None, risk: RiskOut | None) -> str:
    text = message.lower()

    if summary is None or risk is None:
        return (
            "I can help with stress, sleep, and burnout prevention. "
            "I could not find your latest watch data yet, so please sync data first and I can personalize advice."
        )

    parts: list[str] = []
    parts.append(
        f"Based on your latest watch data from {summary.date}, your burnout risk is {risk.risk_label} ({risk.risk_score}%)."
    )

    guidance: list[str] = []
    if summary.sleep_minutes is not None:
        if summary.sleep_minutes < 420:
            guidance.append("Your sleep is below 7 hours; aim for 7-9 hours and keep a fixed bedtime this week.")
        else:
            guidance.append("Your sleep duration is in a healthy range; protect this routine.")

    if summary.resting_hr is not None:
        if summary.resting_hr >= 75:
            guidance.append("Resting heart rate is elevated; reduce intense training and prioritize recovery today.")
        else:
            guidance.append("Resting heart rate looks stable; continue with balanced training and recovery.")

    if summary.steps is not None:
        if summary.steps < 8000:
            guidance.append("Daily movement is low; add a 20-30 minute walk to support stress recovery.")
        else:
            guidance.append("Your activity level is solid; keep daily movement consistent.")

    if "what should i do" in text or "plan" in text or "improve" in text:
        parts.append("Suggested plan for today:")
        parts.extend(guidance[:3] if guidance else ["Keep sleep, activity, and stress routines consistent."])
    elif "sleep" in text:
        parts.append(next((g for g in guidance if "sleep" in g.lower()), "Focus on a regular sleep schedule and limit screens before bed."))
    elif "stress" in text or "burnout" in text:
        parts.append("Do a short recovery block now: 5 minutes slow breathing, 10 minutes light walk, and a lower workload block if possible.")
        if risk.explanation:
            parts.append(f"Main risk signals: {'; '.join(risk.explanation[:2])}.")
    else:
        parts.append("Ask me for a daily plan, sleep advice, or stress recovery and I will tailor it to your watch data.")

    return " ".join(parts)


def _latest_summary_and_risk(user_id: str, db: Session) -> tuple[DailySummary | None, RiskOut | None]:
    rows = (
        db.query(DailySummary)
        .filter(DailySummary.user_id == user_id)
        .order_by(DailySummary.date.desc())
        .limit(8)
        .all()
    )
    if not rows:
        return None, None

    latest = rows[0]
    baseline_rows = rows[1:8] if len(rows) > 1 else [latest]

    model_prediction = model_service.predict(latest, baseline_rows)
    if model_prediction is not None:
        risk = RiskOut(
            user_id=latest.user_id,
            date=latest.date,
            risk_label=model_prediction.risk_label,
            risk_score=model_prediction.risk_score,
            explanation=model_prediction.explanation,
        )
        return latest, risk

    return latest, _compute_risk(latest, baseline_rows)

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
        avg_stress=payload.avg_stress,
        max_stress=payload.max_stress,
        body_battery_max=payload.body_battery_max,
        sleep_score=payload.sleep_score,
        hrv_avg=payload.hrv_avg,
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
        "avg_stress": row.avg_stress,
        "max_stress": row.max_stress,
        "body_battery_max": row.body_battery_max,
        "sleep_score": row.sleep_score,
        "hrv_avg": row.hrv_avg,
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
def summary_latest(user_id: str, preferred_source: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(DailySummary).filter(DailySummary.user_id == user_id)
    if preferred_source:
        row = query.filter(DailySummary.source == preferred_source).order_by(DailySummary.date.desc()).first()
        if not row:
            row = query.order_by(DailySummary.date.desc()).first()
    else:
        row = query.order_by(DailySummary.date.desc()).first()
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
        "avg_stress": row.avg_stress,
        "max_stress": row.max_stress,
        "body_battery_max": row.body_battery_max,
        "sleep_score": row.sleep_score,
        "hrv_avg": row.hrv_avg,
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

    # If the record has HRV, also run the SWELL/WESAD notebook model and blend the scores
    notebook_prediction = None
    if latest.hrv_avg and latest.hrv_avg > 0:
        notebook_prediction = notebook_model_service.predict(
            resting_hr=latest.resting_hr,
            avg_hr=latest.avg_hr,
            hrv_avg=latest.hrv_avg,
        )

    if model_prediction is not None or notebook_prediction is not None:
        iso_score = model_prediction.risk_score if model_prediction else None
        nb_score = notebook_prediction.risk_score if notebook_prediction else None

        if iso_score is not None and nb_score is not None:
            blended_score = int(round(iso_score * 0.5 + nb_score * 0.5))
        else:
            blended_score = iso_score if iso_score is not None else nb_score

        blended_score = max(0, min(100, blended_score))
        if blended_score >= 70:
            blended_label = "High"
        elif blended_score >= 40:
            blended_label = "Medium"
        else:
            blended_label = "Low"

        explanation = []
        if model_prediction:
            explanation.extend(model_prediction.explanation)
        if notebook_prediction:
            explanation.extend(notebook_prediction.explanation)
        if not explanation:
            explanation = ["no major negative deviation versus baseline detected"]

        confidence = notebook_prediction.confidence if notebook_prediction else None
        return RiskOut(
            user_id=latest.user_id,
            date=latest.date,
            risk_label=blended_label,
            risk_score=blended_score,
            explanation=explanation,
            confidence=confidence,
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

    # Apply adjustments: watch-measured stress takes priority over self-reported slider
    adjustment = 0
    extra_factors: list[str] = []

    # Blend objective (Garmin) and self-reported stress when both are available (60/40 weighting)
    if payload.avg_stress is not None and payload.perceived_stress is not None:
        effective_stress = round(payload.avg_stress * 0.6 + payload.perceived_stress * 0.4)
        stress_source = f"blended stress (watch {payload.avg_stress}/100, self-reported {payload.perceived_stress}/100)"
    elif payload.avg_stress is not None:
        effective_stress = payload.avg_stress
        stress_source = f"watch stress score ({payload.avg_stress}/100)"
    elif payload.perceived_stress is not None:
        effective_stress = payload.perceived_stress
        stress_source = f"self-reported stress ({payload.perceived_stress}/100)"
    else:
        effective_stress = None
        stress_source = ""

    if effective_stress is not None:
        if effective_stress >= 90:
            adjustment += 35
            extra_factors.append(f"{stress_source} — critically high")
        elif effective_stress >= 75:
            adjustment += 22
            extra_factors.append(f"{stress_source} — high")
        elif effective_stress >= 60:
            adjustment += 12
            extra_factors.append(f"{stress_source} — elevated")
        elif effective_stress <= 25:
            adjustment -= 10
            extra_factors.append(f"{stress_source} — low")

    if payload.body_battery_max is not None:
        # Extreme tier: empty body battery overrides an otherwise-low model score
        if payload.body_battery_max <= 5:
            adjustment += 35
            extra_factors.append(f"body battery is empty ({payload.body_battery_max}/100)")
        elif payload.body_battery_max <= 20:
            adjustment += 22
            extra_factors.append(f"body battery critically low ({payload.body_battery_max}/100)")
        elif payload.body_battery_max <= 40:
            adjustment += 12
            extra_factors.append(f"body battery low ({payload.body_battery_max}/100)")
        elif payload.body_battery_max >= 80:
            adjustment -= 10
            extra_factors.append(f"body battery is high ({payload.body_battery_max}/100)")

    if payload.work_hours is not None:
        if payload.work_hours > 10:
            adjustment += 12
            extra_factors.append(f"long workday ({payload.work_hours:.0f} hrs)")
        elif payload.work_hours > 8:
            adjustment += 6
            extra_factors.append(f"extended workday ({payload.work_hours:.0f} hrs)")
        elif payload.work_hours <= 6:
            adjustment -= 5
            extra_factors.append(f"short workday ({payload.work_hours:.0f} hrs)")

    if payload.mood_score is not None:
        if payload.mood_score <= 2:
            adjustment += 10
            extra_factors.append(f"poor self-reported mood ({payload.mood_score}/5)")
        elif payload.mood_score == 3:
            adjustment += 4
        elif payload.mood_score >= 5:
            adjustment -= 5
            extra_factors.append("good self-reported mood")

    adjusted_score = max(0, min(100, prediction.risk_score + adjustment))
    combined_explanation = prediction.explanation + extra_factors

    if adjusted_score >= 70:
        adjusted_label = "High"
    elif adjusted_score >= 40:
        adjusted_label = "Medium"
    else:
        adjusted_label = "Low"

    return RiskOut(
        user_id=risk_user_id,
        date=risk_date,
        risk_label=adjusted_label,
        risk_score=adjusted_score,
        explanation=combined_explanation,
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
            "avg_stress": r.avg_stress,
            "max_stress": r.max_stress,
            "body_battery_max": r.body_battery_max,
            "sleep_score": r.sleep_score,
        })
        for r in rows
    ]


@app.post("/chatbot/coach", response_model=ChatResponseOut)
def chatbot_coach(payload: ChatRequestIn, db: Session = Depends(get_db)):
    latest, risk = _latest_summary_and_risk(payload.user_id, db)
    reply = _build_chatbot_reply(payload.message, latest, risk)

    return ChatResponseOut(
        reply=reply,
        used_watch_data=latest is not None,
        context_date=latest.date if latest else None,
        risk_label=risk.risk_label if risk else None,
        risk_score=risk.risk_score if risk else None,
    )
