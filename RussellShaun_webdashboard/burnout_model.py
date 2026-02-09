import os
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

DEFAULT_METRICS = [
    "resting_hr",
    "vo2max",
    "training_load",
    "hr_response",
    "sleep_hours",
    "stress_level",
    "steps",
    "hrv",
    "work_hours",
]


class BurnoutIsolationForestModel:
    def __init__(self, model_path):
        self.model_path = model_path
        self.model = None
        self.baselines = {}
        self.global_baseline = {}
        self.metrics = []
        self.score_min = None
        self.score_max = None

    def fit_from_dataframe(self, df):
        df = df.copy()
        df = self._normalize_columns(df)

        if "athlete_id" not in df.columns:
            df["athlete_id"] = "default"
        if "timestamp" not in df.columns:
            df["timestamp"] = pd.date_range(start="2000-01-01", periods=len(df), freq="D")

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.sort_values(["athlete_id", "timestamp"])

        self.metrics = self._select_metrics(df)
        if not self.metrics:
            raise ValueError("No usable numeric metrics found in training data")

        self.baselines = self._build_baselines(df, self.metrics)
        self.global_baseline = self._build_global_baseline(df, self.metrics)

        features = self._build_feature_matrix(df)
        self.model = IsolationForest(
            n_estimators=200,
            contamination=0.1,
            random_state=42,
            n_jobs=-1,
        )
        self.model.fit(features)

        scores = self.model.decision_function(features)
        self.score_min = float(np.min(scores))
        self.score_max = float(np.max(scores))
        self._save()

    def predict_from_dict(self, data):
        if self.model is None:
            raise ValueError("Model is not trained. Train before predicting.")

        row = dict(data)
        if "athlete_id" not in row:
            row["athlete_id"] = "default"

        features = self._features_from_row(row).reshape(1, -1)
        score = float(self.model.decision_function(features)[0])
        risk = self._score_to_risk(score)
        insights = self._build_insights(row)

        return {
            "burnout_risk": risk,
            "score": score,
            "metrics_used": self.metrics,
            "insights": insights,
        }

    def load(self):
        if not os.path.exists(self.model_path):
            return False
        payload = joblib.load(self.model_path)
        self.model = payload.get("model")
        self.baselines = payload.get("baselines", {})
        self.global_baseline = payload.get("global_baseline", {})
        self.metrics = payload.get("metrics", [])
        self.score_min = payload.get("score_min")
        self.score_max = payload.get("score_max")
        return self.model is not None

    def _normalize_columns(self, df):
        df.columns = [c.strip().lower() for c in df.columns]
        return df

    def _select_metrics(self, df):
        metrics = [m for m in DEFAULT_METRICS if m in df.columns]
        if metrics:
            return metrics

        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        numeric_cols = [c for c in numeric_cols if c not in ("athlete_id", "timestamp")]
        return numeric_cols

    def _build_baselines(self, df, metrics):
        baselines = {}
        for athlete_id, group in df.groupby("athlete_id"):
            stats = {}
            for metric in metrics:
                series = pd.to_numeric(group[metric], errors="coerce")
                mean = float(series.mean()) if series.notna().any() else 0.0
                std = float(series.std()) if series.notna().any() else 1.0
                if std == 0:
                    std = 1.0
                stats[metric] = {"mean": mean, "std": std}
            baselines[str(athlete_id)] = stats
        return baselines

    def _build_global_baseline(self, df, metrics):
        stats = {}
        for metric in metrics:
            series = pd.to_numeric(df[metric], errors="coerce")
            mean = float(series.mean()) if series.notna().any() else 0.0
            std = float(series.std()) if series.notna().any() else 1.0
            if std == 0:
                std = 1.0
            stats[metric] = {"mean": mean, "std": std}
        return stats

    def _build_feature_matrix(self, df):
        rows = [self._features_from_row(row) for _, row in df.iterrows()]
        return np.vstack(rows)

    def _features_from_row(self, row):
        athlete_id = str(row.get("athlete_id", "default"))
        baseline = self.baselines.get(athlete_id, self.global_baseline)
        features = []

        for metric in self.metrics:
            val = row.get(metric, np.nan)
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = np.nan

            mean = baseline[metric]["mean"]
            std = baseline[metric]["std"]
            if np.isnan(val):
                z_score = 0.0
            else:
                z_score = (val - mean) / std
            features.append(z_score)

        return np.array(features, dtype=float)

    def _score_to_risk(self, score):
        if self.score_min is None or self.score_max is None:
            return 50.0
        if self.score_max == self.score_min:
            return 50.0
        norm = (score - self.score_min) / (self.score_max - self.score_min)
        risk = (1.0 - norm) * 100.0
        return float(np.clip(risk, 0.0, 100.0))

    def _build_insights(self, row):
        athlete_id = str(row.get("athlete_id", "default"))
        baseline = self.baselines.get(athlete_id, self.global_baseline)
        insights = []

        for metric in self.metrics:
            if metric not in row:
                continue
            try:
                val = float(row.get(metric))
            except (TypeError, ValueError):
                continue

            mean = baseline[metric]["mean"]
            std = baseline[metric]["std"]
            if std == 0:
                continue
            z_score = (val - mean) / std
            if abs(z_score) >= 2.0:
                direction = "above" if z_score > 0 else "below"
                insights.append(f"{metric} is {direction} baseline by {abs(z_score):.2f} std")

        return insights

    def _save(self):
        payload = {
            "model": self.model,
            "baselines": self.baselines,
            "global_baseline": self.global_baseline,
            "metrics": self.metrics,
            "score_min": self.score_min,
            "score_max": self.score_max,
            "saved_at": int(time.time()),
        }
        joblib.dump(payload, self.model_path)
