# PumpGuard ACTIII Phase 1 — Simulator

## Scope and integration

The deterministic simulator lives in `src/pumpguard/simulator/engine.py`. `LiveSimulationService` adapts one engine per bounded `(pump_id, client_session_id)` session, and the existing `POST /api/v1/simulation/live-sample` route still returns the established `scenario_label`, one-element `readings`, and `assessment`. It accepts optional control fields; old clients remain valid. Live telemetry includes optional simulator instrumentation fields. The existing batch `/simulation/generate` route and assessment thresholds are unchanged.

The frontend starts polling after Generate, pauses/resumes polling for simulation control, sends slider changes to the same live API, and resets the backend session on reset. Its graph history remains capped at 120 samples. The API session stores a capped 32-entry event log and is process-local; this is not durable replay storage. Reproduce an experiment by reusing the selected scenario, seed and configuration, then resetting the session.

## Variables and assumptions

All figures are synthetic, bounded and for demonstration only. They are not validated pump physics or industrial design limits.

| Variable | Unit / UI range | Illustrative relationship |
|---|---|---|
| Shaft speed (`rpm`) | RPM; derived around 1,260 + 8 × load% | Load-dependent baseline with seeded variation and scenario effect |
| Load | percent; 10–100 | Raises power, temperature, flow and baseline vibration |
| Flow | m³/h; bounded 0–10,000 | Scales with load and declines with inlet restriction |
| Inlet / outlet pressure | kPa; schema bounded 0–2,000 | Restriction reduces inlet and outlet pressure; cavitation adds a pressure drop |
| Motor temperature | °C; schema bounded −20–250 | Ambient + load heat divided by cooling effectiveness, plus fault effect |
| Bearing temperature | °C; schema bounded −20–250 | Load and vibration-related contribution |
| Vibration | mm/s; schema bounded 0–100 | Load baseline plus fault signature and seeded noise |
| Sound | dB; schema bounded 0–160 | Load baseline plus fault signature and seeded noise |
| Power / current | kW / A; bounded 0–10,000 | Power increases with load and restriction; current is a simplified three-phase conversion at 400 V and 0.88 power factor |
| Cooling effectiveness | fraction; 0.2–1.0 | Lower effectiveness raises modeled motor temperature |
| Inlet restriction | percent; 0–70 | Reduces modeled flow and pressure |
| Speed multiplier | 0.25–4× | Adds that many simulation seconds on each wall-clock live sample |

Seeded NumPy noise makes the numerical sequence reproducible for a given seed and configuration. Timestamps are wall-clock API timestamps, so separate runs do not have identical timestamp strings. The live engine is deterministic within a process session; sessions are not persisted across restarts.

## Fault behavior

- `normal`: operating baseline; no fault signature is applied.
- `overheating`: elevated motor-temperature channel.
- `bearing_wear`: increased vibration and sound, gradual bearing-temperature rise, and a small speed reduction.
- `cavitation`: lower pressure and flow, irregular vibration/noise, and a small speed reduction.
- `imbalance`: increased, oscillating vibration and a smaller sound increase.

An enabled fault starts at the selected severity. Disabling it initiates a bounded gradual decay; the rule engine alone determines whether current measurements still produce an assessment. Severity and operating-condition changes produce event markers. Fault scenario and injected state are simulator ground truth and are not added as telemetry sensor fields or passed as assessment features. The existing `scenario_label` is kept as response metadata for the operator/demo path.

## Operator controls and display

Generate starts live sampling automatically. Pause stops frontend polling and therefore freezes the simulation clock; resume continues the same backend session. Reset requests the normal batch and resets the next live session using the configured seed. Scenario changes clear the current chart window and the backend creates a fresh scenario session. Changing speed, load, cooling, restriction, severity or injection updates the live engine on the next accepted poll. Simulation time and a short event list are displayed in the control panel.

The existing Three.js model receives validated telemetry and continues to drive shaft rotation from RPM-derived engineering metrics. Existing assessment-based component highlights remain indicative only. No new mechanically certified animation is claimed.

## Limitations

- This is a compact equation-based illustration, not a validated hydraulic or thermal model. It omits pump curves, fluid properties, cavitation vapor-pressure calculations, motor electrical dynamics, pipe-network boundary conditions and calibration against hardware.
- Vibration is an aggregate scalar; phase, frequency spectra, bearing defect frequencies and sensor mounting are not modeled.
- Rule assessments may not flag every injected fault, and a detected anomaly does not prove the simulator's ground-truth fault or real equipment damage.
- Optional instrumentation values are currently provided by the live-sample engine; the existing batch endpoint remains compatible and does not synthesize all expanded operating fields.
- Event history and engine sessions are in-memory and bounded. No persistent scenario archive or server-side replay browser was added.
- No AMD service/API, cloud resource, database, LLM or external AI service is used.
