# System Architecture

## Overview

This project is an end-to-end burnout monitoring platform that collects physiological data from a Garmin wearable, stores and processes it via a REST API backend, applies machine learning models to produce a burnout risk score, and presents results through a web dashboard.

---

## High-Level Architecture

```
[ Garmin Connect ]
       |
       | (garminconnect Python library)
       v
[ sync_garmin_to_railway.py ]   <-- runs manually or on a schedule
       |
       | POST /ingest/healthkit
       v
[ FastAPI Backend (Railway) ]
       |
       |-- SQLite (local dev) / PostgreSQL (Railway production)
       |-- BurnoutModelService  (Isolation Forest)
       |-- NotebookBurnoutModelService  (Logistic Regression / notebook model)
       |-- Groq LLM API  (conversational chatbot)
       |
       | JSON responses
       v
[ Web Dashboard (static HTML/CSS/JS) ]
       |
       |-- Burnout risk display
       |-- Manual metric override
       |-- AI chatbot interface
```

---

## Components

### 1. Garmin Sync Pipeline (`backend/sync_garmin_to_railway.py`)

- Authenticates with Garmin Connect using the `garminconnect` library with token caching via `garth`.
- Pulls daily metrics: resting HR, HRV, steps, sleep duration, average HR.
- POSTs each day's data to `POST /ingest/healthkit` on the backend.
- After sync, fetches `/risk/latest` and `/risk/notebook` to confirm scores.
- Can also be triggered automatically by the backend on a configurable interval via environment variables (`GARMIN_AUTO_SYNC_ENABLED`, `GARMIN_AUTO_SYNC_INTERVAL_MINUTES`).

### 2. FastAPI Backend (`backend/app/`)

Deployed on Railway. Key files:

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, route definitions, auto-sync loop |
| `models.py` | SQLAlchemy ORM model (`DailySummary`) |
| `schemas.py` | Pydantic request/response schemas |
| `db.py` | Database engine and session setup |
| `ml_service.py` | Isolation Forest and notebook model service classes |

#### Key Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check |
| `/sync/status` | GET | Garmin auto-sync state and last run result |
| `/ingest/healthkit` | POST | Ingest a daily health summary (JSON) |
| `/ingest/garmin-export` | POST | Upload a Garmin export file (multipart) |
| `/summary/latest` | GET | Latest daily summary for a user (`?user_id=`) |
| `/summaries` | GET | Paginated list of summaries for a user (`?user_id=&limit=30`) |
| `/risk/latest` | GET | Burnout risk from blended Isolation Forest + notebook model |
| `/risk/notebook` | POST | Burnout risk from notebook model using HR/HRV inputs |
| `/chatbot/coach` | POST | AI coaching chatbot (Groq LLM with rule-based fallback) |

#### Database

- **Local development**: SQLite file-based database.
- **Production (Railway)**: PostgreSQL, connection string injected via `DATABASE_URL` environment variable.
- Schema is created on startup via `Base.metadata.create_all()`.
- Upsert logic prevents duplicate records for the same `user_id` + `date`.

### 3. Machine Learning Service (`backend/app/ml_service.py`)

Two model paths run in parallel:

**Primary Model — Isolation Forest (`BurnoutModelService`)**
- Artifact: `backend/app/artifacts/burnout_iforest.joblib`
- Features: `sleep_ratio`, `resting_hr_delta`, `steps_ratio`, `avg_hr_delta` (all derived relative to a rolling baseline)
- Produces a 0–100 risk score and a risk label (Low / Moderate / High)
- Used by `/risk/latest`

**Notebook Model — Logistic Regression (`NotebookBurnoutModelService`)**
- Artifacts: `notebooks/burnout_model.pkl` + `notebooks/scaler.pkl`
- Features: `HR`, `RMSSD`, `SDRR`, `MEAN_RR`, `MEDIAN_RR`
- Trained on the combined SWELL-WESAD HRV dataset (313,310 training rows)
- Target: Condition Label == 0 → stressed (1)
- Used by `/risk/notebook`

### 4. Web Dashboard (`RussellShaun_webdashboard/`)

Static HTML/CSS/JavaScript single-page application. Sections:

- **Home** — overview and navigation
- **Burnout** — displays latest risk scores from both models; supports watch-data mode and manual metric override form
- **Chatbot** — AI assistant powered by the backend `/chat` endpoint (Groq LLM)

The dashboard communicates with the backend via `fetch()` API calls to the Railway-deployed URL.

---

## Deployment

| Component | Platform |
|---|---|
| FastAPI Backend | Railway (containerised, auto-deploy from GitHub) |
| Database | Railway PostgreSQL plugin |
| Web Dashboard | Static files (served locally or via any static host) |
| Garmin Sync | Runs as a background task within the Railway backend process |

---

## Data Flow Summary

1. Garmin sync script pulls metrics from Garmin Connect and POSTs to `/ingest/healthkit`.
2. Backend stores the daily summary in the database.
3. On a `/risk/latest` request, the Isolation Forest model compares the latest summary against a 30-day rolling baseline and returns a risk score.
4. On a `/risk/notebook` request, the notebook model runs HRV-based inference and returns a stress probability.
5. The dashboard polls both endpoints and displays the results to the user.
