# PumpGuard — Phases 1–4.1

PumpGuard is an offline-ready industrial pump monitoring prototype. Phase 1 provides synthetic telemetry, explainable threshold alerts, structured assessments, a health score, and a FastAPI backend. Phase 2 adds a reproducible raw-to-feature pipeline, causal temporal features, pump-group splits, classification metrics, dataset quality reports, and small CPU baselines. Phase 3 adds optional CPU machine-learning experiments and synthetic distribution-shift evaluation. Phase 4.1 adds a browser-based, procedural centrifugal pump twin driven by the existing simulation API.

Phase 3A adds an optional, compact PyTorch training/evaluation path for local CPU use and a separate AMD GPU preflight/cloud entry point. It does not provision cloud resources or claim GPU execution on this laptop.

All generated observations are synthetic. Scenario classification identifies which controlled simulator pattern produced a sample; it is not failure prediction or proof of real-pump accuracy.

## Project layout
- `apps/api`: Uvicorn entry point.
- `apps/web`: responsive React/Vite digital twin and local API proxy.
- `src/pumpguard/models`: validated telemetry and assessment schemas.
- `src/pumpguard/simulator`: five synthetic operating scenarios.
- `src/pumpguard/detection`: configurable threshold records and deterministic rules.
- `src/pumpguard/services`: health assessment and bounded in-memory history.
- `src/pumpguard/api`: FastAPI routes and app factory.
- `src/pumpguard/data`: CSV validation, causal features, group splitting, metrics, and baseline helpers.
- `scripts`: raw data generation, feature preparation, report generation, and CPU experiments.
- `tests`: Phase 1 compatibility and Phase 2 pipeline tests.

## Windows setup

PowerShell:
```powershell
cd D:\Hackathon\PumpGuard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,ml]"
```

The `ml` extra is optional for the API. It adds scikit-learn for logistic-regression and Random Forest experiments. The `torch` extra is separately optional and adds PyTorch for the MLP experiment. Runtime API dependencies remain FastAPI, Uvicorn, Pydantic, and NumPy. No LLM, API key, external service, or GPU is needed for the service or CPU experiments.

For the Phase 3A laptop workflow, install the API and sklearn extras, then select the official CPU-only PyTorch wheel index (the tested Windows/Python 3.12 wheel was 2.7.1):
```powershell
python -m pip install -e ".[dev,ml]"
python -m pip install "torch>=2.7,<2.8" --index-url https://download.pytorch.org/whl/cpu
```
Do not install ROCm on this Windows laptop; the integrated AMD graphics are not assumed to be a supported training device. The `torch` optional extra records the tested-compatible version range for dependency metadata.

Start the API with `uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload`. Swagger UI: http://127.0.0.1:8001/docs. Liveness: http://127.0.0.1:8001/health.

## Phase 1 API and sensors

A fresh API process has no pumps. Initialize one by posting to `/api/v1/simulation/generate`:
```powershell
$body = '{"pump_id":"pump-01","scenario":"normal","sample_count":10,"sampling_interval_seconds":1,"random_seed":42}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8001/api/v1/simulation/generate -ContentType application/json -Body $body
```

Other routes: `GET /api/v1/pumps`, `GET /api/v1/pumps/{pump_id}/telemetry/latest`, `GET /api/v1/pumps/{pump_id}/telemetry/history?limit=20`, and `GET /api/v1/pumps/{pump_id}/assessment`.

Sensor columns and units: temperature °C, vibration mm/s, sound dB, and rotational speed rpm. Illustrative expected ranges are temperature 20–85, vibration 0–4.5, sound 45–85, and RPM 1650–1900. A threshold breach is warning unless it passes the configured critical outer bound. Health score starts at 100, subtracts 15 per warning and 35 per critical finding, and floors at zero. This is an explainable status score, not a failure probability or remaining-life estimate.

Supported synthetic scenarios: `normal`, `overheating`, `bearing_wear`, `cavitation`, and `imbalance`. The patterns are illustrative assumptions, not universal diagnostic rules.

## Phase 2 raw-to-feature workflow

