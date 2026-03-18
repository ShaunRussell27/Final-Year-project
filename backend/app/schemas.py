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
    avg_stress: Optional[int] = None
    max_stress: Optional[int] = None
    body_battery_max: Optional[int] = None
    sleep_score: Optional[int] = None

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
    avg_stress: Optional[int] = None
    max_stress: Optional[int] = None
    body_battery_max: Optional[int] = None
    sleep_score: Optional[int] = None


class RiskOut(BaseModel):
    user_id: str
    date: str
    risk_label: str
    risk_score: int
    explanation: list[str]
    confidence: Optional[float] = None


class NotebookPredictIn(BaseModel):
    user_id: Optional[str] = Field(default="demo-user", examples=["u123"])
    date: Optional[str] = Field(default=None, examples=["2026-02-16"])

    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hrv_avg: float = Field(..., examples=[53.0])

    # Watch-measured stress (Garmin avg stress score 0-100); takes priority over perceived_stress when present
    avg_stress: Optional[int] = Field(default=None, ge=0, le=100)
    body_battery_max: Optional[int] = Field(default=None, ge=0, le=100)

    # Self-report fallback — used only when watch stress data is absent
    perceived_stress: Optional[int] = Field(default=None, ge=0, le=100)  # 0-100, same scale as Garmin avg_stress
    work_hours: Optional[float] = Field(default=None, ge=0, le=24)       # hours worked/studied today
    mood_score: Optional[int] = Field(default=None, ge=1, le=5)          # 1=very poor, 5=excellent


class ChatRequestIn(BaseModel):
    user_id: str = Field(..., examples=["shaun"])
    message: str = Field(..., examples=["How am I doing today?"])


class ChatResponseOut(BaseModel):
    reply: str
    used_watch_data: bool = False
    context_date: Optional[str] = None
    risk_label: Optional[str] = None
    risk_score: Optional[int] = None
