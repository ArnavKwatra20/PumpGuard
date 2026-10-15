# PumpGuard Complete Project Audit Report

Audit date: 2026-10-14 (Asia/Calcutta)

Scope: local repository, local FastAPI/Vite development services, synthetic simulator, offline ML artifact, controlled live AMD catalog and chat-completion probes, and mocked adapter regression tests. No credentials, secrets, persistent databases, external data, deployment targets, or Git history were modified.

## Executive summary

Overall status: **PARTIAL / DEMO-READY, NOT PRODUCTION-READY**.

The core local application works: the backend starts, the frontend builds, the rule-based assessment path is operational, simulation scenarios produce bounded synthetic telemetry, alert state is rendered, and the browser dashboard was exercised successfully. The latest backend suite passed 144 tests. The frontend fixture-isolation defect found during final stabilization was fixed, and five consecutive complete frontend runs passed 88/88. Browser verification showed live telemetry, rule-based warning assessment, alert history, trend cards, pause/stop controls, and the diagnostic-chat UI; browser console error/warning collection was empty.

The highest-impact verified issues were:

1. Live samples could receive duplicate wall-clock timestamps during rapid polling. The UI deliberately rejects non-advancing samples, so this could silently drop valid telemetry. Fixed with a strictly increasing automatic timestamp guard and a regression test.
2. The UI continued to say AMD availability was “not yet verified” after a successful catalog response. Fixed to say “catalog verified; inference unverified,” preserving the important distinction.
3. AMD transport and the documented OpenAI-compatible response envelope are verified. The conversational chat now passes the previously failing condition-change question through live AMD content extraction, grounding, result construction, and HTTP serialization. The structured diagnostic still fails at the upstream response timeout boundary. Rule-based detection remained independent and operational.

Remaining uncertainties are AMD inference reliability/response compatibility under real request conditions, GPU/ROCm execution, real industrial validity, long-duration browser memory behavior, and production authentication/deployment controls.

## Architecture

Data flow:

```text
LiveSimulationService / TelemetryGenerator
        -> TelemetryService bounded in-memory history
        -> assess_reading deterministic threshold engine
        -> FastAPI response
        -> React polling/API validation
        -> dashboard cards, charts, alerts, 3D procedural scene

Offline data generator -> feature engineering/split/evaluation -> optional PyTorch MLP artifact
Diagnostic request -> bounded DiagnosticService -> mock or AMD provider
AMD provider -> /models catalog verification -> /chat/completions inference -> schema/grounding validation
```

Backend entry point is `apps/api/main.py`, importing the FastAPI app factory in `src/pumpguard/api/app.py`. Routes cover health, pumps, simulation, telemetry history, assessments, diagnostics, ML status, telemetry analysis, and fault relationships. State is process-local and in memory; there is no database or migration system.

Frontend is React 19 with Vite and Three.js. `App.tsx` polls one live sample per second after Generate, validates pump/scenario/timestamp freshness, bounds the chart window, reconciles alerts, and renders the procedural pump scene. The Vite proxy targets the local API. The browser bundle contains no AMD credential; optional AMD calls go through FastAPI.

External operations: AMD catalog and diagnostic inference only. Local rule assessment, simulator, relationship analysis, telemetry analysis, and dashboard state do not require AMD. The installed PyTorch runtime reports `2.7.1+cpu`, no HIP runtime, no visible devices, and CPU execution. AMD service configuration does not imply AMD GPU access.

## Test results

| Check | Result | Evidence |
|---|---:|---|
| Initial backend baseline | 116 passed, 3 failed, 1 warning | Three optional PyTorch training tests failed once in `torch._dynamo` with missing `NP_SUPPORTED_MODULES`. |
| Final backend suite | **143 passed**, 1 warning, 26.82 s | `.\.venv\Scripts\python.exe -m pytest -q` |
| ML-focused rerun | **13 passed**, 6.03 s | `pytest tests/test_ml_pipeline.py tests/test_robustness.py -q -rs` |
| Focused affected tests | **8 passed** | Live simulation timestamp regression |
| AMD/diagnostic focused suite | **43 passed**, 1 warning, 13.58 s | `pytest tests/test_diagnostics.py tests/test_diagnostic_chat.py tests/test_ai_features.py -q` |
| API/diagnostic/simulation focused suite | **39 passed**, 1 warning, 16.38 s | `tests/test_diagnostics.py tests/test_api.py tests/test_simulation_engine.py` before the added envelope regression |
| Frontend baseline | **88 passed** across 11 files, 20.23 s | Earlier completed audit run: `npm test -- --run --reporter=dot` |
| Follow-up diagnostic frontend tests | **11 passed** across 2 files, 4.13 s | `DiagnosticChat.test.tsx` and `AiFeaturePanel.test.tsx` |
| Final full frontend suite | **88 passed** across 11 files, five consecutive runs | `npm test -- --run --reporter=dot`; all five runs passed |
| Frontend production build | **PASS** | `npm run build`; existing Three.js chunk advisory: 567.97 kB minified / 142.14 kB gzip |
| Python syntax/import compilation | **PASS** | `python -m compileall -q src apps scripts tests` |
| Dependency consistency | **PASS** | `pip check` reported no broken requirements |
| Frontend production dependency audit | **PASS** | `npm audit --omit=dev --audit-level=high`: zero vulnerabilities in the lockfile dependency graph |
| Lint/type checks | **PARTIAL** | TypeScript checking is included in the build; no Python linter/type checker or frontend lint script is configured |
| Browser console | **PASS for observed session** | No error/warning entries returned |

The initial PyTorch failure was not reproducible in the final rerun. It is retained as baseline evidence and should be treated as an environment/package-integrity concern until the optional ML environment is recreated and verified independently.

## Browser verification

The real local browser page at `http://127.0.0.1:5173/` loaded successfully against the backend at `http://127.0.0.1:8001`.

Verified in the browser:

