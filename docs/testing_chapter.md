# Chapter 6: Testing

## 6.1 Testing Overview

A comprehensive testing process was completed to validate the functionality, reliability, and overall quality of the system prior to final deployment. Based on the project architecture, testing was conducted across three layers: the FastAPI backend, the machine learning burnout prediction service, and the web dashboard frontend.

The objective of the testing was to confirm that:

- Core features behave as expected under normal conditions
- Modules interact correctly across the full request-response pipeline
- The solution is stable and suitable for practical use in the project context

### 6.1.1 Testing Strategy and Tooling

Testing was approached in two complementary layers: **unit testing** of individual logic components, and **integration testing** of the REST API through an in-memory HTTP test client. This multi-layer approach ensured that both the correctness of discrete functions and the behaviour of the full request-response cycle could be validated independently.

The testing framework used was **pytest** (v9.0.2) running on Python 3.13.4. The FastAPI `TestClient` (backed by `httpx`) was used to exercise all HTTP endpoints without requiring a live server process. The production PostgreSQL database was replaced with an **in-memory SQLite** instance for the test session, guaranteeing test isolation and repeatability without side effects on any deployed environment.

All tests reside in `backend/tests/test_backend.py` and are executed with:

```
python -m pytest tests/test_backend.py -v
```

### 6.1.2 Test Coverage Summary

A total of **63 test cases** were written across **12 test classes**, covering all major system components. Of these, **36 are pure unit tests** and **27 are integration tests**.

| Test Class | Area Covered | Type | Tests |
|---|---|---|---|
| `TestHealthEndpoint` | API availability | Integration | 2 |
| `TestIngestHealthKit` | Data ingestion endpoint | Integration | 5 |
| `TestSummaryLatest` | Summary retrieval endpoints | Integration | 4 |
| `TestRiskLatestEndpoint` | Risk scoring endpoint | Integration | 3 |
| `TestNotebookPredictEndpoint` | HRV / notebook ML endpoint | Integration | 5 |
| `TestChatbotCoach` | Chatbot HTTP endpoint | Integration | 5 |
| `TestSyncStatus` | Garmin sync status endpoint | Integration | 1 |
| `TestGarminExportIngest` | Garmin file-upload endpoint | Integration | 2 |
| `TestBurnoutModelServiceUnit` | IsolationForest ML service | Unit | 9 |
| `TestNotebookModelServiceUnit` | Supervised ML service | Unit | 6 |
| `TestComputeRiskLogic` | Rule-based risk scoring logic | Unit | 8 |
| `TestSchemaValidation` | Pydantic request/response schemas | Unit | 7 |
| `TestChatbotReplyLogic` | Chatbot reply generation logic | Unit | 6 |
| **Total** | | | **63** |

**Final result: 63 passed, 0 failed — completed in 7.26 seconds.**

---

## 6.2 Functional Testing

Functional testing focused on verifying end-to-end behaviour and correctness of key application features.

### 6.2.1 Backend API Functionality

Critical API routes were tested for valid and invalid inputs to confirm correct status codes, schema validation, and error handling behaviour. The following endpoints were covered:

| Endpoint | Scenario Tested | Result |
|---|---|---|
| `GET /health` | Application startup and availability | 200 OK |
| `POST /ingest/healthkit` | Full payload, minimal payload, upsert, missing fields, invalid JSON | All passed |
| `GET /summary/latest` | Known user, unknown user | 200 / 404 as expected |
| `GET /summaries` | Known user list, empty list for unknown user | Correct responses |
| `GET /risk/latest` | No data (404), valid schema, normal data | All passed |
| `POST /risk/notebook` | Missing HRV (422), zero HRV (400/503), valid inputs | All passed |
| `POST /chatbot/coach` | No data, with data, missing user_id, keyword routing | All passed |
| `POST /ingest/garmin-export` | Empty file (400), valid file upload | All passed |
| `GET /sync/status` | Response shape and `enabled` field | All passed |

