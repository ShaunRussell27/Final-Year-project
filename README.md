# Final Year Project — Burnout Detection Platform

This repository contains an end-to-end burnout monitoring prototype that combines:
- Garmin metric collection and sync
- A FastAPI backend with risk endpoints
- Two risk model paths (backend model + notebook model)
- A web dashboard for analysis and visualization

## Current Architecture

- **Backend API**: `backend/app/main.py`
  - Stores daily summaries (`DailySummary`) in SQLite locally or Postgres on Railway.
  - Exposes ingest, summary, and risk endpoints.
  - Supports optional automatic Garmin sync loop via environment variables.

- **Garmin sync pipeline**: `backend/sync_garmin_to_railway.py`
  - Reads Garmin Connect data (steps, sleep, resting HR, HRV, etc.).
  - Sends daily summaries to `/ingest/healthkit`.
  - Fetches `/risk/latest` and `/risk/notebook` after sync.

- **Model services**: `backend/app/ml_service.py`
  - **Primary backend model**: Isolation Forest artifact `backend/app/artifacts/burnout_iforest.joblib` used by `/risk/latest`.
  - **Notebook model**: `notebooks/burnout_model.pkl` + `notebooks/scaler.pkl` used by `/risk/notebook`.

- **Web dashboard**: `RussellShaun_webdashboard/`
  - Burnout tab supports watch-data mode and manual metric override.

## Repository Layout

- `backend/` FastAPI app, DB models, model service, sync script, training script
- `notebooks/` notebook experiments and notebook model artifacts (`.pkl`)
- `RussellShaun_webdashboard/` static dashboard UI
- `data/` raw/processed datasets
- `docs/` architecture and pipeline notes

## Quick Start (Local)

### 1) Create and activate virtual environment

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

### 3) Run backend API

From repository root:

```bash
python -m uvicorn backend.app.main:app --reload
```

API docs: `http://127.0.0.1:8000/docs`

### 4) Open dashboard

Open `RussellShaun_webdashboard/index.html` in your browser.
Set `Backend URL` to your running API (for local: `http://127.0.0.1:8000`).

## Key API Endpoints

- `GET /health` — health check
- `GET /sync/status` — auto-sync state and last sync result
- `POST /ingest/healthkit` — upsert daily summary metrics
- `GET /summary/latest?user_id=...` — latest summary for a user
- `GET /risk/latest?user_id=...` — backend model risk (Isolation Forest / fallback scoring)
- `POST /risk/notebook` — notebook model risk using HR/HRV inputs

## Garmin Sync Configuration

Used by `backend/sync_garmin_to_railway.py` and startup auto-sync:

- `GARMIN_EMAIL` (required)
- `GARMIN_PASSWORD` (required)
- `BURNOUT_API_BASE_URL` (or `RAILWAY_PUBLIC_DOMAIN`)
- `BURNOUT_USER_ID` (optional; defaults to email prefix)
- `GARMIN_DAYS_BACK` (default `7`)
- `GARMIN_TOKEN_STORE` (default `~/.garth`)
- `GARMIN_AUTO_SYNC_ENABLED` (`true`/`false`, default `false`)
- `GARMIN_AUTO_SYNC_INTERVAL_MINUTES` (default `180`)
- `GARMIN_AUTO_SYNC_RUN_ON_STARTUP` (default `true`)

Run manual sync:

```bash
python backend/sync_garmin_to_railway.py
```

## Model Training Notes

- Train/update backend Isolation Forest artifact:

```bash
python backend/train_model.py
```

- Train/update calibrated notebook classifier artifact:

```bash
python backend/train_notebook_model.py
```

- Notebook model files are expected at:
  - `notebooks/burnout_model.pkl`
  - `notebooks/scaler.pkl`
  - `notebooks/burnout_model_metrics.json` (evaluation summary)

If notebook files are missing, `/risk/notebook` returns a 503 and clients can fall back to `/risk/latest`.

## Deployment Notes

- Root `Procfile` runs backend via:
  - `cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Database:
  - Local fallback: SQLite (`sqlite:///./burnout.db`)
  - Hosted: Postgres via `DATABASE_URL` (auto-normalized to `postgresql://`)

## Running the Tests

The test suite covers all API endpoints, ML model services, risk scoring logic, schema validation, and chatbot reply logic (63 tests total). No live server or external database is needed — tests run against an in-memory SQLite database automatically.

### 1) Navigate to the backend folder

```bash
cd backend
```

### 2) Run all tests

```bash
python -m pytest tests/test_backend.py -v
```

Expected output: `63 passed` in approximately 7–10 seconds.

### Useful options

```bash
# Shorter tracebacks on failure
python -m pytest tests/test_backend.py -v --tb=short

# Run only a specific test class
python -m pytest tests/test_backend.py::TestComputeRiskLogic -v

# Run only a specific test
python -m pytest tests/test_backend.py::TestChatbotCoach::test_chatbot_with_data_returns_personalized_reply -v

# Quiet summary only
python -m pytest tests/test_backend.py -q
```

### Test file location

```
backend/
  tests/
    test_backend.py   ← all 63 tests
```

## Project Status

This README reflects the current burnout detection stack in this repository and replaces the old scrapped project documentation.