Raw telemetry and processed features are kept separate. The raw CSV preserves the Phase 1 columns: `timestamp,pump_id,temperature_c,vibration_mm_s,sound_db,rpm,operating_mode,scenario_label`. `scenario_label` is simulator ground truth and is never included in the model feature allowlist.

Generate a small, reproducible dataset (100 samples per scenario across five pump histories by default):
```powershell
python scripts/generate_dataset.py --samples-per-scenario 100 --pump-count 5 --seed 42 --start-time 2026-01-01T00:00:00+00:00 --output data/raw/pump_telemetry.csv
```
The fixed default start time and explicit per-pump/per-scenario seeds make repeated runs byte-identical. Each pump receives all five scenario segments, and pump histories occupy separate chronological blocks so group holdouts have a clear time order. At least three pumps are required for train/validation/test grouping.

Validate the raw CSV, engineer features, and save a separate processed CSV:
```powershell
python scripts/prepare_dataset.py --input data/raw/pump_telemetry.csv --output data/processed/pump_features.csv --windows 3,5 --lags 1
```
Validation rejects missing required columns, missing or nonnumeric sensor values, nonfinite values, invalid Pydantic ranges or scenario labels, unordered per-pump timestamps, and duplicate `(pump_id,timestamp)` records.

## Feature definitions

For each sensor, the engineered CSV keeps the raw sensor column and adds:
- `{sensor}_delta`: current minus previous reading, in the sensor's original unit.
- `{sensor}_relative_change`: delta divided by the absolute previous value; dimensionless. It is blank when no previous value exists or the previous value is zero.
- `{sensor}_lag_N`: the value N rows earlier for that same pump.
- `{sensor}_roll_mean_wN` and `{sensor}_roll_std_wN`: trailing window statistics including the current row; standard deviation uses population convention (ddof=0), in the sensor's original unit.

Default windows are 3 and 5 rows; default lag is 1. Rows are sorted by pump and timestamp before calculation. Windows never cross pump boundaries and use only current/past observations. Early rows have blank derived values until enough history exists; `feature_warmup` flags rows before the largest configured window or lag is ready. The ground-truth label, pump ID, timestamp, operating mode, and warm-up flag are not model inputs.

## Splits, targets, and leakage controls

`scenario_label` supports **controlled scenario classification** only. Rule-based anomaly detection is a separate baseline task. **Predictive maintenance** requires a future event label and a defined prediction horizon; Phase 2 has neither, so it does not claim failure prediction.

`split_dataset` assigns complete pump groups to train, validation, and test in order of each history's start time, then sorts samples chronologically within each split. Related rolling windows from a pump remain together. The split metadata records groups, seed, sample counts, and time ranges. At least three groups are required. The CPU experiment fits its imputer and scaler only on training data, selects a model using validation balanced accuracy, then evaluates the selected model on test once.

The current synthetic generator assigns scenario blocks to every pump, so each group contains all five classes. Other datasets may not; inspect the report and per-class metrics before drawing conclusions.

## Quality reports and CPU baselines

Create JSON and Markdown audits:
```powershell
python scripts/dataset_report.py --input data/raw/pump_telemetry.csv --json-output data/reports/quality_report.json --markdown-output data/reports/quality_report.md --seed 42
```
The report labels its data synthetic and includes sample/pump counts, timestamp range, label distribution, missing values, duplicates, sensor ranges and means, class imbalance, split counts, and warnings.

Run optional CPU scenario-classification experiments:
```powershell
python scripts/run_baselines.py --input data/raw/pump_telemetry.csv --output data/reports/baseline_results.json --seed 42
```
When scikit-learn native components load, the script compares Logistic Regression and Random Forest, uses validation balanced accuracy for selection, and reports fit/inference timing, classification metrics, per-class results, confusion matrix, and multiclass ROC-AUC when valid. If native components are unavailable, it runs a small pure-Python nearest-centroid fallback with train-only median imputation and standardization. This fallback does not replace the optional scikit-learn comparison.

## Tests and limitations

Run Phase 1 and Phase 2 tests with `python -m pytest`. All synthetic results are conditional on the simulator's hand-authored patterns and are not evidence of industrial accuracy. Threshold rules flag configured symptoms; they do not predict failure before symptoms. In-memory API history disappears on restart.