- Overheating scenario selection and Generate action.
- Live telemetry cards, timestamps, charts, motor/bearing/flow/pressure values, and 3D pump scene.
- Warning assessment at 85/100 with temperature threshold evidence.
- Active alert and session event history.
- Pause changed the live simulation to `Simulation paused`.
- Stop changed the simulation state to `STOPPED`.
- AMD model inspection rendered 12 catalog models and capability metadata.
- After the fix, status rendered `catalog verified; inference unverified`.
- Browser console returned no errors or warnings.

The diagnostic-chat UI was exercised with fresh synthetic telemetry. The one bounded browser request returned a sanitized `Not Found` error because the already-running API process predated the new route. The process was then restarted from the repository virtual environment and the route was confirmed in the current OpenAPI application; no second live AMD chat request was made.

Not claimed: speaker/audio hardware verification, all responsive viewport sizes in this run, WebGL performance profiling, or a successful AMD explanation/chat response rendered in the browser.

## Findings

### P1 — Live dashboard 502 was caused by a stale duplicate Uvicorn process — FIXED OPERATIONALLY

The failing browser request was `POST http://127.0.0.1:8001/api/v1/simulation/live-sample`, sent by `apps/web/src/api.ts` with the dashboard's bounded simulator controls. It expects a `SimulationResponse` containing one validated reading, the rule-based assessment, and the live simulation snapshot.

The 502 was not produced by AMD, the simulator engine, request validation, or the frontend response validator. Port 8001 had duplicate Uvicorn processes: an older process was serving the dashboard port while the current repository process was not the process being exercised. After stopping only the stale PumpGuard API instances and starting the repository API configuration, the current OpenAPI route and direct endpoint returned HTTP 200 with valid synthetic telemetry. The dashboard then displayed `LIVE`, fresh timestamps, current readings, and a normal rule assessment.

The endpoint was also tested with a diagnostic provider that raises on every diagnostic call; live simulation still returned HTTP 200. This confirms simulation telemetry remains independent of AMD availability. No simulator code or AMD provider/model was changed for this incident. The relevant development API process was restarted; no unrelated process was modified.

### P2 — Duplicate automatic live timestamps could drop valid samples — FIXED

Evidence: five rapid local `/api/v1/simulation/live-sample` requests advanced simulation time from 1.0 to 5.0 seconds, but two consecutive response timestamps were identical. `apps/web/src/response-validation.ts` rejects any timestamp that is not strictly newer than the previous sample.

Root cause: `PumpSimulationEngine.tick()` used `datetime.now()` directly, whose effective resolution can be lower than the request loop rate.

Correction: `src/pumpguard/simulator/engine.py` now advances an automatic timestamp by one microsecond when wall-clock time has not advanced. Explicit caller timestamps remain unchanged. `tests/test_live_simulation.py` adds a 40-sample strict-monotonicity regression test.

Verification: focused live simulation tests 8/8 passed; final backend suite 122/122 passed.

### P2 — AMD catalog success was displayed as unverified availability — FIXED

Evidence: live `GET /api/v1/diagnostics/models` returned HTTP 200, 12 models, and the configured `DeepSeek-V4-Flash` model. The UI still displayed `availability not yet verified`.

Root cause: the status label only read initial provider status and ignored the successfully loaded catalog.

Correction: `apps/web/src/DiagnosticExplorer.tsx` now checks whether the configured model exists in the returned catalog and displays `catalog verified; inference unverified`. It does not overclaim inference success.

Verification: browser HMR view showed the corrected text after catalog inspection; frontend tests and build passed.

### P2 — Frontend regression fixture became stale during the full suite — FIXED

Reproduction: the four affected `App.test.tsx` cases passed in isolation but the full suite intermittently failed with missing telemetry, incorrect scenario state, or missing acknowledgement controls. The clearest failure was `anchors the generated batch so its newest sample is not future-dated`, which could not find the expected `69.5` reading after the suite had been running for roughly half a minute.

Root cause: the shared module-level `fixtureTimestamp` was created once when Vitest loaded the file. By the time late tests used the fixture, the production freshness validator correctly treated the response as stale. Isolated runs reloaded the module with a fresh timestamp, masking the defect.

Correction: `apps/web/src/App.test.tsx` now creates the fixture through `createFixture()` and refreshes it in `beforeEach`. Production freshness validation was not changed or weakened.

Verification: the four previously affected tests passed together; the complete frontend suite passed **88/88 in five consecutive normal runs**. The fix is test-fixture lifecycle isolation, not a relaxation of stale-telemetry handling.

### P2 — Structured telemetry evidence allowed a mismatched metric label — FIXED

The structured grounding validator checked that an evidence value matched the selected telemetry field, but did not check the optional `metric` label. A controlled provider fixture could therefore cite the `vibration_mm_s` value while labeling it `temperature_c` and still pass grounding.

Correction: telemetry evidence now requires `metric` to equal `field`; the AMD output contract and mock provider emit the explicit association. A regression test confirms mismatched metric labels are rejected as HTTP 502. The change preserves strict validation and does not broaden accepted evidence.

The adapter also now rejects explicit non-terminal finish reasons such as `content_filter` instead of attempting to parse them as successful structured output. The existing `length` truncation rejection remains unchanged.

### P2 — AMD live diagnostic contract is not fully verified; transport envelope is compatible — OPEN

Evidence: catalog request reached the configured AMD endpoint and returned HTTP 200 in approximately 1,746 ms. The minimal request returned HTTP 200 in 3,426.5 ms with `choices[0].message.content` containing JSON and `finish_reason: stop`. Full synthetic probes then showed: 700 output tokens caused an AMD read timeout at about 47–48 seconds and, with a 90-second client timeout, an AMD HTTP 502 at about 48 seconds; 256 and 512 token budgets returned HTTP 200 with `finish_reason: length` and invalid/truncated JSON; 600 tokens returned HTTP 200 in 18.3 seconds with `finish_reason: stop` and valid JSON, but strict Pydantic validation rejected a literal-valued field. No reasoning field was used.

Impact: optional AI explanations cannot currently be considered reliable. This does not block deterministic rule-based assessment, alerts, simulation, or telemetry rendering.

