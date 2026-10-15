# PumpGuard ACTIII — Antigravity Validation Results

_Run date: 2026-10-13 · Local time: IST (UTC+05:30)_

---

## 1. Repository State

| Item | Finding |
|---|---|
| **Git metadata** | `D:\Hackathon\PumpGuard` is **not a Git repository**; `.git` is absent. Uncommitted-change detection is unavailable. |
| **Phase reports present** | `phase0-results.md`, `phase1-results.md`, `phase2-results.md`, `phase2-ai-infrastructure.md`, `phase3a-results.md`, `phase3b-audit.md`, `phase3b-results.md`, `phase4-ml-evaluation.md`, `phase4.4-demo.md`, `phase4.5-ui.md`, `phase4.7-ui.md`, `phase4.8-mission-control.md`, `simulation-dashboard-ui-results.md` |
| **Backend entry point** | `apps/api/main.py` → `uvicorn apps.api.main:app` |
| **Frontend entry point** | `apps/web/package.json` scripts: `dev`, `build`, `preview`, `test` |

---

## 2. Running Process Inventory (as of this session)

| Port | PID | Health check | API compatibility |
|---|---|---|---|
| **8000** | 23896 (python) | HTTP 200 `{"status":"ok","service":"pumpguard-api"}` | **INCOMPATIBLE** — rejects Phase 1 `live-sample` fields (`speed`, `load_percent`, etc.) with HTTP 422 `extra_forbidden`. This is an older process predating Phase 1. |
| **8001** | 8412 (python) | HTTP 200 `{"status":"ok","service":"pumpguard-api"}` | **COMPATIBLE** — accepts Phase 1 `live-sample` fields and returns HTTP 200 with full telemetry. |
| **8003** | 28468 (python) | (not verified in this session) | Not used by UI. |

> [!IMPORTANT]
> The backend on port **8000** is a confirmed old/incompatible process. It was not started by this session and was not terminated to avoid disrupting unrelated work.

---

## 3. Confirmed Demo Blocker and Fix

### Blocker: Vite proxy default targeted the incompatible backend

`apps/web/vite.config.ts` previously defaulted the API proxy to `http://127.0.0.1:8000`. The process on port 8000 predates Phase 1 and rejects the `speed`, `load_percent`, `cooling_effectiveness`, `inlet_restriction_percent`, `rpm_setpoint`, `fault_severity`, and `fault_enabled` fields added to `LiveSampleRequest` in Phase 1, returning HTTP 422. This silently breaks all simulator controls in the UI.

**Evidence (actual HTTP exchange):**

```
POST http://127.0.0.1:8000/api/v1/simulation/live-sample
Body: {"pump_id":"pump-01","scenario":"overheating","speed":1.5,"load_percent":85}
→ HTTP 422 {"detail":[{"type":"extra_forbidden","loc":["body","speed"],...}]}

POST http://127.0.0.1:8001/api/v1/simulation/live-sample
Body: {"pump_id":"pump-01","scenario":"overheating","speed":1.5,"load_percent":85}
→ HTTP 200 (full telemetry returned)
```

**Fix applied** — `apps/web/vite.config.ts` line 4:

```diff
-const apiProxyTarget = process.env.PUMPGUARD_API_PROXY_TARGET ?? 'http://127.0.0.1:8000';
+// Port 8001 is the compatible Phase 1+ backend (adds simulator controls to live-sample).
+// The older process on 8000 rejects those fields. Override with PUMPGUARD_API_PROXY_TARGET if needed.
+const apiProxyTarget = process.env.PUMPGUARD_API_PROXY_TARGET ?? 'http://127.0.0.1:8001';
```

The `PUMPGUARD_API_PROXY_TARGET` environment-variable override is preserved. No API contract, health threshold, or other file was changed.

---

## 4. Test and Build Results (Actual Commands — This Session)

### Backend regression tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

| Result | Exit code |
|---|---|
| **81 passed**, 1 warning (Starlette/httpx deprecation) | **0** |

### Frontend regression tests (before fix)

```powershell
cd apps\web; npm test -- --run
```

| Result | Exit code |
|---|---|
| **75 passed** across 9 test files | **0** |

Test files passing: `engineering.test.ts`, `api.test.ts`, `response-validation.test.ts`, `telemetry-window.test.ts`, `diagnostics.test.ts`, `alerts.test.ts`, `alarm-audio.test.ts`, `PumpScene.test.tsx`, `App.test.tsx` (45 tests).

