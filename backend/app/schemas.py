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


class ChatRequestIn(BaseModel):
    user_id: str = Field(..., examples=["shaun"])
    message: str = Field(..., examples=["How am I doing today?"])


class ChatResponseOut(BaseModel):
    reply: str
    used_watch_data: bool = False
    context_date: Optional[str] = None
    risk_label: Optional[str] = None
    risk_score: Optional[int] = None
