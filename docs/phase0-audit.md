# PumpGuard ACTIII Phase 0 — Engineering Audit

## Scope and repository state

This audit follows the current telemetry-to-chart path, alert lifecycle, scenario transitions, API validation, and simulator boundary. It also checks that rule-based assessments, optional scenario classification, and future explanatory text remain separate.

The requested Git status check was attempted before edits, but `D:\Hackathon\PumpGuard` is not a Git repository (`git status --short --branch` returned “not a git repository”). There is no Git diff or clean/dirty status to report. No existing files were overwritten by this audit.

## Telemetry and chart path

1. `POST /api/v1/simulation/generate` validates a `SimulationRequest`, calls `TelemetryGenerator.generate_sequence`, stores those readings in the bounded process-local `TelemetryService`, and returns the scenario label, batch readings, and assessment of the newest reading.
2. The frontend validates the response against its scenario, pump ID, reading ranges, timestamp freshness, and assessment shape before updating telemetry, assessment, the 3D scenario, or charts.
3. The initial chart window comes from that validated response. It deliberately does not seed itself from the unlabelled telemetry-history endpoint, which may contain samples from earlier runs or scenarios.
4. A successful Generate action starts polling `POST /api/v1/simulation/live-sample`. Each accepted, strictly newer response updates the latest cards and assessment and prepends its reading to a bounded 120-reading window. Sparklines sort samples chronologically and display the latest 48.
5. Changing scenario clears the current telemetry, assessment, and chart window. The next poll uses the new scenario. A cancelled prior request is ignored, and the in-flight guard serializes requests.

### Graph defects found in the implementation history and current protections

- A one-time batch did not provide continuing graph data. Automatic live sampling now starts after Generate.
- Seeding charts from shared, unlabelled history could mix readings from prior scenario runs. Charts now seed from the validated, scenario-labelled response and reset on a scenario change.
- Two clients using the same pump ID could reset each other's deterministic live sequence. Current browser clients send a per-page `client_session_id`; the backend keeps those sessions separate.
- Out-of-order, stale, malformed, wrong-pump, or wrong-scenario responses could otherwise overwrite displayed values. Validation, cancellation, and monotonic timestamp checks reject them.

These protections are present in the current source. Phase 0 did not find a remaining graph-data defect. The scenario-switch regression test was strengthened to verify the graph resets and an old alarm resolves only after a fresh normal assessment.

## Alert lifecycle

The rule engine produces warning/critical metric findings. `reconcileAlerts` turns each pump/metric/expected-range condition into one in-session episode. Observed value and severity can change without changing its ID or acknowledgement. An episode is resolved only when a successful fresh assessment omits that condition. Failed or stale polling does not resolve it. A later recurrence receives a new ID.

The alarm action is derived from active, unacknowledged episode state. The siren controller separately observes that state, sound preference, and audio availability. Acknowledgement silences the acknowledged episode but leaves its condition active. Muting audio does not acknowledge or hide the alert. Existing tests cover repeated readings/severity changes, simultaneous alerts, acknowledgement, resolution, API failures/recovery, and stale responses.

The prior flicker cause is fixed in current source: severity had been part of episode identity, so crossing a warning/critical boundary resolved one ID and created another. Severity is now mutable episode state; the stable key is pump ID, metric, and expected range.

## Contracts, validation, and loading/error behavior

- Backend request schemas reject unsupported scenarios and invalid ranges; response models retain the existing simulation/assessment contract.
- Frontend response validation verifies scenario, pump identity, telemetry ranges, timestamp ordering/freshness, and assessment/anomaly fields.
- API fetches have an 8-second timeout. Live failures show unavailable/disconnected state and preserve the last accepted data and alert lifecycle; polling retries.
- A successful Generate response is the transition from ready/loading to live. The application has no separate live-monitoring start/pause control; the 3D animation pause remains visual only.
- The Phase 0 regression test confirms a fault episode stays visible during a scenario switch until the new scenario returns a fresh assessment, then resolves correctly when normal conditions are reported.

## Assessment and explanation boundaries

The production assessment path is rule-based (`assess_reading` and configured detection rules). The optional PyTorch/scikit-learn code is a separate offline scenario-classification experiment; it does not replace the health engine or feed the alert lifecycle. No LLM, AMD API, or external explanation service is present in the assessed API/frontend paths. Future explanations must remain a separate presentation layer and must not be represented as measured evidence or model health output.

## Simulator integration seam

`LiveSimulationService.next_sample(pump_id, scenario, seed, client_session_id)` is the narrowest safe future integration boundary. The API route can continue to accept the existing request and return the same `SimulationResponse` while delegating sample production to a deterministic engine that returns a validated `TelemetryReading`. Keep assessment generation in `assess_reading` and leave labels separate from sensor inputs.

The current live service has scenario-specific progression logic and calls the generator's private `_normal` helper. A future engine should replace or sit behind this service boundary; Phase 0 does not refactor or implement it. This preserves the API, current scenarios, and frontend while allowing a more capable deterministic simulator to be introduced behind the adapter.

## Verification configuration observations

- `apps/web/package.json` defines `test` and `build` but no lint script. No ESLint configuration was found.
- `npm run build` invokes `tsc -b` before Vite, so the frontend TypeScript build/type check is included.
- No Ruff, mypy, Pyright, or tox configuration was found for Python. The Python test suite is the configured check.
- The production bundle currently triggers Vite's advisory because the lazy Three.js chunk exceeds 500 kB minified.
- Git-based change inspection is unavailable because the project directory has no `.git` metadata.
