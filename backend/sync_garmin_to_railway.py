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


def _write_token_from_env(token_path: str) -> bool:
    """Restore garth token files from GARMIN_TOKEN_JSON env var (survives Railway restarts)."""
    token_json_env = os.getenv("GARMIN_TOKEN_JSON", "").strip()
    if not token_json_env:
        return False
    try:
        token_data: dict[str, str] = json.loads(token_json_env)
        os.makedirs(token_path, exist_ok=True)
        for filename, contents in token_data.items():
            with open(os.path.join(token_path, filename), "w", encoding="utf-8") as f:
                f.write(contents)
        return True
    except Exception:
        return False


def _read_token_to_json(token_path: str) -> str | None:
    """Serialize garth token directory to a JSON string for storage as an env var."""
    try:
        token_data: dict[str, str] = {}
        for fname in os.listdir(token_path):
            fpath = os.path.join(token_path, fname)
            if os.path.isfile(fpath):
                with open(fpath, encoding="utf-8") as f:
                    token_data[fname] = f.read()
        return json.dumps(token_data)
    except Exception:
        return None


def _get_client(email: str, password: str, token_store: str) -> Garmin:
    client = Garmin(email, password)

    token_path = str(Path(token_store).expanduser())
    token_parent = str(Path(token_path).expanduser().parent)
    os.makedirs(token_parent, exist_ok=True)

    # Railway filesystems are ephemeral — restore token from env var if available
    # so we don't have to call login() on every container restart.
    _write_token_from_env(token_path)

    token_loaded = False
    # garth>=0.4 uses .load(); older versions used .resume() — try both
    for load_method_name in ("load", "resume"):
        load_fn = getattr(client.garth, load_method_name, None)
        if load_fn is None:
            continue
        try:
            load_fn(token_path)
            token_loaded = True
            break
        except Exception:
            pass

    if not token_loaded:
        client.login()
        # Save token to disk
        for dump_method_name in ("dump",):
            dump_fn = getattr(client.garth, dump_method_name, None)
            if dump_fn:
                try:
                    dump_fn(token_path)
                except Exception:
                    pass
        # Print the new token so the user can set GARMIN_TOKEN_JSON on Railway
        # to prevent rate-limit (429) errors on future restarts.
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


def _garmin_call_with_retry(fn: Any, *args: Any, max_retries: int = 3) -> Any:
    """Call a Garmin API function with exponential backoff on 429 rate-limit errors."""
    for attempt in range(max_retries):
        try:
            return fn(*args)
        except Exception as exc:
            if "429" in str(exc) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2s, then 4s
                print(f"[GARMIN RATE LIMIT] 429 on attempt {attempt + 1}, retrying in {wait}s...")
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
    token_store = (os.getenv("GARMIN_TOKEN_STORE") or "").strip() or "~/.garth"

    if not user_id:
        user_id = garmin_email.split("@")[0]

    days_back = _get_int_env("GARMIN_DAYS_BACK", 7, minimum=1)

    # Reuse the cached client if credentials haven't changed — avoids the OAuth
    # token exchange on every periodic sync run (which causes 429 rate limits).
    cache_key = f"{garmin_email}:{token_store}"
    if _garmin_client_cache is None or _garmin_client_cache_key != cache_key:
        _garmin_client_cache = _get_client(garmin_email, garmin_password, token_store)
        _garmin_client_cache_key = cache_key
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

        # Brief pause between days to stay well within Garmin's rate limits
        time.sleep(1)
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