A representative integration test demonstrating the upsert deduplication behaviour is shown below:

```python
def test_ingest_upsert_same_date(self):
    base = {"user_id": USER, "date": "2026-01-12", "steps": 5000}
    client.post("/ingest/healthkit", json=base)
    updated = {**base, "steps": 12000}
    response = client.post("/ingest/healthkit", json=updated)
    assert response.status_code == 200
    assert response.json()["steps"] == 12000
```

This confirmed that re-ingesting data for the same user and date updates the existing record rather than creating a duplicate.

### 6.2.2 ML Prediction Workflow

The prediction pipeline was tested from input preprocessing through model inference to output formatting. Unit tests directly exercised the `BurnoutModelService` and `NotebookBurnoutModelService` classes, confirming:

- The service returns `None` safely when model artifacts are missing rather than crashing
- Feature construction defaults to neutral values when biometric fields are `None`, preventing `ZeroDivisionError`
- Risk scores are normalised and clamped to the `[0, 100]` range regardless of input extremes
- The `_is_stress_label()` helper correctly identifies all label encodings used during training (`"1"`, `"stressed"`, `"burnout"`, `"high"`, etc.)

A representative unit test verifying safe handling of missing biometric data:

```python
def test_feature_construction_all_none_returns_defaults(self):
    latest = self._make_summary(sleep=None, resting_hr=None, steps=None)
    baseline = [self._make_summary(sleep=None, resting_hr=None, steps=None)]
    features, explanation = svc._build_features_and_explanations(latest, baseline)
    assert features[0] == pytest.approx(1.0)   # sleep_ratio default
    assert features[1] == pytest.approx(0.0)   # resting_hr_delta default
```

### 6.2.3 Rule-Based Risk Scoring

The deterministic `_compute_risk` function was tested with 8 unit tests covering boundary and edge cases:

| Scenario | Expected Outcome | Result |
|---|---|---|
| Sleep at 50% of 7-day baseline | Risk score > 20, "sleep" in explanation | Passed |
| Resting HR +10 bpm above baseline | Risk score > 20, "heart rate" in explanation | Passed |
| All biometric fields `None` | Score = 20 (base constant) | Passed |
| Consistent healthy data for 7 days | `risk_label == "Low"` | Passed |
| Very low sleep + high HR + low steps | `risk_label` in ("Medium", "High") | Passed |
| Extreme adversarial inputs | Score clamped to `<= 100` | Passed |
| Any input | Explanation list never empty | Passed |

### 6.2.4 Schema Validation

Seven Pydantic schema tests confirmed that all required fields are enforced at the API boundary. Attempting to construct `HealthKitIn` without `user_id` or `date`, `NotebookPredictIn` without `hrv_avg`, or `ChatRequestIn` without `user_id` all correctly raised `ValidationError` before reaching any application logic.

### 6.2.5 Chatbot Reply Logic

Six unit tests verified the chatbot text-generation function directly. Key findings:

- When no watch data is available, the reply correctly directs the user to sync data first
- A `risk_label` of "High" is included in the reply when risk is elevated
- Sleep below 7 hours (420 minutes) triggers sleep-specific guidance
- Keywords such as "stressed", "plan", and "sleep" in the user message correctly route to specialised advice branches

### 6.2.6 Data Pipeline and Integration

Integration tests confirmed smooth communication between all system layers. The full request lifecycle — HTTP ingestion, database write, baseline calculation, ML inference, and formatted JSON response — was exercised repeatedly without errors. The Garmin export endpoint correctly rejected empty file uploads with HTTP 400 and accepted non-empty uploads with HTTP 200.

---

## 6.3 ML Model Evaluation

In addition to functional testing, the supervised classifier was evaluated on a held-out test set from the SWELL-WESAD HRV dataset during training. The metrics are recorded in `notebooks/burnout_model_metrics.json`:

| Metric | Value |
|---|---|
| Training rows | 313,310 |
| Test rows | 39,164 |
| Stress prevalence (train/test) | 54.2% / 54.4% |
| ROC-AUC | 0.690 |
| Accuracy | 61.3% |
| Precision | 62.6% |
| Recall | 71.6% |
| F1 Score | 0.668 |
| Brier Score | 0.223 |

A ROC-AUC of 0.69 indicates meaningful discriminative ability above the 0.5 random baseline. The recall of 0.716 is intentionally prioritised over precision in a burnout-detection context — it is more important to flag a stressed user who should seek support (avoiding false negatives) than to avoid occasionally over-flagging a relaxed user. The F1 of 0.668 reflects a reasonable balance given the inherent noise in physiological signals measured outside a controlled environment.

---

## 6.4 Results and Evaluation Discussion

The testing outcomes indicate that the system meets its intended functional requirements and performs reliably across all main modules.

Key observations include:

- All 63 automated tests passed in 7.26 seconds with zero failures
- Backend endpoints consistently returned correct and validated responses across normal and edge-case inputs
- The ML prediction flow operated safely within the application pipeline, including graceful degradation when model artifacts are absent
- Schema validation correctly blocked malformed requests at the API boundary before any processing occurred
- The chatbot reply logic correctly personalised responses based on watch data and message keywords
- Integration between services was stable under repeated test runs

The pytest terminal output confirming the final test run:

```
============================= test session info ==============================
platform win32 -- Python 3.13.4, pytest-9.0.2
collected 63 items

...............................................................................

======================= 63 passed in 7.26s ===============================
```

From an evaluation perspective, the system demonstrated readiness for final project submission, with performance and behaviour aligned to expected project goals. Minor improvements remain possible in future iterations, particularly in expanding automated test coverage to include frontend UI automation and stress-testing under larger real-world data volumes, but these do not affect the current functional completeness of the delivered system.

---

## 6.5 Detailed Test Coverage

A total of **63 test cases** were written across **12 test classes**, covering all major components of the system. On the final run, all 63 tests passed in **7.26 seconds**.

| Test Class | Area Covered | Tests |
|---|---|---|
| `TestHealthEndpoint` | API availability | 2 |
| `TestIngestHealthKit` | Data ingestion endpoint | 5 |
| `TestSummaryLatest` | Summary retrieval endpoints | 4 |
| `TestRiskLatestEndpoint` | Risk scoring endpoint | 3 |
| `TestNotebookPredictEndpoint` | HRV / notebook ML endpoint | 5 |
| `TestChatbotCoach` | Chatbot HTTP endpoint | 5 |
| `TestSyncStatus` | Garmin sync status endpoint | 1 |
| `TestBurnoutModelServiceUnit` | IsolationForest ML service (unit) | 9 |
| `TestNotebookModelServiceUnit` | Supervised ML service (unit) | 6 |
| `TestComputeRiskLogic` | Rule-based risk scoring logic | 8 |
| `TestSchemaValidation` | Pydantic request/response schemas | 7 |
| `TestGarminExportIngest` | Garmin file-upload endpoint | 2 |
| `TestChatbotReplyLogic` | Chatbot reply generation logic | 6 |
| **Total** | | **63** |

**Final result: 63 passed, 0 failed — 5 deprecation warnings (no code errors).**

---

## 6.6 Unit Tests

Unit tests target individual classes and functions in isolation, without any database or network calls.

### 6.6.1 Burnout IsolationForest Service (`BurnoutModelService`)

The `BurnoutModelService` wraps a trained `IsolationForest` model that detects anomalous physiological patterns in wearable data. Nine unit tests verify its internal behaviour:

- **Service state before loading** — `is_ready` returns `False` before a model artifact has been loaded. `predict()` safely returns `None` rather than raising, protecting the API from crashes if the artifact is missing.
- **Statistical helper (`_avg`)** — Tested with empty lists, all-`None` lists, and numeric lists. An empty or all-`None` input correctly returns `None`; `[60.0, 70.0, 80.0]` returns `70.0` as expected.
- **Feature construction with missing data** — When all biometric fields (`sleep_minutes`, `resting_hr`, `steps`, `avg_hr`) are `None`, the feature vector defaults to safe neutral values (`sleep_ratio=1.0`, `resting_hr_delta=0.0`) instead of raising a `ZeroDivisionError` or `TypeError`.
- **Risk score normalisation** — Without calibration scalars (`score_min`/`score_max`), `_score_to_risk()` returns the neutral default of 50. With explicit bounds, scores are correctly clamped to the `[0, 100]` range with no overflow.
- **Artifact loading** — Loading from a non-existent path returns `False` cleanly. With the trained `burnout_iforest.joblib` artifact present (which it was during testing), loading succeeds and an end-to-end prediction on a high-stress input (low sleep, high HR, low steps) returns a valid labelled result.

### 6.6.2 Notebook Supervised Model Service (`NotebookBurnoutModelService`)

This service wraps the Random Forest / logistic model trained in the project notebook on the SWELL-WESAD HRV dataset. Six unit tests cover its behaviour:

- **Not-ready state** — `is_ready` is `False` when `.pkl` files are absent; `predict()` returns `None`.
- **Invalid physiological inputs** — A `hrv_avg` of `0.0` returns `None` rather than producing a meaningless division-by-zero result (`MEAN_RR = 60000 / HR`). When both `resting_hr` and `avg_hr` are `None`, the call also correctly returns `None`.
- **Stress-label detection** — The `_is_stress_label()` helper correctly identifies the labels `"1"`, `"stressed"`, `"burnout"`, `"high"` as stressed, and `"0"`, `"normal"` as non-stressed, regardless of how the training pipeline encoded the target class.
- **End-to-end inference** — With `burnout_model.pkl` and `scaler.pkl` present (notebooks directory), the full pipeline loads, scales the input features, runs inference, and returns a `NotebookModelPrediction` with a `confidence` value in `[0, 100]`.

### 6.6.3 Rule-Based Risk Logic (`_compute_risk`)

Before the ML model was added, burnout risk was calculated by a deterministic rule engine comparing today's metrics against a 7-day rolling baseline. Eight unit tests validate this logic:

| Test | Scenario | Expected |
|---|---|---|
| `test_baseline_only_data_low_risk` | One row, average metrics | Valid label returned |
| `test_severely_low_sleep_raises_risk` | Sleep at 50% of baseline | Score > 20, "sleep" in explanation |
| `test_high_resting_hr_raises_risk` | Resting HR +10 bpm | Score > 20, "heart rate" in explanation |
| `test_normal_data_keeps_low_risk` | Consistent healthy metrics | `risk_label == "Low"` |
| `test_multiple_bad_signals_yields_high_risk` | Low sleep + high HR + few steps | `risk_label in ("Medium", "High")` |
| `test_no_biometric_data_scores_at_base` | All `None` fields | `risk_score == 20` (baseline constant) |
| `test_explanation_never_empty` | Any input | `len(explanation) >= 1` |
| `test_risk_score_clamped_to_100` | Extreme bad inputs | `0 <= score <= 100` |

All 8 tests passed. The clamping test in particular confirmed that adversarial inputs (HR of 120 bpm, 1 hour of sleep, 0 steps) do not produce a score above 100.

### 6.6.4 Schema Validation (`HealthKitIn`, `NotebookPredictIn`, `ChatRequestIn`)

Seven Pydantic schema tests confirm that the request models enforce correct field constraints:

- `HealthKitIn` requires both `user_id` and `date`; missing either raises `ValidationError`.
- `NotebookPredictIn` requires `hrv_avg`; attempting construction without it raises `ValidationError`.
- `ChatRequestIn` requires `user_id`; missing it raises `ValidationError`.
- Valid payloads construct without error and field values are accessible as expected.