## Phase 3A compact PyTorch experiment

Generate a larger, deterministic synthetic experiment (300 samples per scenario across ten pump identities, 1,500 rows total) with varied random seed, sensor noise, and pump-specific operating offsets:
```powershell
python scripts/generate_dataset.py --samples-per-scenario 300 --pump-count 10 --seed 2026 --noise-scale 1.5 --operating-variation 1.0 --output data/raw/pump_telemetry_phase3a.csv
```
Change these arguments for larger or repeated experiments. The new generator arguments default to the Phase 2 behavior. The extra variation is illustrative synthetic variation only; it does not represent measured industrial conditions.

Train the small five-class MLP on CPU, save its artifact, and evaluate it:
```powershell
python scripts/train_torch.py --input data/raw/pump_telemetry_phase3a.csv --artifact models/pumpguard_mlp.pt --output data/reports/torch_results.json --seed 2026 --epochs 40 --batch-size 64 --learning-rate 0.001 --patience 6
```
The pipeline reuses causal feature engineering, the numeric feature allowlist, whole-pump chronological splits, and the training-only median imputer/standardizer. It selects checkpoints using validation balanced accuracy (validation loss breaks ties), applies early stopping, then reports test metrics once. The serialized artifact contains weights, ordered feature names, preprocessing statistics, class mapping, model/training configuration, and split metadata. `SavedClassifier` provides ordered-row `predict` and `predict_proba` methods.

Compare against the existing Logistic Regression and Random Forest pipeline on the same seed, pump groups, split metadata, and ordered features:
```powershell
python scripts/compare_models.py --input data/raw/pump_telemetry_phase3a.csv --artifact models/pumpguard_mlp.pt --output data/reports/model_comparison.json --seed 2026 --epochs 40
```
Reports include accuracy, balanced accuracy, macro F1, confusion matrix, per-class scores, training/inference wall time, and MLP parameter count. The neural model is not assumed to outperform the simpler baselines. Small synthetic results are useful for software checks, not evidence of real-pump performance.

PyTorch remains optional: importing the FastAPI service and Phase 1/2 data utilities does not import it. The standard test suite skips only the PyTorch-dependent model tests when that extra is absent; tests for metrics and missing-GPU behavior remain CPU-only.

### Future AMD Developer Cloud workflow

`python scripts/verify_gpu.py` reports the installed PyTorch build, operating system, visible device properties, and whether a ROCm AMD device is actually exposed. This is a diagnostic only. In a future compatible AMD cloud environment, stage the synthetic or properly governed real dataset there and run `python scripts/train_cloud.py --input <cloud-data-file> --artifact <cloud-output-file>`. That entry point requires a PyTorch HIP/ROCm build and an identifiable AMD GPU, and exits with an error if either is unavailable; it will never relabel CPU execution as GPU training. Cloud paths, supported GPU types, ROCm versions, and installation instructions must be obtained from the chosen cloud environment when credits/access are available. No cloud resources were provisioned and no GPU benchmark was run in Phase 3A.

## Phase 3B synthetic robustness workflow

The Phase 3B audit and limitations are recorded in `docs/phase3b-audit.md`. The new simulator condition object controls measurement noise, baseline temperature/vibration/sound, operating RPM, fault intensity, and within-sequence sensor drift. `scripts/generate_dataset.py` exposes these values as CLI options and validates generated telemetry through the existing schema. `pumpguard.simulator.robustness.generate_condition_rows` randomizes scenario order independently per pump to remove the legacy fixed-order shortcut. Channel dropout is injected into engineered feature families for evaluation; raw CSV ingestion still rejects missing/invalid sensor readings.

Run the reproducible CPU robustness comparison:
```powershell
python scripts/run_robustness.py --seed 2027 --samples-per-scenario 400 --epochs 30 --bootstrap-repetitions 1000 --output-json data/reports/phase3b_robustness.json --output-markdown docs/phase3b-results.md --artifact models/phase3b_mlp.pt
```
This trains on 12 pump groups, uses four groups for MLP checkpoint and uncertainty-threshold selection, and reserves four complete groups for the standard holdout. It compares that holdout with unseen synthetic pump configurations and drift, higher sensor noise, weaker fault signatures, and 5% channel dropout. LR/RF settings are fixed; all three classifiers use the same labels, feature ordering, train/validation groups, and compatible held-out conditions. Reported intervals bootstrap pumps as clusters, not individual rows.

