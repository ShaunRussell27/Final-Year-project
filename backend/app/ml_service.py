import os
from dataclasses import dataclass
from typing import Optional

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest

from .models import DailySummary


@dataclass
class ModelPrediction:
    risk_score: int
    risk_label: str
    explanation: list[str]


@dataclass
class NotebookModelPrediction:
    risk_score: int
    risk_label: str
    confidence: float
    explanation: list[str]


class BurnoutModelService:
    def __init__(self, artifact_path: Optional[str] = None):
        base_dir = os.path.dirname(__file__)
        self.artifact_path = artifact_path or os.path.join(base_dir, "artifacts", "burnout_iforest.joblib")
        self.model: Optional[IsolationForest] = None
        self.feature_names: list[str] = [
            "sleep_ratio",
            "resting_hr_delta",
            "steps_ratio",
            "avg_hr_delta",
        ]
        self.score_min: Optional[float] = None
        self.score_max: Optional[float] = None

    @property
    def is_ready(self) -> bool:
        return self.model is not None

    def load(self) -> bool:
        if not os.path.exists(self.artifact_path):
            return False

        payload = joblib.load(self.artifact_path)
        self.model = payload.get("model")
        self.feature_names = payload.get("feature_names", self.feature_names)
        self.score_min = payload.get("score_min")
        self.score_max = payload.get("score_max")
        return self.model is not None

    def predict(self, latest: DailySummary, baseline_rows: list[DailySummary]) -> Optional[ModelPrediction]:
        if not self.is_ready:
            return None

        features, explanation = self._build_features_and_explanations(latest, baseline_rows)
        features_df = pd.DataFrame([features], columns=self.feature_names)
        score = float(self.model.decision_function(features_df)[0])
        risk_score = self._score_to_risk(score)

        if risk_score >= 70:
            risk_label = "High"
        elif risk_score >= 40:
            risk_label = "Medium"
        else:
            risk_label = "Low"

        if not explanation:
            explanation = ["no major negative deviation versus baseline detected"]

        return ModelPrediction(
            risk_score=risk_score,
            risk_label=risk_label,
            explanation=explanation,
        )

    def _avg(self, values: list[float | int | None]) -> Optional[float]:
        numeric = [float(v) for v in values if v is not None]
        if not numeric:
            return None
        return sum(numeric) / len(numeric)

    def _build_features_and_explanations(
        self,
        latest: DailySummary,
        baseline_rows: list[DailySummary],
    ) -> tuple[list[float], list[str]]:
        baseline_sleep = self._avg([r.sleep_minutes for r in baseline_rows])
        baseline_resting_hr = self._avg([r.resting_hr for r in baseline_rows])
        baseline_steps = self._avg([r.steps for r in baseline_rows])
        baseline_avg_hr = self._avg([r.avg_hr for r in baseline_rows])

        explanation: list[str] = []

        sleep_ratio = 1.0
        if latest.sleep_minutes is not None and baseline_sleep and baseline_sleep > 0:
            sleep_ratio = float(latest.sleep_minutes / baseline_sleep)
            if sleep_ratio < 0.85:
                explanation.append("sleep is below 7-day baseline")

        resting_hr_delta = 0.0
        if latest.resting_hr is not None and baseline_resting_hr is not None:
            resting_hr_delta = float(latest.resting_hr - baseline_resting_hr)
            if resting_hr_delta >= 4:
                explanation.append("resting heart rate is above baseline")

        steps_ratio = 1.0
        if latest.steps is not None and baseline_steps and baseline_steps > 0:
            steps_ratio = float(latest.steps / baseline_steps)
            if steps_ratio < 0.75:
                explanation.append("steps are below baseline")

        avg_hr_delta = 0.0
        if latest.avg_hr is not None and baseline_avg_hr is not None:
            avg_hr_delta = float(latest.avg_hr - baseline_avg_hr)

        features = [sleep_ratio, resting_hr_delta, steps_ratio, avg_hr_delta]
        return features, explanation

    def _score_to_risk(self, score: float) -> int:
        if self.score_min is None or self.score_max is None or self.score_max == self.score_min:
            return 50

        normalized = (score - self.score_min) / (self.score_max - self.score_min)
        risk = (1.0 - normalized) * 100.0
        risk = max(0.0, min(100.0, risk))
        return int(round(risk))