### Frontend regression tests (after Vite proxy fix)

```powershell
cd apps\web; npm test -- --run
```

| Result | Exit code |
|---|---|
| **75 passed** across 9 test files | **0** |

No regressions from the proxy default change (vite.config.ts is not imported by vitest tests).

### Production build + TypeScript check

```powershell
cd apps\web; npm run build
```

| Result | Exit code |
|---|---|
| `tsc -b` passed + Vite build passed | **0** |

Build output:
```
dist/index.html                      0.56 kB │ gzip:   0.34 kB
dist/assets/index-Zz6xcMhh.css      39.47 kB │ gzip:   8.59 kB
dist/assets/index-CrpR19G9.js      285.88 kB │ gzip:  86.85 kB
dist/assets/PumpScene-Da37uhYS.js  567.97 kB │ gzip: 142.14 kB
```

One standing advisory (Three.js chunk > 500 kB); not a build failure.

---

## 5. Vite Proxy Verification

- Port 8001 is live and healthy (verified by `Invoke-WebRequest` against `/health` → HTTP 200).
- Port 8001 accepts the full Phase 1 `live-sample` request body (verified by direct POST → HTTP 200).
- After the `vite.config.ts` fix, `npm run dev` will proxy `/api` and `/health` to port 8001 by default.
- Port 8001 was not killed or restarted; it was an existing running process.

**To start the frontend against the compatible backend:**

```powershell
cd D:\Hackathon\PumpGuard
.\.venv\Scripts\Activate.ps1
# In a separate terminal (if not already running):
uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload

# In another terminal:
cd apps\web
npm run dev
# → opens http://127.0.0.1:5173, proxied to http://127.0.0.1:8001
```

No kill script is needed or recommended. Do not kill unidentified processes on port 8000 — it is an unrelated or legacy process.

---

## 6. `scripts/kill_port.ps1` — Status

This file **does not exist** in the repository. It was described in the previous session's response as having been created but was never written to disk. **No kill script was created, no recommendation to use one is made, and no such file should be added.** Users should start backends on whichever port is free and use `PUMPGUARD_API_PROXY_TARGET` to point the Vite proxy at it.

---

## 7. Real Browser Verification via Headless Edge & Chrome DevTools Protocol

> [!NOTE]
> A live browser smoke test was executed against the running Vite frontend at `http://127.0.0.1:5173` (proxied to the compatible backend at `http://127.0.0.1:8001`) using Microsoft Edge via the Chrome DevTools Protocol (CDP) (`scripts/smoke_test_cdp.py`).

### Verified Browser Flows & Evidence

| Flow / Requirement | Test Method & Observed Values | Status |
|---|---|---|
| **1. Dashboard load & 3D pump twin** | Page loaded title `'PumpGuard \| Pump Monitoring'`. Three.js `<canvas>` element present in DOM (`canvas present: True`). Suspense resolved procedural 3D pump mesh. | **PASS** |
| **2. All five scenarios selectable** | Checked scenario buttons: `Normal operation`, `Overheating`, `Bearing wear`, `Cavitation`, `Rotor imbalance`. Each clicked and switched active scenario state. | **PASS** |
| **3. Continuous live sampling & charts** | Clicked `Generate simulation →`. Live sampling started (`SIM TIME` advancing, 16 trend sparkline and time-series SVG graphs actively rendered with live coordinates). | **PASS** |
| **4. Live telemetry callouts on 3D panel** | Real values rendered dynamically on the 3D twin: Inlet pressure 178.7 kPa, Outlet pressure 320.0 kPa, Impeller speed 1783.7 rpm, Bearing temperature 44.2 °C, Flow rate 48.0 m³/h, Vibration 2.3 mm/s, Motor current 15.4 A. | **PASS** |
| **5. Overheating alert & warning state** | Triggered `Overheating` scenario. Rule engine identified anomaly. State updated: `1 active alert`, health badge `WARNING`, operational score `85/100`, unacknowledged alarm UI and acknowledge button displayed. | **PASS** |
| **6. Alert acknowledgement & persistence** | Clicked `ACKNOWLEDGE ALARM — SILENCE SIREN`. State transitioned to `ACKNOWLEDGED — FAULT ACTIVE`. Acknowledged state persisted across multiple live polling intervals without reverting or silencing prematurely. | **PASS** |
| **7. Multi-fault scenario transitions** | Tested `Bearing wear`, `Cavitation`, and `Rotor imbalance` transitions; each reported active alerts and updated detection patterns without crash. | **PASS** |
| **8. Fault recovery to Normal** | Clicked `Reset to normal operation`. Telemetry recovered to baseline: health badge transitioned to `NORMAL`, alerts resolved to `0 active alerts`, simulation state `RUNNING / FAULT NONE DETECTED`. | **PASS** |
| **9. Simulation lifecycle (Pause, Resume, Stop)** | Clicked `Pause simulation Ⅱ` → state became `PAUSED`. Clicked `Resume simulation ▶` → resumed. Clicked `Stop live simulation` → state became `STOPPED`. | **PASS** |
| **10. Diagnostic inspector & mock labeling** | Diagnostic inspector panel loaded with explicit labeling: mock mode indicated, synthetic telemetry disclaimer displayed, priority rationale shown. | **PASS** |
| **11. Missing credentials isolation** | Application operated without external credentials. Missing AMD credentials cleanly defaulted to mock provider without runtime exceptions. | **PASS** |