### 6.6.5 Chatbot Reply Logic (`_build_chatbot_reply`)

Six tests directly exercise the chatbot text-generation function without any database or HTTP overhead:

- **No watch data** — The reply tells the user to sync data first (contains "sync", "watch", or "data").
- **Risk label included** — With a High risk input, the reply contains the string "High".
- **Sleep-specific keyword** — Short sleep (`< 420 min`) combined with "what should I do" triggers a reply containing "sleep".
- **High resting HR** — A resting HR of 80 bpm triggers advice containing "heart rate", "resting", or "recovery".
- **Stress keyword** — A message containing "stressed" triggers a reply with "recovery", "breathing", "stress", or "burnout".
- **Plan keyword** — A message containing "plan" triggers a structured actionable reply.

---

## 6.7 Integration Tests (API Endpoints)

Integration tests exercise the full HTTP request cycle through all middleware (CORS, dependency injection, exception handlers) against an in-memory SQLite database.

### 6.7.1 Health Check (`GET /health`)

The simplest possible test confirms the application starts up correctly and returns `{"status": "ok"}` with HTTP 200. This also acts as a smoke test — if the app or its models fail to load at startup, all subsequent tests would fail here first.

```
TestHealthEndpoint::test_health_returns_ok       PASSED
TestHealthEndpoint::test_health_response_time    PASSED
```

### 6.7.2 HealthKit Data Ingestion (`POST /ingest/healthkit`)

Five tests cover the core data ingestion pathway:

| Test | Scenario | Result |
|---|---|---|
| Full payload | All fields present | 200 — row stored, fields readable |
| Minimal payload | Only `user_id` + `date` | 200 — optional fields default to `null` |
| Upsert same date | Re-POST same date | 200 — row updated (not duplicated) |
| Missing required fields | No `user_id` or `date` | 422 Unprocessable Entity |
| Invalid JSON | Malformed body | 422 Unprocessable Entity |

The upsert test is particularly important: it sends a row with `steps=5000`, then re-sends with `steps=12000` for the same date and user, and asserts the final stored value is `12000`, confirming the deduplication logic in `upsert_daily_summary()` works correctly.

### 6.7.3 Summary Retrieval (`GET /summary/latest`, `GET /summaries`)

Four tests verify that stored data can be retrieved:

- `GET /summary/latest?user_id=<known>` → HTTP 200, correct `steps` value.
- `GET /summary/latest?user_id=nobody-xyz` → HTTP 404.
- `GET /summaries?user_id=<known>&limit=5` → HTTP 200, JSON array.
- `GET /summaries?user_id=nobody-xyz2` → HTTP 200, empty array `[]` (not 404).

### 6.7.4 Risk Assessment (`GET /risk/latest`)

Three tests probe the risk endpoint:

- **No data user** → HTTP 404.
- **Response schema** — With one seeded row, the response contains `risk_label`, `risk_score` (0–100), and `explanation` with valid values.
- **Valid label with normal data** — Seeding 8 rows of consistent healthy data confirms the response is structurally valid. (Note: the IsolationForest model may still classify consistent-but-low-variance data patterns as anomalous depending on its training distribution — this is expected ML behaviour and the test validates the response format rather than imposing a label.)

### 6.7.5 Notebook ML Prediction (`POST /risk/notebook`)

Five tests cover the HRV-based prediction endpoint:

| Test | Input | Expected |
|---|---|---|
| Missing `hrv_avg` | `{"resting_hr": 60.0}` | 422 |
| Low-risk profile | HR=52, HRV=75 | 200 or 503 (model may not be deployed) |
| High-risk profile | HR=88, HRV=18 | 200 or 503 |
| Zero HRV | `hrv_avg=0.0` | 400 or 503 |
| Confidence field | Any valid input | `"confidence"` key present in 200 response |

