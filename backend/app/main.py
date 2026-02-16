from fastapi import FastAPI, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timezone

from .db import get_db, engine
from .models import Base, DailySummary
from .schemas import HealthKitIn, DailySummaryOut

app = FastAPI(title="Burnout Project Backend")

# Simple “migration”: create tables on startup (fine for FYP MVP)
Base.metadata.create_all(bind=engine)

SOURCE_PRIORITY = ["healthkit", "garmin_export"]  # prefer healthkit if both exist

@app.get("/health")
def health():
    return {"status": "ok"}

def upsert_daily_summary(db: Session, user_id: str, date: str, source: str, **fields):
    # If there is an existing record for this user+date, keep the higher-priority source.
    existing = db.query(DailySummary).filter(DailySummary.user_id == user_id, DailySummary.date == date).one_or_none()
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
        return existing

    row = DailySummary(user_id=user_id, date=date, source=source, **fields)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row

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
        raw_note="healthkit_json",
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
        "raw_note": row.raw_note,
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
        raw_note=f"uploaded_file={file.filename};bytes={len(content)}",
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
        "raw_note": row.raw_note,
    })

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
            "raw_note": r.raw_note,
        })
        for r in rows
    ]
