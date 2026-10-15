# PumpGuard ACTIII Phase 1 — Simulation dashboard UI results

## Implemented

- Reworked the existing React simulation view into a responsive three-column control-room layout with PumpGuard header/navigation, left scenario/control rail, central procedural Three.js twin, and right system status/diagnostic panels.
- Added compact measurement cards and SVG time-series charts sourced from the existing bounded telemetry window. Each chart displays only fields actually supplied by the API and shows an unavailable/collecting state when data is missing.
- Added current-value callouts on the 3D panel for inlet/outlet pressure, RPM, bearing temperature, flow, vibration and motor current. These read the same current telemetry object as the rest of the dashboard.
- Added a simulation session timeline from API simulator events, current alert lifecycle records, operator actions and successful diagnostic requests. Event history is in-memory for the current page session.
- Added a bounded motor RPM setpoint control end-to-end through the existing live-sample API, while retaining simulation time speed as a separate control. The control changes the engine's actual generated RPM.
- Added a real stop-live-polling control. Existing pause/resume and reset behavior remain connected to the monitoring lifecycle.
- Added responsive layouts for tablet and phone widths. Fleet View remains disabled because no fleet destination is implemented. Existing 3D animation pause and camera reset are the supported model controls; thermal/X-ray/exploded/flow display modes are not presented as working controls.

## Data sources and limits

| Panel | Source |
|---|---|
| System status and health score | Existing deterministic backend assessment and its threshold findings |
| Sensor cards, callouts and live charts | Latest API telemetry plus the bounded per-scenario reading window |
| Diagnostic inspector | Existing operator-triggered diagnostic API and mock/availability status |
| Alarm history and acknowledgement | Existing alert reconciliation and acknowledgement state |
| Timeline | Live simulator event markers, alert events, and actual operator/diagnostic actions during this page session |
| Vibration FFT | Explicitly unavailable; current API does not provide frequency-domain samples and no FFT is fabricated |

All data remains synthetic. Model highlights and diagnoses are not proof of equipment damage or real-world predictive accuracy. No AMD API call or credential is needed. The existing model is procedural Three.js, not a static image.

## Files changed

- `apps/web/src/App.tsx` — new dashboard panels, charts, callouts, navigation, timeline, actual motor-speed control wiring and stop action.
- `apps/web/src/styles.css` — dashboard tokens/layout, panel styling and responsive breakpoints.
- `apps/web/src/api.ts` — optional bounded live-sample `rpm_setpoint` contract and snapshot typing.
- `src/pumpguard/simulator/engine.py` — independently configurable RPM setpoint and condition-change event recording.
- `src/pumpguard/simulator/live.py` — passes the setpoint through the existing live engine session.
- `src/pumpguard/api/routes/pumps.py` — validates and forwards RPM setpoint in the existing live-sample endpoint.
- `apps/web/vite.config.ts` — allows the local API proxy target to be overridden with `PUMPGUARD_API_PROXY_TARGET`, retaining port 8000 as the default.
- `tests/test_api.py`, `tests/test_simulation_engine.py`, `apps/web/src/App.test.tsx` — setpoint bounds/generation and dashboard regression coverage.
- `docs/simulation-dashboard-ui-results.md` — this report.

## Verification

- `.venv\Scripts\python.exe -m pytest -q` — **81 passed**; one existing Starlette/httpx deprecation warning.
- `npm test -- --run` (`apps/web`) — **75 passed** across 9 files.
- `npm run build` (`apps/web`) — **passed**, including `tsc -b` and Vite production build. Vite retains its existing Three.js chunk-size advisory (567.97 kB minified, 142.14 kB gzip).
- The existing backend on port 8000 rejected the current live-sample fields, so I left that running process untouched and started the checked-in backend and Vite app separately on ports 8001 and 5175. Direct API request returned rich telemetry with the requested 2050 RPM setpoint. In the embedded browser at `127.0.0.1:5175`, verified live telemetry updates, scenario change to Bearing Wear, alert creation, acknowledgement, reset to Normal, confirmed alert resolution, and stopping live polling. The procedural Three.js pump rendered. The visible embedded viewport was roughly 780 px wide (tablet breakpoint); desktop 1536×1024 and phone widths remain unverified.
- No lint script is configured in `apps/web/package.json`. The project directory has no `.git` metadata, so Git status/diff could not be reported.
- The pre-existing service on port 8000 may need to be restarted with the checked-in project code before the original 5174 app is used; no existing process was stopped. A compatible review instance remains running at `http://127.0.0.1:5175/` with its backend on port 8001.

## Remaining limitations

- The reference's thermal, X-ray, exploded-view and flow-line modes are not implemented in the existing Three.js scene and are omitted as interactive claims.
- FFT is unavailable until a valid sampled signal is exposed by the simulator/API.
- The app has no separate maintenance, history-route or fleet pages. Header actions scroll to implemented sections; Fleet View is visibly disabled.
- The timeline and alert history are session-only and are lost on refresh.
- Visual comparison at 1536×1024 and a narrow phone viewport remains unverified in a real browser. CSS breakpoints and production compilation pass, but this report does not claim those browser checks occurred.