class NotebookBurnoutModelService:
    def __init__(self, model_path: Optional[str] = None, scaler_path: Optional[str] = None):
        base_dir = os.path.dirname(__file__)
        project_root = os.path.abspath(os.path.join(base_dir, "..", ".."))
        default_model_path = os.path.join(project_root, "notebooks", "burnout_model.pkl")
        default_scaler_path = os.path.join(project_root, "notebooks", "scaler.pkl")

        self.model_path = model_path or default_model_path
        self.scaler_path = scaler_path or default_scaler_path

        self.model = None
        self.scaler = None
        self.feature_names = ["HR", "RMSSD", "SDRR", "MEAN_RR", "MEDIAN_RR"]

    @property
    def is_ready(self) -> bool:
        return self.model is not None and self.scaler is not None

    def load(self) -> bool:
        if not os.path.exists(self.model_path) or not os.path.exists(self.scaler_path):
            return False

        self.model = joblib.load(self.model_path)
        self.scaler = joblib.load(self.scaler_path)
        return self.is_ready

    @staticmethod
    def _is_stress_label(label: object) -> bool:
        label_text = str(label).strip().lower()
        if label_text in {
            "1",
            "1.0",
            "2",
            "2.0",
            "true",
            "stressed",
            "stress",
            "burnout",
            "high",
            "medium",
            "interruption",
            "time pressure",
        }:
            return True
        try:
            return int(float(label_text)) > 0
        except ValueError:
            return False

    def predict(
        self,
        resting_hr: Optional[float],
        avg_hr: Optional[float],
        hrv_avg: float,
    ) -> Optional[NotebookModelPrediction]:
        if not self.is_ready:
            return None

        hr_value = resting_hr if resting_hr is not None else avg_hr
        if hr_value is None or hr_value <= 0 or hrv_avg <= 0:
            return None

        feature_values = {
            "HR": float(hr_value),
            "RMSSD": float(hrv_avg),
            "SDRR": float(hrv_avg) * 1.1,
            "MEAN_RR": 60000.0 / float(hr_value),
            "MEDIAN_RR": 60000.0 / float(hr_value),
        }

        features_df = pd.DataFrame([feature_values], columns=self.feature_names)
        scaled = self.scaler.transform(features_df)

        pred_raw = self.model.predict(scaled)[0]
        is_predicted_stressed = self._is_stress_label(pred_raw)

        stress_probability = 0.0
        if hasattr(self.model, "predict_proba"):
            probabilities = self.model.predict_proba(scaled)[0]
            classes = list(getattr(self.model, "classes_", []))
            stress_class_index = next(
                (index for index, cls in enumerate(classes) if self._is_stress_label(cls)),
                None,
            )

            if stress_class_index is not None:
                stress_probability = float(probabilities[stress_class_index])
            elif len(probabilities) == 2:
                stress_probability = float(max(probabilities) if is_predicted_stressed else min(probabilities))
            else:
                stress_probability = float(max(probabilities))

        confidence = round(stress_probability * 100.0, 2)
        risk_score = int(round(stress_probability * 100.0))

        if is_predicted_stressed and risk_score >= 70:
            risk_label = "High"
        elif is_predicted_stressed:
            risk_label = "Medium"
        else:
            risk_label = "Low"

        explanation = [
            f"notebook model classified sample as {'stressed' if is_predicted_stressed else 'normal'}",
            f"stressed-class probability: {confidence:.2f}%",
        ]

        return NotebookModelPrediction(
            risk_score=risk_score,
            risk_label=risk_label,
            confidence=confidence,
            explanation=explanation,
        )
