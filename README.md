# Final Year Project — Burnout Detection Platform

**Shaun Russell | L00181248 | Computer Science | Atlantic TU**

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
  - **Primary model — Isolation Forest** (`BurnoutModelService`): artifact `backend/app/artifacts/burnout_iforest.joblib`, used by `/risk/latest`. Features: `sleep_ratio`, `resting_hr_delta`, `steps_ratio`, `avg_hr_delta` (all derived relative to a 30-day rolling baseline). Outputs a 0–100 risk score and a Low / Moderate / High label.
  - **Notebook model — Logistic Regression** (`NotebookBurnoutModelService`): artifacts `notebooks/burnout_model.pkl` + `notebooks/scaler.pkl`, used by `/risk/notebook`. Features: `HR`, `RMSSD`, `SDRR`, `MEAN_RR`, `MEDIAN_RR`. Trained on the combined SWELL-WESAD HRV dataset (313,310 training rows). Target: Condition Label == 0 → stressed.

- **Web dashboard**: `RussellShaun_webdashboard/`
  - Burnout tab supports watch-data mode and manual metric override.
  - Chatbot tab (`sections/chatbot.html`, `chatbot.js`) provides an AI coaching assistant powered by the `/chatbot/coach` endpoint, falling back to rule-based replies when no LLM key is configured.

## Backend File Reference

| File | Purpose |
|---|---|
| `backend/app/main.py` | FastAPI app, route definitions, auto-sync loop |
| `backend/app/models.py` | SQLAlchemy ORM model (`DailySummary`) |
| `backend/app/schemas.py` | Pydantic request/response schemas |
| `backend/app/db.py` | Database engine and session setup |
| `backend/app/ml_service.py` | Isolation Forest and notebook model service classes |

## Repository Layout

- `backend/` FastAPI app, DB models, model service, sync script, training script
- `notebooks/` notebook experiments and notebook model artifacts (`.pkl`)
- `RussellShaun_webdashboard/` static dashboard UI

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
- `POST /ingest/healthkit` — upsert daily summary metrics (JSON payload)
- `POST /ingest/garmin-export` — store a raw Garmin export file (multipart upload; MVP stores metadata only)
- `GET /summary/latest?user_id=...` — latest summary for a user
- `GET /summaries?user_id=...&limit=30` — paginated list of summaries for a user (newest first)
- `GET /risk/latest?user_id=...` — backend model risk (Isolation Forest / fallback scoring)
- `POST /risk/notebook` — notebook model risk using HR/HRV inputs
- `POST /chatbot/coach` — AI coaching chatbot; uses Groq LLM when `GROQ_API_KEY` is set, falls back to rule-based replies

## Chatbot / AI Coach

The `/chatbot/coach` endpoint accepts a `user_id`, a `message`, and an optional `history` array. It:
1. Fetches the user's latest daily summary and risk score from the database.
2. If `GROQ_API_KEY` is set, calls the Groq LLM with a personalised system prompt.
3. Otherwise falls back to rule-based keyword matching (stress, sleep, plan, etc.) for a contextual reply.

The dashboard chatbot UI (`sections/chatbot.html`) calls this endpoint and displays the reply inline.

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

## Deployment

| Component | Platform |
|---|---|
| FastAPI Backend | Railway (auto-deploy from GitHub) |
| Database | Railway PostgreSQL plugin |
| Web Dashboard | Static files (served locally or via any static host) |
| Garmin Sync | Background task within the Railway backend process |

- Root `Procfile` runs backend via:
  - `cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Database:
  - Local fallback: SQLite (`sqlite:///./burnout.db`)
  - Hosted: Postgres via `DATABASE_URL` (auto-normalized to `postgresql://`)

## Data Flow

1. Garmin sync script pulls metrics from Garmin Connect and POSTs to `/ingest/healthkit`.
2. Backend stores the daily summary in the database.
3. On a `/risk/latest` request, the Isolation Forest model compares the latest summary against a 30-day rolling baseline and returns a risk score.
4. On a `/risk/notebook` request, the notebook model runs HRV-based inference and returns a stress probability.
5. The dashboard polls both endpoints and displays the results to the user.

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