Root-cause classification: the full request is too slow/large for the AMD gateway’s observed approximately 48-second behavior at the configured 700-token budget, while smaller budgets can truncate the JSON. When a complete JSON response is obtained at 600 tokens, it can still contain a literal-value schema mismatch and is correctly rejected by strict Pydantic validation. The failure is therefore upstream response-budget/gateway behavior plus model-contract incompatibility; it is not the SDK envelope, content-field extraction, reasoning handling, or evidence grounding.

Correction: the adapter now records sanitized response, JSON parsing, Pydantic, grounding, and result-construction stages; explicitly rejects `finish_reason: length` as truncated output; and gives the model explicit concise JSON literal requirements without weakening validation. It does not retry, use reasoning as content, fabricate output, or convert a rule assessment into an AMD diagnosis. The current configured AMD model still did not produce a complete validated `DiagnosticResult` live, so the integration remains failure-isolated.

### P2 — Optional PyTorch environment had a transient internal package failure — OPEN / ENVIRONMENT

Evidence: initial full suite failed three training tests with `ImportError: cannot import name 'NP_SUPPORTED_MODULES' from torch._dynamo.utils`. The same ML tests later passed 13/13 in a fresh run, and the final full suite passed.

Impact: optional training reproducibility is sensitive to the local environment state. No production API path was broken by this transient failure in the final run.

Recommendation: recreate or verify the `.venv` from the documented CPU-only torch installation procedure and pin/check the complete torch package integrity in CI. Do not alter model artifacts based on this audit.

## AMD integration report

- Configuration was present without exposing the key. The project `.env` is ignored by Git; only `.env.example` is tracked.
- Local health succeeded independently: `GET /health` returned HTTP 200.
- Catalog succeeded: `GET /api/v1/diagnostics/models` returned HTTP 200, 12 models, and verified capability metadata including JSON-output support.
- Catalog calls are cached in process memory for three minutes and serialized by an async lock.
- Inference uses the configured model only after catalog membership verification, OpenAI-compatible client timeouts, `max_retries=0`, bounded output, strict schema validation, and evidence grounding.
- A minimal live inference probe genuinely succeeded at the transport/envelope level and returned JSON content, but it was not a full PumpGuard diagnostic request and therefore does not prove a valid `DiagnosticResult`.
- Observed full PumpGuard inference requests are not passing the application contract. Upstream HTTP 200 does not equal a valid PumpGuard diagnostic result.
- The live message used `reasoning_content`, while AMD documentation describes reasoning as separate from final `content`; PumpGuard correctly reads only `content`.
- Core rule assessment remained available while AMD inference failed; no telemetry, detector, alert, or health score was mutated.
- The configured UI/frontend diagnostic request timeout is 60 seconds; backend diagnostic timeout is 50 seconds with a 45-second provider response timeout derived from configuration. Live instrumentation showed the provider response stage timing out or receiving upstream 502 before content extraction on the 700-token request.
- The structured adapter sends one `POST /chat/completions` request using model `DeepSeek-V4-Flash`, `max_tokens=700`, and `response_format={"type":"json_object"}` only when the verified catalog advertises JSON output. The SDK uses `max_retries=0`, a 3-second connect timeout, and a 45-second response timeout under the default 50-second service deadline.
- A bounded direct comparison with the same configured model and endpoint produced: minimal text request (`max_tokens=16`) timed out at the 20-second diagnostic probe boundary; short JSON-mode request (`max_tokens=64`) returned HTTP 200 in 2.27 seconds with `finish_reason=stop`, 16-character content, and usage metadata; the full PumpGuard request returned no response before its application deadline and was classified as `ProviderTimedOut`.

Status: catalog **PASS** for this live run; minimal chat transport/envelope **PASS**; full PumpGuard inference **PARTIAL/UNVERIFIED**.

### Final bounded end-to-end verification

The corrected live structured request used a fresh synthetic fixture and reached the AMD provider after local validation. The catalog request returned HTTP 200, then the structured completion timed out at the provider response boundary after approximately 52 seconds. Sanitized server logs classified the failure as `ProviderTimedOut`; no JSON parsing, Pydantic validation, evidence grounding, `DiagnosticResult` construction, FastAPI serialization, or frontend rendering was claimed. The short JSON comparison succeeded, so the evidence does not support an unsupported model or JSON-mode parameter as the cause. The mocked valid fixture continues to pass every stage through HTTP 200 serialization.

The remaining timeout is therefore upstream/response-latency behavior for the larger PumpGuard generation, not a confirmed PumpGuard URL, SDK retry, model-selection, or structured-parameter defect. The smallest next diagnostic is provider-side timing/capability guidance for this model and prompt size; changing the model or increasing all deadlines would not be evidence-based.

### Final release-freeze verification

The structured request was measured at approximately 2.6k characters for the deterministic fixture, including approximately 488 characters of evidence. No evidence-based prompt-size defect was found, so no speculative request-contract reduction was made. A direct bounded comparison established that short JSON mode works with the configured model while the larger structured request times out upstream.

Final checks after the provider instrumentation change: backend **144 passed** with one existing Starlette/httpx deprecation warning; frontend **88 passed** across 11 files; production build passed with the existing Three.js chunk-size advisory; `pip check` passed; `npm audit --omit=dev --audit-level=high` reported zero vulnerabilities; and `git diff --check` reported no whitespace errors. No commits, pushes, deployments, provider/model changes, or credential changes were made.

### AMD-powered diagnostic chat

The new chat path is separate from structured `DiagnosticResult` generation:

```text
React DiagnosticChat
  -> POST /api/v1/diagnostics/chat
  -> authoritative backend telemetry + assess_reading + telemetry analysis
  -> bounded DiagnosticChatService
  -> MockDiagnosticProvider or AmdProvider.chat
  -> final assistant content only (never reasoning text)
  -> DiagnosticChatResponse -> frontend rendering
```

The backend rejects unknown pumps, oversized questions/history, empty provider content, upstream errors, and timeouts. Context is constructed server-side from the selected pump's in-memory telemetry and current rule assessment; browser-supplied telemetry is not accepted. The response is a plain assistant message and is not treated as a verified diagnosis or used to mutate rule-based health state.

Fixture coverage verifies valid response construction, authoritative-context enforcement, timeout and empty-content handling, provider status mapping, and AMD content-vs-reasoning extraction. Frontend coverage verifies sending, loading, retry, suggested prompts, clear confirmation, and pump-session separation.

