import argparse
import json
import os
from datetime import datetime, timezone

import joblib
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import StandardScaler


FEATURE_COLUMNS = ["HR", "RMSSD", "SDRR", "MEAN_RR", "MEDIAN_RR"]
TARGET_COLUMN = "Condition Label"


def _load_frame(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [col for col in FEATURE_COLUMNS + [TARGET_COLUMN] if col not in df.columns]
    if missing:
        raise RuntimeError(f"Missing expected columns in {path}: {missing}")

    clean = df[FEATURE_COLUMNS + [TARGET_COLUMN]].copy()
    clean[TARGET_COLUMN] = pd.to_numeric(clean[TARGET_COLUMN], errors="coerce")
    for col in FEATURE_COLUMNS:
        clean[col] = pd.to_numeric(clean[col], errors="coerce")

    clean = clean.dropna(subset=FEATURE_COLUMNS + [TARGET_COLUMN])
    clean[TARGET_COLUMN] = clean[TARGET_COLUMN].astype(int)
    return clean


def _to_binary_stress_label(series: pd.Series) -> pd.Series:
    # Dataset encoding used by this project: Condition Label 0 denotes stressed.
    return (series == 0).astype(int)


def train_notebook_model(train_csv: str, test_csv: str, model_out: str, scaler_out: str, metrics_out: str) -> None:
    train_df = _load_frame(train_csv)
    test_df = _load_frame(test_csv)

    x_train = train_df[FEATURE_COLUMNS]
    x_test = test_df[FEATURE_COLUMNS]
    y_train = _to_binary_stress_label(train_df[TARGET_COLUMN])
    y_test = _to_binary_stress_label(test_df[TARGET_COLUMN])

    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)
    x_test_scaled = scaler.transform(x_test)

    base_model = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)
    calibrated_model = CalibratedClassifierCV(estimator=base_model, method="sigmoid", cv=5)
    calibrated_model.fit(x_train_scaled, y_train)

    y_prob = calibrated_model.predict_proba(x_test_scaled)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": FEATURE_COLUMNS,
        "target_definition": "Condition Label == 0 => stressed (1)",
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "stress_prevalence_train": float(y_train.mean()),
        "stress_prevalence_test": float(y_test.mean()),
        "roc_auc": float(roc_auc_score(y_test, y_prob)),
        "brier_score": float(brier_score_loss(y_test, y_prob)),
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
    }

    os.makedirs(os.path.dirname(model_out), exist_ok=True)
    os.makedirs(os.path.dirname(scaler_out), exist_ok=True)
    os.makedirs(os.path.dirname(metrics_out), exist_ok=True)

    joblib.dump(calibrated_model, model_out)
    joblib.dump(scaler, scaler_out)
    with open(metrics_out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(f"Saved calibrated notebook model to: {model_out}")
    print(f"Saved scaler to: {scaler_out}")
    print(f"Saved metrics to: {metrics_out}")
    print("Evaluation metrics:")
    for key in ["roc_auc", "brier_score", "accuracy", "precision", "recall", "f1"]:
        print(f"  {key}: {metrics[key]:.4f}")


def _default_paths(project_root: str) -> tuple[str, str, str, str, str]:
    train_csv = os.path.join(
        project_root,
        "notebooks",
        "swellwesad-hrv-data",
        "HRV Dataset",
        "combined-swell-classification-hrv-train-dataset.csv",
    )
    test_csv = os.path.join(
        project_root,
        "notebooks",
        "swellwesad-hrv-data",
        "HRV Dataset",
        "combined-swell-classification-hrv-test-dataset.csv",
    )
    model_out = os.path.join(project_root, "notebooks", "burnout_model.pkl")
    scaler_out = os.path.join(project_root, "notebooks", "scaler.pkl")
    metrics_out = os.path.join(project_root, "notebooks", "burnout_model_metrics.json")
    return train_csv, test_csv, model_out, scaler_out, metrics_out


if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    defaults = _default_paths(root)

    parser = argparse.ArgumentParser(description="Train calibrated notebook burnout model")
    parser.add_argument("--train-csv", default=defaults[0])
    parser.add_argument("--test-csv", default=defaults[1])
    parser.add_argument("--model-out", default=defaults[2])
    parser.add_argument("--scaler-out", default=defaults[3])
    parser.add_argument("--metrics-out", default=defaults[4])

    args = parser.parse_args()
    train_notebook_model(
        train_csv=args.train_csv,
        test_csv=args.test_csv,
        model_out=args.model_out,
        scaler_out=args.scaler_out,
        metrics_out=args.metrics_out,
    )