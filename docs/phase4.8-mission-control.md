# Phase 4.8 — Mission Control UI

## Visual update

The monitoring interface now uses a dark graphite Mission Control palette with semantic surface, text, separator, status, and safety-orange tokens. Headings use the existing system sans-serif stack; telemetry values retain tabular monospace numerals. The former warm-paper gradient grid and health-ring gradient were removed. The pump scene keeps its procedural geometry, stable component IDs, controls, animation, and warning/critical highlighting, with a dark viewport and restrained grid. Each telemetry trend now has a stable metric-specific color.

The existing desktop two-region layout is retained: the interactive pump, simulation controls, and alert history occupy the main region; Operating Parameters occupies the former Evidence & Fault Relationship dashboard region. The Diagnostic Inspector with evidence and fault relationships remains after alert history. The five displayed readings, units, assessments, trends, freshness labels, and timestamps continue to come from the backend and its bounded history. No API, health rule, threshold, alert, or scenario behavior changed.

## Verification

Commands run from `D:\Hackathon\PumpGuard` or `D:\Hackathon\PumpGuard\apps\web`:

- `D:\Hackathon\PumpGuard\.venv\Scripts\python.exe -m pytest -q` — 51 passed. One existing Starlette/httpx deprecation warning remains.
- `npm test -- --run --reporter=dot` — 48 passed across 8 frontend test files.
- `npm run build` — passed. Vite reports the lazy Three.js chunk at 567.97 kB minified (142.14 kB gzip), above its 500 kB advisory threshold.

The local browser was checked at 390, 768, 1024, and 1440 CSS-pixel viewport widths. Document and body widths matched the available viewport at each size; no horizontal overflow was measured. The 1440-pixel live view showed all five backend telemetry values and five timestamped trend lines with distinct metric colors, a fresh normal assessment, and the interactive pump. Those readings came from the synthetic simulator and are not real equipment readings or validation. Operating Parameters and the Diagnostic Inspector placements were present in the rendered DOM.

The in-app browser console reported Vite HMR WebSocket connection errors while accessing localhost through its browser bridge. HTTP module loading and the API simulation request still succeeded. This is a development hot-reload limitation in that browser session; it does not affect the successful production build. The browser check exercised a normal simulation only; fault scenarios, API failures, stale data, acknowledgement, and WebGL fallback remain covered by existing automated tests and prior phase verification, not re-run manually for this visual revision.

## Local launch

In separate PowerShell terminals:

```powershell
cd D:\Hackathon\PumpGuard
.\.venv\Scripts\Activate.ps1
uvicorn apps.api.main:app --host 127.0.0.1 --port 8001 --reload
```

```powershell
cd D:\Hackathon\PumpGuard\apps\web
npm run dev
```

Open `http://127.0.0.1:5173/`. Select a scenario and click **Generate simulation** to start backend-driven live telemetry. All scenario readings remain synthetic.