Live status: one observed live AMD chat response passed content extraction, normalization, grounding, `DiagnosticChatResponse` construction, and FastAPI serialization with HTTP 200. Exact frontend DOM rendering of that response was not independently captured. Structured diagnostics remain live-unverified because the corrected provider-bound request timed out upstream.

### Diagnostic assistant input gating — FIXED

The assistant textarea was disabled whenever `providerStatus` was null or reported an unconfigured provider, even though the chat endpoint is designed to return a classified provider failure. This made `Provider status unavailable` incorrectly block typing and caused the not-allowed cursor. `DiagnosticChat.tsx` now treats provider status as informational; the textarea and suggestions depend only on the chat API being present, available telemetry context, and the active request state. Send remains disabled for empty input or while sending, and backend failures remain visible with retry.

Regression coverage verifies editable input with unavailable provider status, Enter submission, Shift+Enter newline behavior, and failure rendering. Browser verification after generating telemetry showed the input enabled, accepted typed text and a newline, and retained the expected informational AMD status.

### AMD chat response quality — FIXED / LIVE PROVIDER STILL VARIABLE

The provider returned HTTP 200 and `finish_reason=stop`, but the final assistant content contained malformed token concatenations such as `thresholdaine`, `secondstons`, and `bandsaine`. The adapter previously treated any non-empty string as valid, and the frontend rendered it as plain text, so escaped Markdown such as `\*\*warning\*\*` and corrupted words were shown literally.

The correction has three layers: the AMD prompt now requires concise professional engineering text, simple unescaped Markdown, paragraph spacing, explicit unit spacing, and evidence-only numerical claims; the backend normalizes harmless escaped bold markers and rejects HTML, unbalanced Markdown, control characters, glued unit/word tokens, overlong text, and numbers absent from the server-owned context; and the frontend renders only a small safe React Markdown subset for bold text, paragraphs, and bullets. It does not use `dangerouslySetInnerHTML` or treat reasoning as final content.

Focused fixture coverage verifies escaped-bold normalization, safe HTML treatment, malformed/corrupted text rejection, unsupported numerical evidence rejection, provider failures, and final-content extraction. The earlier diagnostic fixture run passed 33/33; the follow-up focused chat suite passed 14/14 and the focused frontend diagnostic suite passed 11/11. The production build passed.

The first post-fix live attempt still returned HTTP 502 at grounding, which confirmed the previous false-positive fix did not explain every upstream response. A later bounded live request in the current server log returned AMD HTTP 200 with `finish_reason=stop`, non-empty string content of approximately 872 characters, and then passed normalization, grounding, `DiagnosticChatResponse` construction, and the FastAPI route with HTTP 200 in approximately 9.9 seconds. This proves a complete live backend chat response can now pass; browser DOM rendering of that exact successful response was not independently captured.

### Numerical evidence gate — FALSE POSITIVE FIXED / LIVE ANSWER STILL BLOCKED

The reported qualitative failure was reproducible with the controlled response `1. Inspect the bearings.\n2. Check alignment and lubrication.`. The first failing value was the ordered-list marker `1`, which the previous validator compared as if it were a telemetry claim. The same false positive affected ordinary metadata numbers such as `pump-01`, ISO timestamps, and numeric fault identifiers.

The validator now classifies numeric tokens before grounding them. It ignores only ordered-list markers, ISO timestamp components, and digits embedded in identifiers. Standalone measurements remain grounded against the matching authoritative metric family, with bounded decimal rounding accepted; unsupported measurements, thresholds, durations, percentages, and sample counts remain rejected. The AMD prompt explicitly permits qualitative inspection recommendations and identifies list numbering as formatting rather than evidence.

Regression coverage now includes qualitative recommendations, numbered recommendations, exact and rounded telemetry values, unsupported measurements/thresholds/sample counts, identifiers/timestamps/fault names, and existing empty/malformed/truncated provider responses.

The first bounded live request after the fix reached AMD HTTP 200 with `finish_reason=stop`, non-empty text of approximately 965 characters, and passed provider content extraction, but returned PumpGuard HTTP 502 at numerical grounding. The raw upstream text was not recorded, so the exact unsupported token from that response is intentionally unknown. A subsequent bounded live response was observed passing grounding and final result construction; its sanitized metadata was HTTP 200, `finish_reason=stop`, non-empty content of approximately 872 characters, and approximately 9.9 seconds end-to-end. The earlier rejection therefore remains reproducible as an upstream-response-specific grounding rejection, but its exact token is not known because the raw text was not retained.

For this follow-up verification, the new bounded grounding diagnostic logs only the rejected token, a maximum 96-character normalized excerpt, metric family, and rejection category. Focused frontend diagnostic tests passed 11/11. The full frontend run attempted 88 tests but had four unrelated pre-existing `App.test.tsx` timing/state failures; no App or UI source was changed in this pass. The production build still passed.

### Optional AI engineering tools — IMPLEMENTED / AMD LIVE SUCCESS NOT VERIFIED

The maintenance planner, telemetry explanation, and scenario analyst are now exposed through one bounded `POST /api/v1/diagnostics/ai-feature` layer over the existing deterministic telemetry analysis. The route accepts only a pump ID, feature kind, and optional live-session ID; it reconstructs recent telemetry, the rule assessment, deterministic trends, and the recorded simulator snapshot on the backend. The browser never supplies evidence, and no feature runs before a generated telemetry context exists.

The panel reuses the safe React Markdown subset used by DiagnosticChat. It labels provider output as a draft, keeps the rule engine authoritative, distinguishes synthetic simulator records from physical evidence, and exposes provider failure with retry rather than substituting a plan or diagnosis. Fixture coverage covers all three features, live-session snapshot context, unknown/extra input, and timeout failure while the rule assessment remains unchanged.

The bounded live AMD check did not produce a complete AI feature response: the provider transport returned HTTP 200 and content, but the content-quality/grounding gate rejected the upstream corrupted response and the API returned HTTP 502. The feature layer is therefore verified by mocked fixtures and strict failure isolation, not by a live AMD result.