The seed-2027 experiment is documented in `docs/phase3b-results.md`, with full per-class metrics, confusion matrices, model sizes, confidence diagnostics, thresholds, examples, and bootstrap details in `data/reports/phase3b_robustness.json`. On this simulator run, in-distribution macro F1 was 0.990 for LR, 0.990 for RF, and 0.983 for the MLP. Under the shifted baseline plus drift, LR and the MLP fell to 0.082 macro F1 while RF scored 0.947. Weaker fault signatures were difficult for all three (macro F1 0.733, 0.707, and 0.810 respectively). These are synthetic stress tests, not industrial validation. Validation-selected confidence rejection did not reliably catch the high-confidence errors caused by the baseline shift, so it remains an experiment-only reject option and does not change API or health-engine behavior.

Rule-based anomaly detection and the health score remain separate from scenario classification. A predicted scenario is not a failure forecast, and classifier scores are not calibrated probabilities of equipment failure.

## Phase 4.1 interactive centrifugal pump twin

Phase 4.1 adds the first browser UI in `apps/web`. It is a local React, TypeScript, Vite, and Three.js client for the existing FastAPI simulation API. The development server proxies `/api` and `/health` to `127.0.0.1:8001`; the API request/response schemas and health engine are unchanged. The twin starts in an empty state and displays only values returned by a simulation request. Current trend charts seed from that validated scenario response and append fresh live samples; the unlabeled historical telemetry endpoint is not used to seed scenario graphs.

