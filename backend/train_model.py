from datetime import datetime, timezone
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.db import SessionLocal
from app.models import DailySummary


def _build_training_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values(["user_id", "date"])

    metric_cols = ["sleep_minutes", "resting_hr", "steps", "avg_hr", "body_battery_max", "sleep_score"]

    for col in metric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in metric_cols:
        baseline_col = f"{col}_baseline"
        df[baseline_col] = (
            df.groupby("user_id")[col]
            .transform(lambda s: s.shift(1).rolling(window=7, min_periods=1).mean())
        )

    df["sleep_ratio"] = (df["sleep_minutes"] / df["sleep_minutes_baseline"]).replace([np.inf, -np.inf], np.nan)
    df["steps_ratio"] = (df["steps"] / df["steps_baseline"]).replace([np.inf, -np.inf], np.nan)
    df["resting_hr_delta"] = (df["resting_hr"] - df["resting_hr_baseline"])
    df["avg_hr_delta"] = (df["avg_hr"] - df["avg_hr_baseline"])
    df["body_battery_ratio"] = (df["body_battery_max"] / df["body_battery_max_baseline"]).replace([np.inf, -np.inf], np.nan)
    df["sleep_score_ratio"] = (df["sleep_score"] / df["sleep_score_baseline"]).replace([np.inf, -np.inf], np.nan)

    feature_cols = ["sleep_ratio", "resting_hr_delta", "steps_ratio", "avg_hr_delta", "body_battery_ratio", "sleep_score_ratio"]
    features = df[feature_cols].copy().fillna(0.0)

    return features


def train_model(output_path: str) -> None:
    db = SessionLocal()
    try:
        rows = db.query(DailySummary).all()
    finally:
        db.close()

    if len(rows) < 5:
        raise RuntimeError("Not enough daily_summary rows to train model (need at least 5)")

    data = []
    for row in rows:
        data.append(
            {
                "user_id": row.user_id,
                "date": row.date,
                "sleep_minutes": row.sleep_minutes,
                "resting_hr": row.resting_hr,
                "steps": row.steps,
                "avg_hr": row.avg_hr,
                "body_battery_max": row.body_battery_max,
                "sleep_score": row.sleep_score,
            }
        )

    df = pd.DataFrame(data)
    features = _build_training_frame(df)

    model = IsolationForest(
        n_estimators=200,
        contamination=0.15,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(features)

    scores = model.decision_function(features)

    payload = {
        "model": model,
        "feature_names": ["sleep_ratio", "resting_hr_delta", "steps_ratio", "avg_hr_delta", "body_battery_ratio", "sleep_score_ratio"],
        "score_min": float(np.min(scores)),
        "score_max": float(np.max(scores)),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "rows_used": len(features),
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    joblib.dump(payload, output_path)
    print(f"Model saved to {output_path}")
    print(f"Rows used: {len(features)}")


if __name__ == "__main__":
    artifact_path = os.path.join(os.path.dirname(__file__), "app", "artifacts", "burnout_iforest.joblib")
    train_model(artifact_path)