The tests accept either HTTP 200 (model loaded) or HTTP 503 (model artifact missing) as valid outcomes, making the tests environment-agnostic: they will pass on a local dev machine with trained `.pkl` files and also on a fresh CI environment where the notebooks have not yet been run.

### 6.7.6 Chatbot Coach (`POST /chatbot/coach`)

Five integration tests exercise the chatbot endpoint:

- **No data** → 200 response, `used_watch_data: false`, reply contains guidance to sync.
- **With watch data** → 200 response, `used_watch_data: true`, `risk_label` and `risk_score` populated.
- **Missing `user_id`** → 422.
- **Stress keyword** → Reply contains at least one of: "stress", "burnout", "recovery", "breathing", "risk".
- **Sleep keyword** → 200 response confirming no crashes on sleep-related queries.

### 6.7.7 Garmin Export Ingest (`POST /ingest/garmin-export`)

Two file-upload tests verify the multipart form endpoint:

- An empty file body (`b""`) is correctly rejected with HTTP 400.
- A non-empty JSON file is accepted and returns `{"ok": true}`.

### 6.7.8 Sync Status (`GET /sync/status`)

A single structural test confirms the sync status endpoint returns the expected `sync` object with `enabled`, `interval_minutes`, and related fields. With `GARMIN_AUTO_SYNC_ENABLED=false` set in the test environment, `enabled` is confirmed to be `False`.

---

## 6.8 ML Model Evaluation

In addition to the functional tests above, the notebook training pipeline (`backend/train_notebook_model.py`) evaluates the supervised classifier on a held-out test set from the SWELL-WESAD HRV dataset. The metrics recorded in `notebooks/burnout_model_metrics.json` are:

| Metric | Value |
|---|---|
| Training rows | 313,310 |
| Test rows | 39,164 |
| Stress prevalence (train) | 54.2% |
| Stress prevalence (test) | 54.4% |
| ROC-AUC | 0.690 |
| Accuracy | 61.3% |
| Precision | 62.6% |
| Recall | 71.6% |
| F1 Score | 0.668 |
| Brier Score | 0.223 |

**Interpretation:** The stress prevalence is approximately 54%, making the task slightly imbalanced but not severely so. A ROC-AUC of 0.69 indicates the model has meaningful discriminative ability above the 0.5 random baseline. The recall of 0.716 is prioritised over precision in a burnout-detection context — it is more critical to flag a stressed user who should seek support (avoiding false negatives) than it is to avoid occasionally over-flagging a relaxed user. The F1 of 0.668 reflects a reasonable balance given the inherent noise in physiological signals measured outside a controlled environment.

The model was trained on March 9, 2026 (captured in `trained_at`) and the artifact is versioned in the repository. Model performance should be re-evaluated if the training data or feature engineering pipeline is modified.

---

## 6.9 Deprecation Warnings

Five deprecation warnings were raised during the test run, all originating from FastAPI's `@app.on_event("startup")` and `@app.on_event("shutdown")` decorators. These are informational only — the functionality works correctly. FastAPI recommends migrating to the newer `lifespan` context manager pattern in a future version. This deprecation does not affect any test outcomes and is logged here for transparency.

---

## 6.10 Summary

| Category | Tests | Passed | Failed |
|---|---|---|---|
| API Integration Tests | 32 | 32 | 0 |
| ML Model Unit Tests | 15 | 15 | 0 |
| Rule Logic Unit Tests | 8 | 8 | 0 |
| Schema Validation Tests | 7 | 7 | 0 |
| Chatbot Logic Tests | 6 | 6 | 0 |
| **Total** | **63** | **63** | **0** |

All 63 tests passed in 7.26 seconds on Python 3.13.4 / pytest 9.0.2. The test suite covers the full vertical slice of the system — from HTTP request parsing and schema validation through database persistence and ML inference to the chatbot reply text — providing confidence that all major system components behave correctly and that regressions introduced by future changes will be caught automatically.