In two PowerShell terminals, start the existing API and then the web client:
```powershell
cd D:\Hackathon\PumpGuard
.\.venv\Scripts\Activate.ps1
uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload
```
```powershell
cd D:\Hackathon\PumpGuard\apps\web
npm ci
npm run dev
```
Open the local URL printed by Vite (normally http://127.0.0.1:5173). The UI supports the existing five simulator scenarios and API-backed pump ID, sample count, interval, and random seed controls. A fixed seed with the same inputs reproduces the same synthetic sensor sequence. Reset submits a new `normal` simulation; pause affects only the visual animation. Simulation requests are disabled while a request is in progress. API validation errors are shown without substituting local or fabricated readings.

The pump is procedural geometry, not a CAD-derived or dimensionally accurate asset. Orbit and zoom use pointer controls. The shaft's visual angular velocity uses the standard conversion `ω = RPM × 2π / 60`; RPM deviation is relative to the documented illustrative 1,780 RPM reference. Temperature deviation uses 68 °C as an illustrative display reference, and the vibration percentage scales the display to an illustrative 8 mm/s range. These values are visualization aids and do not change the health engine's configured thresholds. Scenario-specific coloration and cavitation bubbles use the scenario label returned by the API; vibration motion and shaft speed use returned telemetry. WebGL initialization failure shows a fallback while leaving simulation and telemetry panels usable. The canvas respects reduced-motion preferences and has an animation pause control.

Run frontend tests and a production build with:
```powershell
cd D:\Hackathon\PumpGuard\apps\web
npm test
npm run build
```
`VITE_API_BASE_URL` can specify an API base URL for a deployment configured to serve the frontend and API separately; local development uses the Vite proxy. `npm ci` uses the checked-in lockfile. The browser bundle contains no AMD credential or direct provider client; optional LLM requests pass through FastAPI. All displayed pump data is synthetic and this UI is not evidence of industrial validation or a real pump's failure risk.

The current production build emits a 266.97 kB main JavaScript bundle (82.23 kB gzip) and a lazily loaded 567.97 kB Three.js scene bundle (142.14 kB gzip). Vite reports its standard 500 kB minified-chunk advisory for the scene bundle; the measured gzip size is reported here so the tradeoff is explicit.

## Phase 4.2 alerts and fault localization

The web client now turns warning and critical anomalies from each successful backend simulation assessment into in-session alert episodes. Repeated observations of the same pump, metric, and expected range update the existing event; severity and observed value can change without changing its episode identity or acknowledgement state. A later fresh assessment with that condition absent resolves it. API failures leave alert state unchanged and show that telemetry is unavailable, rather than resolving a condition. Acknowledgement records operator review only. The visible event history lasts for the current browser session and is capped at 200 events; it is not persisted across restarts.

Component locations are suspected regions inferred from the rule engine's metric and supported fault indicators: temperature points to the motor, shaft speed to the shaft/drive, and specific bearing, cavitation, overheating, or imbalance indicators map to corresponding regions. Ambiguous readings use a generic pump location. Three.js parts have stable component IDs; active warning/critical conditions use amber/red outlines. Selecting an event keeps its component highlighted and opens backend evidence, expected range, explanation, and current recommendations. These locations are not proof of physical damage. Sound alerts are enabled by default and are requested once for each newly identified warning or critical episode; the visual alert is independent of sound mute state. Browsers may require the one-time Enable sound alerts gesture, which is surfaced if autoplay is blocked. All alerts are based on the existing health assessment; the rule thresholds, health score, API schemas, and scenario classification were not changed.

## Phase 4.3 continuous live telemetry

The original dashboard generated one batch from `POST /api/v1/simulation/generate`, displayed its latest row, and fetched history once. Nothing requested a new sample afterward, so sensor cards and trend charts stayed static. The existing simulator also applied fixed fault offsets independently per row and had no evolving live state.

Click **Generate simulation** to create the initial dataset and automatically begin one backend sample per second. While live, **Pause simulation** pauses dashboard polling and **Stop live simulation** ends the live session; the separate 3D animation control affects only visual motion. Selecting a different scenario while live clears the old chart window and immediately requests a sample for the new mode. Every returned sample carries a fresh rule assessment and enters a newest-first chart window capped at 120 readings. API failures are shown as unavailable/stale; polling retries automatically and alert episodes are changed only by successful fresh assessments.

The existing batch simulation API and health thresholds are unchanged. The added `POST /api/v1/simulation/live-sample` returns the existing simulation response shape with one new sample. Its process-local generator starts from the established baseline generator and adds reproducible bounded variation, scenario trends, and a pressure signal. Live fault intensity starts at the selected scenario's established level so the first poll stays consistent with the batch shown by Generate; sensor noise and scenario progression continue to vary over time. New optional `pressure_kpa` telemetry defaults to 320 kPa for compatibility with earlier clients/readings. The request also accepts optional `client_session_id`; the web dashboard sends a per-page ID so separate dashboards using the same pump ID cannot reset one another's scenario sequence. Older clients that omit it retain a shared legacy session. Live generator state is process-local and bounded to 256 pump/client sessions; existing per-pump telemetry history remains bounded by the configured service limit. Restarting the backend resets live sequence state and in-memory telemetry. These signals are illustrative synthetic behavior, not calibrated pump physics or field validation.

## Phase 4.9 scenario graphs and automatic fault alarm

The dashboard validates and plots all five supported API scenario identifiers from returned telemetry. The graph window starts from the selected scenario's validated batch response rather than the telemetry-history endpoint, because that endpoint has no scenario label and may contain readings from earlier scenarios. Changing scenarios clears the old graph window; cancelled requests and response validation prevent stale samples from replacing the active scenario. Live polling appends each fresh backend reading to the bounded graph window. The live generator's first fault sample retains the selected scenario signature after the batch. The runtime audit found two local Vite dashboards using the same pump ID for different scenarios; the backend's single session-per-pump key let those requests reset each other's sequence and repeat the first samples. Each current dashboard now sends an optional client session ID, isolating its live sequence from other tabs/apps using that pump ID. Older clients that omit the ID use a shared legacy session for backward compatibility.

An active warning or critical alert episode starts one repeating, alternating 740/520 Hz Web Audio pattern with short tone bursts and quiet gaps. The loop is idempotent across polling and React rerenders. **ACKNOWLEDGE ALARM — SILENCE SIREN** acknowledges only its episode; it silences the loop when no other active unacknowledged episode remains. Acknowledgement does not resolve the condition: the alert and component highlight remain until a fresh backend assessment no longer reports it. Severity changes update the same episode, so routine warning/critical fluctuations cannot create a fresh siren or restore its acknowledgement action. A later distinct episode can sound again. If autoplay is blocked, the UI reports that state and the one-time **Enable sound alerts** control unlocks playback, including a still-active alarm. Muting stops the sound while leaving visual alerts active. Acknowledgement and event history are held in frontend memory for the current page session only; they are not persisted across reloads or shared between operators. Audio behavior was verified through automated Web Audio mocks; actual audible speaker output was not confirmed in this run and depends on browser/device audio settings. All findings remain synthetic rule-engine alerts, not claims of physical damage.

Verification: the frontend suite has 91 passing tests across 12 files, the backend suite has 163 passing tests with one existing Starlette/httpx deprecation warning, and `npm run build` succeeds (with the documented Three.js chunk-size advisory). The running browser verified live telemetry, an overheating assessment, alert history, pause/stop controls, and AMD catalog inspection; no test or browser check constitutes validation on real industrial equipment.

Launch as in Phase 4.1: run `uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload` from `D:\Hackathon\PumpGuard` with `.venv` activated, then run `npm run dev` from `D:\Hackathon\PumpGuard\apps\web` and open `http://127.0.0.1:5173`. Choose a scenario and click **Generate simulation**. Observe the sensor readings, discharge pressure, latest-sample time, charts, rule assessment, and alert history updating continuously.

## Phase 4.4 demo readiness and reliability

See [`docs/phase4.4-demo.md`](docs/phase4.4-demo.md) for exact startup and health checks, a 3–5 minute judge walkthrough, recovery and troubleshooting steps, and the verified AMD/ML readiness state. The browser validates live response shape and freshness, timed API requests fail clearly, and continuous session alert history is bounded to 200 events. The initial batch ends at request time so live timestamps do not move backward. The live simulation has dashboard pause/resume/stop controls; the separate Three.js pause control affects animation only.

## Phase 4.5–4.7 monitoring interface

The Mission Control redesign supersedes the Phase 4.7 warm-paper palette. The current interface uses dark graphite surfaces, neutral operational typography, restrained safety orange, and distinct stable trend colors around the existing interactive pump, API-backed instrument trends, simulation controls, alert lifecycle, and Phase 4.6 evidence explorer. Operating Parameters remains in the former Evidence & Fault Relationship dashboard slot; that evidence explorer remains available in the Diagnostic Inspector after the alert log. No API contract, health threshold, telemetry source, or pump behavior changed. The implementation and verification are documented in [`docs/phase4.8-mission-control.md`](docs/phase4.8-mission-control.md). All displayed readings remain synthetic, not industrial validation.

## AMD Token Factory explanations

The optional AMD integration uses the backend-only `.env` file at the project root. `RADEON_API_KEY` is never exposed to Vite or returned by an API route. Set `PUMPGUARD_DIAGNOSTIC_PROVIDER=amd` to select it; the package default remains the offline mock. `GET /api/v1/diagnostics/status` reports local configuration, while the operator-triggered `GET /api/v1/diagnostics/models` fetches the model catalog and exposes IDs plus capability metadata that AMD actually returns. The catalog is cached in process memory for three minutes. An explanation request verifies the configured model appears in that catalog before calling chat completions. AMD explanations accept only requests marked synthetic, and omit pump/session identifiers and simulator scenario labels. Rule assessments, alerts, thresholds, simulation, and ML behavior remain authoritative and unchanged.

Local development uses the Vite proxy target `127.0.0.1:8001`; Vite itself has no fixed port configured and defaults to `5173` (pass `--port 5176` if that local port is desired). Start the backend with `uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload` from the project root. No authenticated AMD request is made until the operator clicks **Inspect AMD models** or **Request diagnostic explanation**.

## Hackathon deployment

PumpGuard is a synthetic monitoring prototype for a temporary demonstration. It must not be connected to industrial control equipment or presented as a validated diagnostic system. The default deployment shape is a static frontend host plus one Python-compatible backend service. No hosting provider is hard-coded in this repository. A concrete example wiring this shape to Vercel with two projects from this repository is documented at the end of this section.

Build the frontend with the backend's public URL at build time:

```powershell
cd apps\web
$env:VITE_API_BASE_URL="https://your-api.example.com"
npm ci
npm run build
```

Publish `apps/web/dist` on the static frontend host. Configure the backend service to install the Python project and run a production server (no `--reload`):

```text
uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT
```

Set `PORT` using the hosting provider's assigned port. The backend requires no AMD credential when `PUMPGUARD_DIAGNOSTIC_PROVIDER=mock`; AMD diagnostics are optional. For AMD, set `PUMPGUARD_DIAGNOSTIC_PROVIDER=amd`, `RADEON_API_KEY`, `RADEON_BASE_URL`, and `RADEON_MODEL` as backend secret/environment settings. Never put `RADEON_API_KEY` in frontend or `VITE_*` variables, commit `.env`, or package the local virtual environment.

Set `PUMPGUARD_CORS_ORIGINS` to the exact frontend origin, comma-separated, for example `https://demo.example`. Local defaults allow `http://localhost:5173` and `http://127.0.0.1:5173`; production should use an explicit deployed origin. CORS is not a replacement for access control.

The backend includes lightweight process-local limits for the temporary single-process demo. Defaults are 10 diagnostic/AMD requests, 120 simulation requests, 60 telemetry-analysis requests, and 30 ML-status requests per client address per 60 seconds. Adjust `PUMPGUARD_RATE_LIMIT_WINDOW_SECONDS`, `PUMPGUARD_RATE_LIMIT_DIAGNOSTICS`, `PUMPGUARD_RATE_LIMIT_SIMULATION`, `PUMPGUARD_RATE_LIMIT_ANALYSIS`, and `PUMPGUARD_RATE_LIMIT_ML` in the backend environment. A `429` response includes `Retry-After`. These limits are not shared across workers or instances, so use hosting-provider access restriction or rate limiting if the preview is public.

Smoke test the deployed API before opening the frontend:

```powershell
Invoke-RestMethod "https://your-api.example.com/health"
$body = '{"pump_id":"pump-01","scenario":"normal","sample_count":3,"random_seed":42}'
Invoke-RestMethod -Method Post -Uri "https://your-api.example.com/api/v1/simulation/generate" -ContentType "application/json" -Body $body
```

Expected behavior is HTTP 200 for `/health` and simulation generation, successful browser requests from the configured origin, HTTP 429 after the configured limit, and a clear provider-unavailable response when AMD is not configured. State, telemetry history, sessions, and in-memory rate-limit counters reset when the backend restarts.

The active model/evidence design and GPU verification steps are documented in [`docs/amd-compute-and-predictive-maintenance.md`](docs/amd-compute-and-predictive-maintenance.md). The official [Radeon Cloud model catalog API](https://amd-aim.github.io/radeon-cloud-docs/api/models/) describes available metadata, and the [chat-completions API](https://amd-aim.github.io/radeon-cloud-docs/api/chat-completions/) documents the request and response contract. In the latest local audit, the catalog and a minimal OpenAI-compatible chat envelope were live-verified; a complete PumpGuard diagnostic result was not verified, so AMD explanations remain an optional, failure-isolated integration.

The Diagnosis page also exposes optional maintenance-planner, telemetry-explanation, and scenario-analyst actions through `POST /api/v1/diagnostics/ai-feature`. These actions reuse server-owned deterministic telemetry context and the rule assessment, label all records as synthetic, and keep the rule engine authoritative. They are bounded draft explanations only; provider failure remains explicit and does not affect simulation or rule-based health.

## Vercel deployment (two projects, one repository)

Live production deployments (Hobby plan; both projects are connected to this repository through the Vercel Git integration, so pushes to `master` redeploy the affected project):

- API: https://pumpguard-steel.vercel.app (project `pumpguard`; the shorter `pumpguard.vercel.app` alias was already taken globally, so Vercel auto-aliased)
- Web: https://pumpguard-web.vercel.app (project `pumpguard-web`)

Both projects were created non-interactively with the Vercel CLI (`vercel link --yes --project …`, `vercel env add …`, `vercel deploy --prod`); the dashboard steps below are the equivalent manual flow.

This repository deploys to Vercel as a Vite frontend and a FastAPI backend. The backend project is `pumpguard` (`https://pumpguard-steel.vercel.app`); the separate `pumpguard-api` project is a failed duplicate and is not used by the frontend. The backend entry point is the root `app.py`, an ASGI module that exports `app` from the FastAPI factory after adding `src/` to `sys.path`. Vercel's FastAPI framework detection supports this entry point. The root `vercel.json` deliberately has no `functions` glob: those patterns match functions under `/api`, and pointing one at root `app.py` caused the `unused_function` build failure. Local development is unchanged (`uvicorn apps.api.main:app`).

1. Push this repository to GitHub, for example:

   ```text
   git remote add origin https://github.com/<you>/PumpGuard.git
   git push -u origin master
   ```

2. In the Vercel dashboard choose **Add New → Project** and import the same repository twice:
   - **API project** — leave Root Directory at the repository root. Vercel deploys the root `app.py` as a single Python function; no build command or output directory is needed. Deploy it first and note its URL (for example `https://pumpguard-steel.vercel.app`).
   - **Web project** — set Root Directory to `apps/web`. Vercel detects Vite, runs the lockfile install and `npm run build`, and publishes `apps/web/dist`.
3. Configure environment variables under **Settings → Environment Variables**, then redeploy:
   - **API project:** `PUMPGUARD_CORS_ORIGINS` set to the exact web origin (comma-separated for more than one, no trailing slash, for example `https://pumpguard.vercel.app`). `PUMPGUARD_DIAGNOSTIC_PROVIDER=mock` is the bounded demo default and can be set explicitly. AMD stays optional: `PUMPGUARD_DIAGNOSTIC_PROVIDER=amd` plus encrypted `RADEON_API_KEY`, `RADEON_BASE_URL`, and `RADEON_MODEL` values.
   - **Web project:** `VITE_API_BASE_URL` set to the API project's URL with no trailing slash. This is a build-time value, so set it before the first successful deploy or redeploy afterwards.
4. Under **Settings → Git**, connect both projects to the repository so every push redeploys both and the frontend always embeds the current API URL.

Smoke test in order: `GET https://<api-host>/health` returns HTTP 200, `POST https://<api-host>/api/v1/simulation/generate` with the documented body returns HTTP 200, then `GET https://<web-host>` returns the UI and telemetry updates after **Generate simulation**.

Vercel-specific behavior, stated explicitly:

- The API runs as one serverless function per warm instance. Pump registry, telemetry history, live-simulation state, and rate-limit counters are process-local, so after an idle cold start they reset; press **Generate simulation** again if the UI reports an unknown pump. The documented process-local rate limits apply per instance and are keyed by the platform's shared proxy address rather than per end user, so raise `PUMPGUARD_RATE_LIMIT_*` on the API project if concurrent testers hit 429 earlier than expected. These limits are still not a distributed rate limiter.
- The production diagnostic provider currently reports `mock_test_mode`; no AMD-generated response is being served. The production backend has no `RADEON_API_KEY` environment variable configured. Configure AMD credentials only on the backend project, then verify an end-to-end diagnostic request before describing responses as AMD-generated. The Vercel project timeout is not set by `vercel.json`; keep the backend diagnostic timeout below the project's configured function limit if AMD is enabled.
- Web preview deployments receive their own origin (for example `https://pumpguard-web-git-<branch>.vercel.app`); add that origin to `PUMPGUARD_CORS_ORIGINS` before testing previews, or validate on the production deployment only. CORS is still not access control.
- The API bundle excludes local-only `apps/`, `tests/`, `docs/`, and `scripts/` paths through the root `.vercelignore`; the web project has its own ignore file under `apps/web`. The API request path performs no disk writes, which fits the read-only serverless filesystem; state lives in process memory only, as documented.
- Browser API calls time out after 8 seconds except diagnostic explanations, which allow tens of seconds; cold-start imports stay well inside that window.
