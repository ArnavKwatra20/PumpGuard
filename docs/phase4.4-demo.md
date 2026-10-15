# PumpGuard Phase 4.4 — Demo and reliability notes

This is a local, synthetic-data demo. The guide is designed for a 3–5 minute judging walkthrough. Keep both terminals open during the demo.

## Start and confirm services

Terminal 1 (PowerShell):

```powershell
cd D:\Hackathon\PumpGuard
.\.venv\Scripts\Activate.ps1
uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload
```

Terminal 2 (PowerShell):

```powershell
cd D:\Hackathon\PumpGuard\apps\web
npm ci
npm run dev
```

Confirm the API at [http://127.0.0.1:8001/health](http://127.0.0.1:8001/health); it should return `{"status":"ok","service":"pumpguard-api"}`. Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in a WebGL-capable browser.

## 3–5 minute walkthrough

1. Select **Normal operation**, then click **Generate simulation**. The initial sample window loads and live backend sampling begins automatically. Point out the advancing sample time, cards, and charts.
2. Select **Overheating** while live. Temperature rises progressively; wait for existing threshold rules to report a finding. Select the alert to show the actual temperature, expected range, explanation, and recommendations. Timing depends on the configured threshold and signal progression.
3. Select **Bearing wear** or **Rotor imbalance**. Point out the different vibration/sound behavior and the suspected bearing or shaft/impeller highlighting. Explain that localization is inferred from rule evidence, not confirmed damage.
4. Open an alert and acknowledge it. Show that acknowledgement records review and does not clear the condition. Select **Normal operation** and wait for a fresh normal assessment before showing resolution.
5. Briefly toggle the 3D scene's **Pause/Play** control and note that it affects animation only; live telemetry intentionally has no pause control and continues after Generate. For recovery, stop the backend with Ctrl+C, show the unavailable/stale status, then restart it and wait for a fresh sample. Alert state is not resolved while the API is unavailable.

The scenario selector changes the running backend session without a page reload. The generated initial batch is timestamped so its newest reading lands at request time; subsequent live timestamps advance. The browser validates scenario, pump identity, sensor values, assessment shape, sample age, and timestamp progression before accepting a live response. Timed-out, malformed, mismatched, or stale responses leave the last good assessment and alerts intact and mark telemetry unavailable. Successful polls retry every second. Event history is session-only and capped at 200 entries; the chart window is capped at 120 readings.

**Known scenario limitation:** Cavitation can produce a falling synthetic pressure and higher vibration/noise, but classification and component localization still depend on existing rule evidence. A quick seeded API check sometimes identified a vibration-only sample as `bearing_wear_pattern` near the RPM boundary; other samples reported `cavitation_pattern`. The UI correctly follows the returned assessment, so do not promise a cavitation-specific highlight on every sample. No threshold was changed to force that outcome.

## Troubleshooting

- **Backend startup failure:** activate the repository virtual environment and run `python -m pip install -e .` if the project is not installed there. Read the terminal traceback. Confirm `/health` responds before generating a simulation.
- **Frontend dependencies missing:** run `npm ci` from `D:\Hackathon\PumpGuard\apps\web` using the checked-in lockfile.
- **Port conflict:** the API is configured for port 8001 and Vite for 5173 (the frontend proxy in `apps/web/vite.config.ts` targets 8001 by default). Stop the process holding that port. If changing the API port, update the `/api` and `/health` proxy targets in `apps/web/vite.config.ts` as well.
- **API connection failure:** confirm the API terminal is running and `/health` responds. Before a simulation starts, correct the issue and click **Generate simulation** again. During live sampling, the UI marks the last sample stale/unavailable and retries; a successful fresh response restores the connected state.
- **WebGL unavailable:** the 3D panel displays a fallback; the sensor, assessment, alert, and chart panels remain usable. Try a current browser with hardware acceleration enabled. No GPU is required for API or rule assessment.
- **No alert appears for the selected scenario:** the scenario name itself does not create an alert; inspect the current backend assessment and threshold findings. The live sample now preserves the selected fault signature from its first reading. Sound may still require the one-time **Enable sound alerts** gesture if the browser blocks autoplay.

## What the demo proves

All telemetry, fault signatures, pressure values, and operating scenarios in the UI are synthetic. Rule-based assessments reflect configured thresholds. The 3D pump is procedural and illustrative. Component locations are suspected regions. Neither the scenario classifier nor the health score establishes real-world failure probability, physical damage, or predictive-maintenance accuracy. No readings or models have been validated against industrial equipment.

## AMD training readiness

The local experimentation code contains Logistic Regression and Random Forest baselines plus an optional compact PyTorch MLP. The API and rule engine do not require PyTorch. Phase 3A's CPU result (PyTorch 2.7.1+cpu on Windows 11) measured synthetic test macro F1 of 0.990 for Logistic Regression, 0.9085 for Random Forest, and 0.9768 for the MLP. These scores only describe that simulator split.

Phase 3B preserved a more cautionary result: under its synthetic unseen-pump baseline shift and drift, macro F1 fell to 0.082 for Logistic Regression and the MLP, while Random Forest scored 0.947 in that particular experiment. Weaker fault signatures also reduced performance for all three. These stress tests do not establish industrial reliability or select a production model. The reports remain in `docs/phase3a-results.md`, `docs/phase3b-audit.md`, `docs/phase3b-results.md`, and `data/reports/phase3b_robustness.json`.

The current device check (`python scripts/verify_gpu.py`) reported Windows 11, PyTorch 2.7.1+cpu, no available device, and `intended_amd_gpu_accessible: false`. AMD Developer Cloud access is unconfirmed. GPU/ROCm compatibility, cloud paths, supported hardware, and setup instructions therefore remain unverified. A verified AMD GPU could later accelerate larger controlled training experiments or inference workloads; it would not validate the synthetic labels or establish field performance. No cloud training or GPU benchmarking was performed.