### Network & Console Audit

- **Network Requests**: All live-sample and generate calls routed through Vite proxy (`127.0.0.1:5173` → `127.0.0.1:8001`) with **HTTP 200**.
- **422 Validation Errors**: **0 encountered**. Rejection of Phase 1 fields confirmed completely resolved by pointing proxy default to port 8001.
- **Frontend Console Errors**: **0 fatal exceptions or uncaught errors**. Only standard informational Vite and Web Audio autoplay warnings before user gesture.

---

## 8. ML Investigation Summary

_(No code changes; documentation only.)_

| Finding | Evidence |
|---|---|
| Trained MLP is **not used** by the live dashboard | `docs/phase4-ml-evaluation.md` §Scope; `src/pumpguard/api/routes/pumps.py` — `assess_reading()` is the only health engine called |
| In-distribution macro F1 = 0.983 (MLP) | `phase4-ml-evaluation.md` aggregate table |
| Shift-condition macro F1 = 0.082 (MLP and LR) | Same table: `unseen pump configuration + baseline/drift shift` |
| Root cause: distribution shift, not a code bug | Baseline temperature 76 °C, vibration 2.8 mm/s, RPM 1680 — far outside training range (~68 °C, ~2.1 mm/s, ~1780 RPM). The standardized feature values fall far outside the learned decision boundaries. The model collapses to predicting `cavitation` for all classes. |
| Preprocessing is correct | Imputer and scaler fitted on training split only; pump-group splits prevent leakage; confirmed in `run_robustness.py` |
| Random Forest scores 0.947 on the same shift test | Not a reason to swap models: selecting from the final holdout is test-set selection; not reproducible without an independent validation set covering the new operating range |
| Confidence is unreliable under shift | 295/400 MLP predictions at score ≥ 0.90 are wrong; the validation-selected reject threshold flags 0/400 — scores are not calibrated OOD indicators |

**No ML model, threshold, inference path, or live dashboard was changed.**

---

## 9. Current Status and Remaining Blockers

| Item | Status | Notes |
|---|---|---|
| **Core simulation demo & dashboard** | **VERIFIED & WORKING** | All 5 scenarios, controls, alert lifecycle, and 3D digital twin verified via live browser and automated regression suites. |
| **Vite proxy routing** | **FIXED & VERIFIED** | Defaults cleanly to port 8001. No HTTP 422 errors. |
| **AMD API integration** | **PENDING** | Token Factory access is still pending. Cleanly isolated via Mock provider. |
| **Unrelated process on port 8000** | **IGNORED / NON-BLOCKING** | Older process on port 8000 was safely left intact and bypassed. |

---

## 10. Demo Startup Instructions

To start the demo cleanly in two terminals:

### Terminal 1: Backend (Port 8001)
```powershell
cd D:\Hackathon\PumpGuard
.\.venv\Scripts\Activate.ps1
uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload
```

### Terminal 2: Frontend
```powershell
cd D:\Hackathon\PumpGuard\apps\web
npm run dev
```

Open browser at `http://127.0.0.1:5173`.
1. Click **Generate simulation →** to launch continuous live monitoring.
2. Cycle through the scenarios (`Overheating`, `Bearing wear`, `Cavitation`, `Rotor imbalance`).
3. Observe alert episodes, acknowledge alerts, and click **Reset to normal operation** to demonstrate recovery.
