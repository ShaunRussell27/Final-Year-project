from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional

class HealthKitIn(BaseModel):
    user_id: str = Field(..., examples=["u123"])
    date: str = Field(..., examples=["2026-02-16"])  # the day the summary represents
    collected_at: Optional[datetime] = None

    steps: Optional[int] = None
    sleep_minutes: Optional[int] = None
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hr_samples_count: Optional[int] = None

class DailySummaryOut(BaseModel):
    user_id: str
    date: str
    source: str
    collected_at: datetime

    steps: Optional[int] = None
    sleep_minutes: Optional[int] = None
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hr_samples_count: Optional[int] = None
    raw_note: Optional[str] = None