## Simulation and ML report

Simulation behavior was exercised through batch and live endpoints for normal, overheating, bearing wear, cavitation, and imbalance paths via the automated suite, plus overheating in the browser. Values stayed within Pydantic schema bounds, scenario-specific signatures appeared, state progressed, reset/seed behavior was tested, and history is bounded by a configurable deque.

The simulator is physically inspired synthetic logic, not a validated digital twin. It uses hand-authored offsets/noise and does not establish physical causality or field performance. The system correctly distinguishes scenario labels, rule-based health assessment, and optional ML scenario classification.

The offline MLP artifact loads on CPU in the final environment. The API’s production health engine does not depend on the MLP; the MLP is used by optional diagnostic inference/offline experimentation. No AMD ROCm GPU was visible, and no cloud or GPU benchmark was run.

## Security and reliability report

Positive evidence:

- `.env` is ignored and credentials are not returned in diagnostic status or settings representations.
- AMD credentials remain backend-only.
- Request models forbid unexpected fields on simulation controls.
- Diagnostic request size is capped at 32 KiB; provider output is bounded and validated.
- Provider errors are categorized without logging raw exception text or secrets.
- Telemetry history, session count, diagnostic cache, and event lists are bounded.
- `pip check` passed; npm production dependency audit reported zero high-or-higher vulnerabilities.

Limitations:

- This is a local development service with no authentication or authorization boundary. That is acceptable for the documented local demo but not a production deployment control.
- No database, persistence, retention job, readiness probe, or multi-process state coordination exists. History disappears on restart and state is process-local.
- No dedicated Python lint/type-check configuration exists.
- No uncontrolled load test was run. A bounded local rapid-request check was used only to expose timestamp behavior.
- Three.js chunk size remains above Vite’s 500 kB advisory threshold.

## Final readiness assessment

### Latest live diagnostic-chat grounding check

The exact question `How has the pump condition changed?` was run once against a fresh current-code synthetic session on a temporary current-code API instance. AMD returned HTTP 200 with `finish_reason=stop` and non-empty content of approximately 970 characters; PumpGuard completed normalization, grounding, result construction, and API serialization with HTTP 200 in approximately 12.6 seconds. No sanitized grounding rejection was emitted for that response.

The regression fixture now covers the same question with grounded trend values and separately rejects an unsupported `37.5%` change claim, logging only the token, bounded excerpt, metric family, and rejection reason. Therefore the reported live failure was not reproducible in this bounded run; the validator remains strict and will reject a genuinely unsupported numeric claim rather than silently stripping it.

The exact condition-change failure was reproduced once against the current local server. AMD returned HTTP 200, `finish_reason=stop`, and non-empty content, but the model included a display-only time range such as `19:17:05 to 19:17:16 UTC`. The grounding regex extracted `19`, `17`, and `16` as numerical evidence and rejected them as unsupported. The fix recognizes time-only `HH:MM:SS` timestamps as metadata, matching the existing ISO-timestamp exclusion, and adds a regression test covering both forms. A fresh live request after the fix returned HTTP 200 through the complete chat pipeline in approximately 11.7 seconds.

Latest verification after this regression: backend **144 passed** with one existing deprecation warning; focused diagnostic/chat/AI tests **44 passed**; frontend **88 passed**; and the production build passed. No AMD model, timeout, or provider setting changed.

| Area | Status | Rationale |
|---|---|---|
| Backend | PASS | Health, routes, validation, deterministic assessments, diagnostics/chat/AI-feature error mapping, and final 143-test suite pass. In-memory/local-only limitations remain. |
| Frontend | PASS | 88 tests passed across 11 files in five consecutive complete runs; focused diagnostic tests passed 11/11. Production build passed and the real page rendered live data plus chat UI. |
| Browser interactions | PARTIAL | Key live interactions verified, console clean; audio hardware, exhaustive responsive matrix, and all scenarios were not manually re-run in this audit. |
| Simulation | PASS | Scenario signatures, bounds, progression, reset/seed behavior, bounded history, and monotonic timestamp fix verified. Synthetic-only claim applies. |
| ML | PARTIAL | CPU artifact and tests pass in final run, but no AMD GPU/ROCm validation and no real-world predictive claim is supported. |
| AMD catalog | PASS | Live configured endpoint returned HTTP 200 and 12 models in about 1.75 s. |
| AMD inference/chat | PARTIAL | Structured diagnostic requests still hit truncation, schema, timeout, or upstream-502 outcomes. The chat endpoint has mocked coverage and one observed live backend response that passed content extraction, grounding, result construction, and FastAPI serialization; exact frontend rendering of that response was not captured. |
| Security | PARTIAL | Defensive input/secret/error controls are present; no production auth boundary and no full external penetration test were in scope. |
| Production build | PASS | `npm run build` passed; Three.js chunk advisory remains. |

## Prioritized remediation plan

Fix now:

1. Obtain a provider-side explanation or a compatible AMD model/output configuration for the observed corrupted-token responses; PumpGuard now classifies and isolates them without weakening validation.
2. Recreate/verify the optional PyTorch environment in CI so the transient `torch._dynamo` failure cannot recur silently.
3. Define production deployment controls: authentication, authorization, CORS policy, readiness checks, and persistence/retention requirements.

Fix next:

1. Add a browser E2E smoke test for Generate → live polling → pause/stop → alert acknowledgement.
2. Add a bounded local soak test that reports request counts, rejected stale samples, history size, and memory over a fixed duration.
3. Add Python lint/type checks and a dependency-integrity check for optional ML packages.

Defer:

1. Three.js code splitting/bundle optimization until deployment performance targets require it.
2. Real equipment calibration, representative datasets, field validation, and causal fault validation until governed industrial data and acceptance criteria exist.
3. AMD GPU benchmarking until a compatible ROCm AMD environment is available.

## Changed files and final Git state

Audit-session changes were limited to the following files:

- `src/pumpguard/simulator/engine.py` — strict monotonicity for automatic live timestamps.
- `tests/test_live_simulation.py` — regression coverage for rapid live samples.
- `apps/web/src/DiagnosticExplorer.tsx` — distinguishes catalog verification from inference verification.
- `apps/web/src/App.test.tsx` — refreshes synthetic timestamps per test to prevent stale-fixture order dependence.
- `src/pumpguard/services/diagnostics/providers.py` — sanitized AMD stage logging including request model/path/limits/timeouts, truncation classification, and concise literal output contract.
- `src/pumpguard/services/diagnostics/service.py` — sanitized Pydantic/grounding/result stage logging and telemetry metric-association validation.
- `tests/test_diagnostics.py` — regression coverage for the observed OpenAI-compatible envelope, truncation, non-terminal finish reasons, and strict metric associations.
- `README.md` — corrected stale verification/control claims and documented current AMD verification limits.
- `PUMPGUARD_AUDIT_REPORT.md` — consolidated audit evidence and current results.

The current feature also adds `apps/web/src/DiagnosticChat.tsx` and its tests, typed chat API support in `apps/web/src/api.ts`, app/styles integration, `src/pumpguard/models/diagnostic_chat.py`, `src/pumpguard/api/routes/diagnostic_chat.py`, `src/pumpguard/services/diagnostics/chat.py`, and `tests/test_diagnostic_chat.py`; `app.py` and `providers.py` register and implement the mock/AMD adapters.

The optional AI engineering tools add `src/pumpguard/models/ai_feature.py`, `src/pumpguard/api/routes/ai_features.py`, `apps/web/src/AiFeaturePanel.tsx`, and `tests/test_ai_features.py`; `src/pumpguard/api/app.py`, `apps/web/src/App.tsx`, `apps/web/src/api.ts`, and `apps/web/src/styles.css` provide the route and UI integration. The chat adapter also rejects the exact observed corrupted tokens (`thresholdaine`, `bandsaine`, and `secondstons`) while preserving strict validation.

The repository has no commits yet on branch `master`; no commit, push, deployment, reset, cleanup, or history rewrite was performed. The working tree also contains pre-existing staged and untracked project files outside this audit-session change list; they were preserved untouched. No credentials, `.env` files, generated model artifacts, or local logs were added to the audit changes.

## Structured AMD timeout isolation — 2026-10-15

A fresh bounded comparison used the configured `DeepSeek-V4-Flash` model and the configured AMD endpoint without printing credentials or telemetry. The minimal text completion returned HTTP 200 with `finish_reason=stop`, 3-character content, usage metadata, and approximately 3.19 seconds elapsed. The actual PumpGuard structured request used the existing compact evidence payload, `response_format=json_object` when advertised, `max_tokens=700`, zero SDK retries, a 3-second connect timeout, and a 45-second provider response timeout inside the 50-second application deadline. It returned no HTTP status or body and was classified as `ProviderTimedOut` after approximately 46.19 seconds.

The timeout occurred before response extraction, JSON parsing, Pydantic validation, evidence grounding, `DiagnosticResult` construction, FastAPI serialization, or frontend rendering. Existing sanitized provider logging records the request path, model, generation limit, response-format mode, timeout values, retry count, elapsed time, and timeout stage. The existing regression test confirms one SDK attempt and safe 504 mapping. No application-side defect was demonstrated, so no speculative timeout, prompt, model, provider, or validation change was made. Rule-based assessment remains independent and available. The remaining blocker is upstream structured-generation latency/availability for this model; a real structured `DiagnosticResult` was not produced in this bounded verification.

## Isolated AMD structured-generation experiment — 2026-10-15

Using the same endpoint, model, SDK, 45-second provider timeout, zero retries, and no production changes:

| Case | Request mode | Result |
|---|---|---|
| A | Plain text, 64-token cap | HTTP 200, `stop`, 2-character content, 2.06 s |
| B | JSON instruction only, 64-token cap | HTTP 200, `stop`, valid JSON, 15 characters, 1.22 s |
| C | Same JSON prompt plus catalog-advertised `response_format=json_object` | HTTP 200, `stop`, valid JSON, 15 characters, 1.40 s |
| D | Compact synthetic diagnostic, JSON mode, 128-token cap | HTTP 200, `stop`, valid JSON, 535 characters, 5.77 s |
| E-1 | Existing full PumpGuard request through the production provider adapter | Parsed JSON, 1,618 serialized characters, 20.07 s |
| E-2 | Same existing full request, repeated once after the differing outcome | Parsed JSON, 1,408 serialized characters, 18.81 s; Pydantic rejected it because two evidence `metric` values were outside the allowed enum and `priority` was missing |

The earlier bounded E attempt timed out at approximately 46.19 seconds with no HTTP response. Therefore the full request is reproducibly variable across timeout, provider JSON response, and schema-invalid response outcomes. A/B/C show that basic JSON prompting and the catalog-advertised JSON mode work for tiny requests; D shows compact diagnostic JSON can also complete. The evidence does not justify blaming the SDK or `response_format` alone, nor weakening strict schema validation. No production code, timeout budget, model, provider, credentials, or frontend code was changed. The remaining issue is upstream workload-dependent latency and contract adherence; no complete live `DiagnosticResult` was produced in these E attempts.

## Structured schema-contract correction — 2026-10-15

The provider contract was tightened without changing validation: the AMD prompt now gives the exact canonical metric identifiers, explicitly forbids shortened metric names, requires `priority` and its allowed values, states when `metric` must be omitted, and includes a literal valid JSON shape. A regression test verifies that this contract is sent and that an AMD response with a shortened metric or missing priority is rejected rather than coerced.

Post-change live verification reached AMD and returned parseable JSON in 26.35 seconds, but the complete PumpGuard pipeline rejected it at evidence grounding because the model placed measured numbers in prose fields instead of structured evidence. This is an upstream response-contract violation, not a successful diagnostic. Strict validation and rule-based fallback remain intact. A complete live `DiagnosticResult` is still not verified; upstream timeout and contract-adherence variability remain limitations.

The subsequent bounded live check after the grounding correction returned parseable AMD JSON in 30.23 seconds and passed Pydantic validation. It then failed at evidence-to-context matching with `ProviderInvalidResponse: Diagnostic evidence does not match supplied evidence`. No raw model response or sensitive telemetry was recorded, so the specific mismatched reference/value cannot be identified from this run. This confirms the live model still violates the trusted evidence-reference contract; the application correctly rejects it rather than fabricating or coercing a diagnosis.

