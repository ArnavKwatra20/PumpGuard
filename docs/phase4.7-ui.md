# Phase 4.7 — Technical Editorial UI (historical visual revision)

## What changed

The monitoring page now uses a warm paper, near-black ink, and restrained safety-orange palette. Its composition gives the existing interactive Three.js pump the main visual area, with compact scenario controls, a five-channel instrument table and timestamped sparklines, a session alert log, and the Phase 4.6 evidence and fault-relationship explorer. Operating Parameters now occupies the former evidence panel's dashboard slot; the unchanged evidence explorer remains in a full-width Diagnostic Inspector after the alert log. At narrower widths, the parameter section stacks after the pump controls, followed by alerts and the inspector. Keyboard focus and reduced-motion styles are provided. The existing API client, polling, alert episode lifecycle, assessment rules, model geometry, component IDs, and health engine remain the source of operational behavior.

Telemetry labels identify the measurement and unit without asserting an unsupported physical sensor location. The UI does not show an expected range unless the backend assessment supplies one. Pressure is explicitly described as having no configured backend threshold. Trends use returned, timestamped history only. A stale or disconnected sample is not presented as live.

## Diagnostic provenance

The backend telemetry schema provides temperature (°C), vibration (mm/s), sound (dB), rotational speed (rpm), pressure (kPa), operating mode, timestamp, and pump ID. It does not provide physical sensor-location metadata. Pressure appears in the live simulator but does not have a health-rule threshold. The frontend displays backend-provided expected ranges and explanations; it does not copy or redefine thresholds.

Backend fault indicators are heuristic co-occurrence patterns for overheating, cavitation, bearing wear, and imbalance. They support symptom summaries and unconfirmed inspection hypotheses, not physical root-cause claims. The explorer distinguishes observed backend findings, other abnormal measurements, unconfirmed possible contributors, and backend recommendations. The 3D component highlight remains a suspected region based on the existing mapping.

All displayed scenario readings are synthetic. The live simulator's scripted progression is illustrative; it is not a validated physical model of pump dynamics. No real-world predictive-maintenance accuracy is established.

## Verification

Automated checks run for this revision:

- Python: `.\.venv\Scripts\python.exe -m pytest -q` from the repository root — 51 passed.
- Frontend: `npm test -- --run --reporter=dot` — 48 passed across 8 files.
- Production build: `npm run build` — passed. Vite reports the existing Three.js scene chunk at about 568 kB minified (142 kB gzip), above its 500 kB advisory threshold.

The local page at `http://127.0.0.1:5173/` was inspected in the in-app browser. A manual walkthrough generated live samples for normal, overheating, bearing wear, cavitation, and imbalance. The overheating and rotating-fault patterns produced backend findings; returning to normal led to a fresh healthy assessment and resolution of the previous critical vibration episode. Browser state also showed the live values, timestamped trends, evidence, suspected region, and recommendations. The console returned no warning or error entries.

Responsive widths were explicitly set to 390, 768, 1024, and 1440 CSS px. At each width, `document.documentElement.scrollWidth` and `document.body.scrollWidth` matched the available client width (375, 753, 1009, and 1425 px respectively, after the browser scrollbar), so no horizontal page overflow was measured. The 390 and 1024 px layouts were visually inspected; other width checks used DOM dimensions. The browser remained on its default viewport after testing. Acknowledgement, mute state, API failure, stale-data handling and scene fallback are covered by the automated frontend suite; those cases were not separately triggered in the manual walkthrough.

## Local launch

In two PowerShell terminals:

```powershell
cd D:\Hackathon\PumpGuard
.\.venv\Scripts\Activate.ps1
uvicorn apps.api.main:app --reload
```

```powershell
cd D:\Hackathon\PumpGuard\apps\web
npm run dev
```

Open `http://127.0.0.1:5173/`.


## Superseded visual revision

The warm-paper palette documented above was replaced by the Mission Control UI redesign. The current application uses the dark graphite palette and neutral sans-serif hierarchy documented in the root README. The Phase 4.7 structural and provenance notes remain applicable: Operating Parameters occupies the former evidence panel slot, the evidence explorer stays in the Diagnostic Inspector, and telemetry/assessment/alert behavior remains backend-driven.
