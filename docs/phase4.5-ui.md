# Phase 4.5 — Monitoring console redesign

The frontend uses a graphite instrumentation-console layout with centralized semantic color tokens, a compact equipment navigation rail, a larger interactive pump viewport, adjacent scenario controls, live sensor instrumentation, and a contextual diagnostic inspector. At wide desktop widths, the diagnostic panel stays alongside the visualization and session event list. At tablet widths it joins the content flow; at phone widths the rail becomes a compact top navigation and the inspector stacks below the pump controls.

The redesign reuses the existing `PumpTwinApp`, API client, Three.js `PumpScene`, alert lifecycle, assessment results, and bounded telemetry history. It does not add telemetry, thresholds, routes, dependencies, or backend behavior. Selecting scenario and generating simulation remain distinct actions. Generate simulation starts continuous backend telemetry automatically; the 3D animation control only affects visual motion. The data is synthetic and the health score is rule-based, not a failure probability.

The workspace navigation scrolls to existing sections. There is no separate history page: alert history is in-session only. Diagnostics show evidence from the selected backend assessment/alert. On narrow layouts the sidebar icons retain accessible names and tooltips, and normal keyboard focus indicators remain enabled. Reduced-motion preferences disable smooth scrolling and transitions.

## Local verification

From `D:\Hackathon\PumpGuard\apps\web`:

```powershell
npm test -- --run --reporter=dot
npm run build
```

From `D:\Hackathon\PumpGuard`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Viewport checks should be performed at 390, 768, 1024, and 1440 CSS pixels in a browser with viewport controls. A manual check at the viewport exposed by the current in-app browser is not a substitute for all four widths.

## Results recorded for this implementation

- Python: `51 passed` (`python -m pytest -q` via the project virtual environment).
- Frontend: `41 passed` across 7 Vitest files (`npm test -- --run --reporter=dot`).
- Production build: passed (`npm run build`). The existing lazy Three.js chunk is 567.97 kB minified (142.16 kB gzip), so Vite continues to show its >500 kB advisory.
- Browser preview: visually inspected at the current in-app browser's default viewport; the redesigned condition header, active telemetry state, prominent 3D viewport, and compact navigation rendered. The API was already live in the browser.
- The browser tool available here exposes screenshots and accessibility state but not viewport resizing or developer-console inspection. Therefore 390/768/1024/1440 overflow checks, full scenario-by-scenario manual interaction, and console-log inspection are not claimed as completed. Existing automated tests cover the five scenarios, API failure/stale data, alerts, and scene fallback.
- Python test output includes the existing Starlette/httpx deprecation warning from `starlette.testclient`.