## Diagnostic chat grounding verification — 2026-10-15

The chat path uses its own `_validate_numeric_grounding()` implementation and does not share the structured `DiagnosticService` grounding validator. Controlled coverage confirms qualitative inspection recommendations, numbered lists, timestamps, identifiers, exact/rounded supported values, unsupported measurements, and mixed supported/unsupported claims. A bounded live request for `What should an engineer inspect first?` returned AMD HTTP 200 with `finish_reason=stop`, non-empty content of approximately 910 characters, and completed chat normalization, numeric grounding, result construction, and API serialization with HTTP 200 in approximately 10.3 seconds. The prior 502 therefore corresponded to an AMD response-specific unsupported numeric claim, not the question itself; genuinely unsupported claims remain rejected.

Latest verification after the mixed-claim regression: diagnostic/structured tests **43 passed**, full backend **147 passed**, frontend **88 passed**, production build passed, `pip check` passed, and `git diff --check` reported no whitespace errors.

## Running UI reproduction and threshold grounding correction — 2026-10-15

The failure was reproduced through the running dashboard, not only through isolated tests. The browser generated synthetic telemetry, submitted the suggested question `What should an engineer inspect first?`, and displayed `Diagnostic chat returned unsupported numerical evidence`. The initial port inspection also found a stale global-Python Uvicorn process on port 8001 while a duplicate virtual-environment process was not listening. Only the PumpGuard backend processes were stopped and the current virtual-environment backend was restarted. The same failure reproduced against the current code, proving the process mismatch was a verification-environment issue but not the root cause.

Sanitized logs from the current backend showed AMD HTTP 200, `finish_reason=stop`, non-empty string content, and rejection of authoritative values `85` (temperature) and `4.5` (vibration). The validator classified both as outside the allowed metric-family values. The defect was in `_numeric_values()`: while recursively inspecting a metric's nested `threshold` object, it replaced the enclosing metric family with the child key `threshold`, so valid threshold values were collected as `general` rather than as temperature/vibration evidence. The correction preserves the enclosing metric family during nested traversal. No validation was weakened, and unsupported numeric claims remain rejected.

A focused regression test now covers authoritative temperature and vibration threshold values in prose. After restarting the current backend, the browser repeated the same synthetic-telemetry flow successfully: AMD HTTP 200, `finish_reason=stop`, non-empty content, valid chat result construction, and `/api/v1/diagnostics/chat` HTTP 200. The assistant response rendered in the dashboard without the grounding error. The successful live answer is grounded in synthetic simulator telemetry and is not a real-world equipment diagnosis.

Final verification after this correction: focused diagnostic tests **44 passed**, full backend **148 passed**, frontend **88 passed**, production build passed, `pip check` passed, and `git diff --check` reported no whitespace errors. The final backend log recorded valid final content and valid result construction in approximately **13.3 seconds**. AMD structured diagnostic variability and unrelated upstream contract/timeouts documented above remain separate limitations; this specific chat false positive is fixed and verified through the running UI.

## AI Interpretation UI reproduction and context correction — 2026-10-15

The browser reproduction targeted the **Draft maintenance plan** action in the AI Interpretation panel. It uses `POST /api/v1/diagnostics/ai-feature`, not the separate `/api/v1/diagnostics/chat` textbox endpoint. Before the correction, AMD returned HTTP 200 and readable text, but the backend returned HTTP 502 after the chat grounding stage. Sanitized rejection logs identified provider prose containing configured rule values such as `85 °C`, `4.5 mm/s`, and `1650–1900 rpm`. These values were valid rule-engine thresholds, but the AI-feature context contained telemetry, assessment, deterministic analysis, and simulator state without the authoritative threshold definitions. The validator therefore correctly rejected them as absent from supplied evidence.

The fix adds the server-owned `DEFAULT_THRESHOLDS` to both AI chat contexts (`/diagnostics/chat` and `/diagnostics/ai-feature`) and documents that they are authoritative rule definitions. A second focused defect found by the regression test was nearest-metric association: a wide text window could classify `85 °C` as vibration when followed by `vibration 4.5 mm/s`. `_claim_family()` now associates a number with the nearest unit or metric marker, preserving strict family-aware grounding. Unsupported values such as an AMD-generated RPM value outside the supplied telemetry still remain rejected; this is intentional and is not silently coerced.

After restarting only the current virtual-environment PumpGuard backend, the same browser action completed successfully: AMD HTTP 200, `finish_reason=stop`, non-empty content, grounding passed, `/api/v1/diagnostics/ai-feature` returned HTTP 200, and the rendered Draft maintenance plan appeared in the UI. One later live AMD response also generated an RPM value not present in the bounded authoritative context and was correctly rejected with HTTP 502, demonstrating that strict protection remains active for genuinely unsupported provider claims.

Final verification for this change: AI/chat-focused backend tests **23 passed**, full backend **150 passed**, frontend **88 passed**, production build passed, `pip check` passed, and `git diff --check` passed. No provider, model, credentials, timeout, retry policy, or unrelated UI behavior was changed.

The separate browser Diagnostic Assistant was also exercised after the AI-feature verification. Its request reached the independent `/api/v1/diagnostics/chat` pipeline, but this particular AMD response was rejected at text normalization as malformed/unsupported provider text. That remains a provider-output quality failure, not evidence that the AI Interpretation threshold-context fix failed; the rule-based assessment and AI-feature result remained intact.

## Intermittent AMD grounding retry — 2026-10-15

A subsequent browser retry reproduced the AI Interpretation error with a different sanitized rejection: AMD returned HTTP 200, `finish_reason=stop`, non-empty content, then cited RPM `1769` in prose even though that exact value was not present in the bounded authoritative context. PumpGuard returned HTTP 502 at numeric grounding. This is a genuine provider evidence violation, not a validator false positive or frontend state bug; accepting it would weaken factual grounding. The shared AMD instruction was strengthened to prohibit estimating, interpolating, rounding unseen values, or using remembered setpoints and to omit unavailable numbers. The retry remains safely rejected when AMD violates that contract.

