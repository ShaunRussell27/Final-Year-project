import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any


import requests
from dotenv import load_dotenv
from garminconnect import Garmin


load_dotenv()

# Cached Garmin client — reused across sync runs to avoid the OAuth token
# exchange (oauth/exchange/user/2.0) being called every 3 hours, which
# triggers Garmin's rate limiter (429).
_garmin_client_cache: Garmin | None = None
_garmin_client_cache_key: str = ""


def _get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_int_env(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise RuntimeError(f"Invalid integer for {name}: {raw!r}") from exc

    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


def _get_api_base_url() -> str:
    explicit = os.getenv("BURNOUT_API_BASE_URL")
    if explicit:
        return explicit.rstrip("/")

    railway_public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_public_domain:
        domain = railway_public_domain.strip().rstrip("/")
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain
        return f"https://{domain}"

    raise RuntimeError(
        "Missing required environment variable: BURNOUT_API_BASE_URL "
        "(or RAILWAY_PUBLIC_DOMAIN)"
    )



# New: Write the unified garminconnect token file from GARMIN_TOKEN_JSON env var
def _write_token_from_env(token_path: str) -> bool:
    token_json_env = os.getenv("GARMIN_TOKEN_JSON", "").strip()
    if not token_json_env:
        return False
    try:
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(token_json_env)
        return True
    except Exception:
        return False



# New: Read the unified garminconnect token file as a JSON string for Railway
def _read_token_to_json(token_path: str) -> str | None:
    try:
        with open(token_path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None



# New: Use garminconnect>=0.3.3 token logic
def _get_client(email: str, password: str, token_store: str) -> Garmin:
    token_path = str(Path(token_store).expanduser())
    token_parent = str(Path(token_path).expanduser().parent)
    os.makedirs(token_parent, exist_ok=True)

    # Restore token from env var if present
    _write_token_from_env(token_path)

    # Try to load token file
    import garth
    client = None
    token_loaded = False
    try:
        client = Garmin()
        # Ensure garth attribute exists (for older/newer garminconnect versions)
        if not hasattr(client, "garth") or client.garth is None:
            client.garth = garth.Client(domain="garmin.com")
        client.garth.load(token_path)
        token_loaded = True
    except Exception:
        pass

    if not token_loaded:
        # No valid token, perform login and save token
        client = Garmin(email, password)
        if not hasattr(client, "garth") or client.garth is None:
            client.garth = garth.Client(domain="garmin.com")
        client.login()
        client.garth.dump(token_path)
        # Print the new token so the user can set GARMIN_TOKEN_JSON on Railway
        token_json = _read_token_to_json(token_path)
        if token_json:
            print(
                "\n[GARMIN AUTH] Fresh login performed. To avoid 429 rate-limit errors "
                "on Railway restarts, set the following value as the GARMIN_TOKEN_JSON "
                "environment variable in your Railway service settings:\n"
                f"{token_json}\n"
            )
    return client


def _safe_get(d: dict[str, Any] | None, *keys: str) -> Any:
    current: Any = d
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


# Garmin enforces a short-term call budget. These waits give the rate-limit
# window time to clear between retries (30 s → 90 s → 180 s).
_RATE_LIMIT_BACKOFF_SECONDS = [30, 90, 180]


def _garmin_call_with_retry(fn: Any, *args: Any, max_retries: int = 3) -> Any:
    """Call a Garmin API function with exponential backoff on 429 rate-limit errors."""
    for attempt in range(max_retries):
        try:
            return fn(*args)
        except Exception as exc:
            if "429" in str(exc) and attempt < max_retries - 1:
                wait = _RATE_LIMIT_BACKOFF_SECONDS[min(attempt, len(_RATE_LIMIT_BACKOFF_SECONDS) - 1)]
                print(f"[GARMIN RATE LIMIT] 429 on attempt {attempt + 1}, waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                raise


def _collect_day(client: Garmin, date_str: str) -> dict[str, Any]:
    stats = _garmin_call_with_retry(client.get_stats, date_str)
    hrv_data = _garmin_call_with_retry(client.get_hrv_data, date_str)
    sleep_data = _garmin_call_with_retry(client.get_sleep_data, date_str)

    total_steps = _safe_get(stats, "totalSteps")
    resting_hr = _safe_get(stats, "restingHeartRate")

    sleep_seconds = _safe_get(sleep_data, "dailySleepDTO", "sleepTimeSeconds")
    sleep_minutes = int(sleep_seconds / 60) if isinstance(sleep_seconds, (int, float)) else None

    avg_sleep_hr = _safe_get(sleep_data, "dailySleepDTO", "avgSleepHeartRate")
    sleep_score = _safe_get(sleep_data, "dailySleepDTO", "sleepScore")

    hrv_avg = _safe_get(hrv_data, "hrvSummary", "lastNightAvg")

    return {
        "date": date_str,
        "steps": total_steps,
        "sleep_minutes": sleep_minutes,
        "resting_hr": resting_hr,
        "avg_hr": avg_sleep_hr,
        "hrv_avg": hrv_avg,
        "avg_stress": _safe_get(stats, "averageStressLevel"),
        "max_stress": _safe_get(stats, "maxStressLevel"),
        "body_battery_max": _safe_get(stats, "bodyBatteryHighestValue"),
        "sleep_score": sleep_score,
    }


def _to_ingest_payload(user_id: str, day_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "date": day_data["date"],
        "steps": day_data.get("steps"),
        "sleep_minutes": day_data.get("sleep_minutes"),
        "resting_hr": day_data.get("resting_hr"),
        "avg_hr": day_data.get("avg_hr"),
        "hr_samples_count": None,
        "avg_stress": day_data.get("avg_stress"),
        "max_stress": day_data.get("max_stress"),
        "body_battery_max": day_data.get("body_battery_max"),
        "sleep_score": day_data.get("sleep_score"),
        "hrv_avg": day_data.get("hrv_avg"),
    }


def _request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
    response = requests.request(method=method, url=url, timeout=30, **kwargs)
    response.raise_for_status()
    if response.content:
        return response.json()
    return {}


def _request_notebook_risk_report(
    api_base_url: str,
    user_id: str,
    day_data: dict[str, Any],
) -> dict[str, Any] | None:
    hrv_avg = day_data.get("hrv_avg")
    resting_hr = day_data.get("resting_hr")
    avg_hr = day_data.get("avg_hr")

    if hrv_avg is None or ((resting_hr is None) and (avg_hr is None)):
        return None

    notebook_payload = {
        "user_id": user_id,
        "date": day_data.get("date"),
        "resting_hr": resting_hr,
        "avg_hr": avg_hr,
        "hrv_avg": hrv_avg,
    }

    return _request_json("POST", f"{api_base_url}/risk/notebook", json=notebook_payload)


def run_sync() -> dict[str, Any]:
    global _garmin_client_cache, _garmin_client_cache_key

    api_base_url = _get_api_base_url()
    user_id = os.getenv("BURNOUT_USER_ID")


    garmin_email = _get_required_env("GARMIN_EMAIL")
    garmin_password = _get_required_env("GARMIN_PASSWORD")
    # Use new default token file name
    token_store = (os.getenv("GARMIN_TOKEN_STORE") or "").strip() or "~/.garminconnect/garmin_tokens.json"

    if not user_id:
        user_id = garmin_email.split("@")[0]

    days_back = _get_int_env("GARMIN_DAYS_BACK", 7, minimum=1)

    # Reuse the cached client if credentials haven't changed — avoids the OAuth
    # token exchange on every periodic sync run (which causes 429 rate limits).
    cache_key = f"{garmin_email}:{token_store}"
    if _garmin_client_cache is None or _garmin_client_cache_key != cache_key:
        try:
            _garmin_client_cache = _get_client(garmin_email, garmin_password, token_store)
            _garmin_client_cache_key = cache_key
        except Exception as auth_exc:
            # If the OAuth token exchange itself was rate-limited, bust the cache
            # so the next run attempts a fresh client rather than reusing a broken one.
            auth_reason = str(auth_exc)
            if "oauth/exchange" in auth_reason.lower() and "429" in auth_reason:
                _garmin_client_cache = None
                _garmin_client_cache_key = ""
                print(
                    "[GARMIN AUTH] OAuth exchange rate-limited (429) during client "
                    "initialisation. Client cache cleared. Sync aborted."
                )
            raise
    client = _garmin_client_cache

    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=days_back - 1)

    ingested = 0
    skipped_days: list[dict[str, str]] = []
    day_snapshots: list[dict[str, Any]] = []
    latest_day_data: dict[str, Any] | None = None

    current = start_date
    while current <= end_date:
        date_str = current.isoformat()

        try:
            day_data = _collect_day(client, date_str)
            payload = _to_ingest_payload(user_id, day_data)
            _request_json("POST", f"{api_base_url}/ingest/healthkit", json=payload)
            ingested += 1
            latest_day_data = day_data
            day_snapshots.append(day_data)
        except Exception as exc:
            reason = str(exc)
            # If the session has expired (401) or auth was rejected, bust the client
            # cache so the next sync run forces a fresh login.
            if "401" in reason or "403" in reason or "Unauthorized" in reason:
                _garmin_client_cache = None
                _garmin_client_cache_key = ""
            skipped_days.append({"date": date_str, "reason": reason})
            # If Garmin is still rate-limiting after all retries, pause before the
            # next day so we don't burn through the remaining quota immediately.
            if "429" in reason:
                print("[GARMIN RATE LIMIT] Still rate-limited after retries — pausing 60s before next day.")
                time.sleep(60)
                current += dt.timedelta(days=1)
                continue

        # Brief pause between days to stay well within Garmin's rate limits
        time.sleep(2)
        current += dt.timedelta(days=1)

    try:
        risk_latest = _request_json("GET", f"{api_base_url}/risk/latest", params={"user_id": user_id})
    except Exception as exc:
        risk_latest = {"error": str(exc)}

    notebook_risk: dict[str, Any] | None = None
    notebook_risk_error: str | None = None
    if latest_day_data is not None:
        try:
            notebook_risk = _request_notebook_risk_report(api_base_url, user_id, latest_day_data)
        except Exception as exc:
            notebook_risk_error = str(exc)


    # After a successful sync, persist the fresh token and print for Railway
    if ingested > 0:
        try:
            token_path_expanded = str(Path(token_store).expanduser())
            client.garth.dump(token_path_expanded)
            fresh_token_json = _read_token_to_json(token_path_expanded)
            if fresh_token_json:
                print(
                    "\n[GARMIN TOKEN — ACTION REQUIRED] "
                    "Garmin data was synced successfully. "
                    "Copy the value below and save it as the GARMIN_TOKEN_JSON "
                    "environment variable in Railway to prevent 429 rate-limit "
                    "errors on future container restarts:\n"
                    f"{fresh_token_json}\n"
                )
        except Exception:
            pass

    result = {
        "user_id": user_id,
        "api_base_url": api_base_url,
        "date_window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days_requested": days_back,
        },
        "ingested_days": ingested,
        "skipped_days": skipped_days,
        "latest_risk": risk_latest,
        "notebook_model_risk": notebook_risk,
        "notebook_model_risk_error": notebook_risk_error,
        "latest_day_data": latest_day_data,
        "garmin_day_snapshots": day_snapshots,
        "token_store": str(Path(token_store).expanduser()),
    }

    output_path = (os.getenv("SYNC_OUTPUT_JSON") or "").strip() or "sync_result.json"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception as exc:
        result["sync_output_write_error"] = str(exc)

    return result


if __name__ == "__main__":
    sync_result = run_sync()
    print(json.dumps(sync_result, indent=2))
