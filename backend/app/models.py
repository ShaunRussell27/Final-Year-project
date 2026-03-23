from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Integer, Float, func

class Base(DeclarativeBase):
    pass

class DailySummary(Base):
    __tablename__ = "daily_summary"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # "YYYY-MM-DD"
    source: Mapped[str] = mapped_column(String(32))            # healthkit | garmin_export

    collected_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sleep_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    hr_samples_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Garmin-specific fields collected by sync but previously unused
    avg_stress: Mapped[int | None] = mapped_column(Integer, nullable=True)       # 0-100 Garmin stress score
    max_stress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_battery_max: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100 energy reserve
    sleep_score: Mapped[int | None] = mapped_column(Integer, nullable=True)       # Garmin sleep score
    hrv_avg: Mapped[float | None] = mapped_column(Float, nullable=True)           # HRV RMSSD nightly average (ms)