The AI Interpretation controls are separate DOM buttons; the apparent concatenation in extracted page text is not a single malformed control. The rendered panel keeps the three actions distinct, and successful AMD results render as separate formatted content. Final backend verification after the prompt change: **151 passed**, focused AI/chat tests **24 passed**, and `git diff --check` passed. The previously verified frontend **88 passed**, production build, and `pip check` remain unchanged by this backend-only prompt update.

## AMD normalization and three-action UI verification — 2026-10-15

The existing `_strip_code_fence()` helper already normalizes exactly one complete Markdown JSON fence before `json.loads()` on the structured `/api/v1/diagnostics` path. It is covered by a direct helper test and an end-to-end mocked fenced-response test. The three AI Interpretation actions do not use that JSON parser: all three call `/api/v1/diagnostics/ai-feature`, sharing the plain-text AMD adapter, normalization, and numeric-grounding path. Markdown-fenced JSON was therefore not the cause of the observed AI Interpretation error.

The live UI was operated against the restarted current virtual-environment backend. Draft maintenance plan produced a rendered AMD result once. Explain telemetry trends reached AMD HTTP 200 with `finish_reason=stop` and non-empty content, then grounding rejected `4.5` as a sound-family value not present in authoritative context. Analyze active scenario reached AMD HTTP 200 with non-empty content but was rejected by the malformed/unsupported text gate. A later Draft maintenance plan retry also reached AMD HTTP 200 and was correctly rejected for unsupported temperature values `30` and `60` in a forecast sentence. These are provider contract violations, not reasons to weaken grounding.

One confirmed application defect was found in the shared text normalizer: `_GLUED_UNIT_PATTERN` has no capture group, but the replacement used `\\g<1>`, causing `re.error: invalid group reference 1` and conversion to a generic provider failure whenever normalization ran. The minimal fix uses the complete match (`\\g<0>`) and removes a broad digit/letter spacing substitution that had corrupted ISO timestamps before grounding could recognize them. Existing corruption checks and strict numeric grounding remain active. A regression test covers glued-unit normalization.

A bounded one-request-per-model comparison with identical synthetic context and the same qualitative prompt completed for DeepSeek-V4-Flash, DeepSeek-V4.1-Flash, and Gemma-4-31B-IT. All three reached AMD but their returned text failed PumpGuard content/grounding validation; no production model was changed. No raw response, credentials, authorization headers, or telemetry payloads were recorded.

Final verification after the correction: focused AI/chat tests **25 passed**, full backend **152 passed**, frontend **88 passed**, production build passed, virtual-environment `pip check` passed, and `git diff --check` passed. The running UI uses the corrected backend; valid provider output can pass normalization, while current live AMD responses with unsupported values still receive safe rejection. A complete successful Draft maintenance plan was observed before the latest retry, but AMD output remains variable and strict grounding intentionally rejects unsupported claims.

## Final AI-feature grounding correction — 2026-10-15

The final three-action browser run used the current reloaded backend and made one request for each action. All three reached AMD with HTTP 200, `finish_reason=stop`, and non-empty text, but all three were rejected safely by PumpGuard grounding. Sanitized examples included an unsupported forecast duration, a sample-window count, an untyped cooling-efficiency value, and an inferred RPM/health value. No raw model text or credentials were recorded. The UI displayed the rejection and did not render an unvalidated draft.

The confirmed application-side defect was family association: `_claim_family()` chose a nearby unrelated unit or metric from later prose. The correction adds the server-owned `flow` family, explicitly includes trusted `sample_count` in both AI contexts, recognizes general context labels such as samples, health score, and cooling effectiveness, and prioritizes adjacent units followed by preceding labels over distant markers. Regression tests cover these exact associations. Strict rejection remains unchanged for values absent from the authoritative context.

Final verification: focused AI/chat tests **27 passed**, full backend **154 passed**, frontend **88 passed**, production build passed, virtual-environment `pip check` passed, and `git diff --check` passed. The live UI was operated and all three actions were tested. A valid grounded AMD draft was not reproduced in this final three-request sample; AMD’s variable unsupported output remains the external limitation. The rule-based assessment and synthetic telemetry remain authoritative and operational.

## Live-browser follow-up and snapshot consistency — 2026-10-15

The exact local reproduction was `POST /api/v1/diagnostics/ai-feature`. A bounded direct request returned HTTP **502** with the sanitized body `{"detail":"Diagnostic chat returned unsupported numerical evidence"}`. Backend logs showed AMD HTTP 200, `finish_reason=stop`, non-empty content, followed by grounding rejection; this was not an AMD transport failure or a favicon failure. The rejected claims were provider-generated numerical rates/ranges such as `1650–1900` being incorrectly associated with temperature, and later derived rates such as `0.088`, `0.008`, and `0.039` that were not present in authoritative context.

The confirmed validator defect was distant metric association: a metric marker appearing later in prose could classify an otherwise untyped number as the wrong family. The correction rejects distant family association, prefers adjacent units and preceding labels, and retains the requirement that untyped claims match a server-owned value somewhere in context. A trusted `sample_count` and flow family remain explicit. No arbitrary numbers are accepted and no validation is bypassed.

The normal/100 versus critical/65 discrepancy was not reproduced in the final run. The successful AI response now exposes the exact `evidence_timestamp` used by the backend, and the UI displays it beside the result. The frontend also discards an older in-flight response when the simulation context changes, preventing stale results from overwriting a newer context. In the final browser run, Draft maintenance plan and Analyze active scenario rendered successfully, with evidence timestamps matching the displayed normal/100 dashboard state. Explain telemetry trends was safely rejected for unsupported derived rates. The favicon 404 was not involved in any AI request.

Final verification after this follow-up: focused AI/chat tests **28 passed**, full backend **155 passed**, frontend **89 passed**, production build passed, virtual-environment `pip check` passed, and `git diff --check` passed. No credentials, provider/model settings, commits, pushes, deployments, resets, or unrelated changes were made. AMD output variability and occasional timeouts remain external limitations; successful grounded output is demonstrated but not guaranteed for every request.
