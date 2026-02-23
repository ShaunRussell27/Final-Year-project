# Garmin → Railway → Burnout Model Automation

This automation pulls your Garmin daily metrics using Python libraries, sends them to your Railway backend, and fetches the latest burnout risk score.

## 1) Install dependencies

From [backend/](../backend):

```bash
pip install -r requirements.txt
```

## 2) Configure environment

Copy [backend/.env.example](../backend/.env.example) to `.env` in `backend/` and fill values:

- `BURNOUT_API_BASE_URL`: your Railway FastAPI base URL
- `BURNOUT_USER_ID`: your app user id
- `GARMIN_EMAIL`: your Garmin account email
- `GARMIN_PASSWORD`: your Garmin password
- `GARMIN_TOKEN_STORE`: token cache path (default `~/.garth`)
- `GARMIN_DAYS_BACK`: number of days to sync each run
- `SYNC_OUTPUT_JSON`: output file for run summary

## 3) Run sync manually

From [backend/](../backend):

```bash
python sync_garmin_to_railway.py
```

What it does:
1. Pulls Garmin metrics per day (`steps`, `sleep_minutes`, `resting_hr`, `avg_hr`)
2. Posts each day to `/ingest/healthkit` on your Railway backend
3. Calls `/risk/latest?user_id=...`
4. Writes a summary JSON (default: `sync_result.json`)

## 4) Schedule daily on Windows (Task Scheduler)

Use Program/script:

```text
C:\path\to\python.exe
```

Use Add arguments:

```text
sync_garmin_to_railway.py
```

Use Start in:

```text
C:\Users\shaun\OneDrive - Atlantic TU\3RD YEAR\Research Emerging technologie\Final-Year-project\backend
```

Set trigger to run once daily at your preferred time.
