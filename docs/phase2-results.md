# PumpGuard ACTIII Phase 2 — Results

## Delivered

- Added a backend-only diagnostic provider protocol, deterministic offline mock (success and four failure modes), an explicitly unavailable AMD Token Factory placeholder, and one provider-selecting service layer.
- Added bounded, validated request/response contracts, evidence-pointer verification against submitted data, numeric-claim rejection in prose, request/response size caps, timeouts, correlation IDs, safe logging, bounded episode deduplication/cache, and one conditional rate-limit retry only when an adapter marks replay safe.
- Added explicit operator-triggered diagnostic requests from the existing inspector. Provider status, mock labeling, cached state, latency, qualitative uncertainty, evidence, evidence gaps, inspection steps and retry/error state are displayed without altering deterministic alerts or detector output.
- Added server-only placeholder configuration. The application starts without AMD credentials. No actual AMD endpoint/model/auth protocol is assumed or called.

## Files changed

- `src/pumpguard/models/diagnostic.py` — bounded diagnostic request, evidence reference, hypothesis, response, and result schemas.
- `src/pumpguard/services/diagnostics/__init__.py`, `providers.py`, `service.py`, `instructions.py` — provider interface, mock and AMD placeholder, inference orchestration/deduplication, and grounding policy.
- `src/pumpguard/config.py`, `.env.example` — server-side provider selection, mock mode, connect/response timeout and placeholder settings.
- `src/pumpguard/api/app.py`, `src/pumpguard/api/routes/diagnostics.py` — service selection and diagnostic/status endpoints.
- `apps/web/src/api.ts`, `apps/web/src/App.tsx`, `apps/web/src/DiagnosticExplorer.tsx`, `apps/web/src/styles.css` — bounded explicit request construction and inspector UI.
- `tests/test_diagnostics.py` — schema bounds, mock, provider selection/failures, timeout/rate-limit, deduplication, evidence grounding, credential-safe settings and alarm isolation.
- `apps/web/src/App.test.tsx` — mock result rendering, bounded request content and alert persistence on provider failure.
- `docs/phase2-ai-infrastructure.md` — provider contract, limits and verified AMD documentation requirements.
- `docs/phase2-results.md` — this report.

## Verification

Commands run:

| Command | Result |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q` (project root) | **80 passed**; one existing Starlette/httpx deprecation warning. |
| `npm test -- --run` (`apps/web`) | **74 passed** across 9 test files. |
| `npm run build` (`apps/web`) | **Passed**, including `tsc -b` and Vite production build. |

The Vite build retains its advisory for the lazy Three.js bundle (567.97 kB minified, 142.14 kB gzip). Backend tests exercise the diagnostic endpoint through FastAPI's test client. Frontend tests verify explicit request construction, mock labeling and alert preservation after provider failure. No manual browser or authenticated AMD inference was performed.

## Unresolved / intentionally unavailable

- The official AMD Token Factory endpoint, model ID, credential flow, request/response schema, limits, retry/idempotency semantics, regions and data-retention terms are not verified. The AMD provider therefore returns an explicit unavailable response.
- The configured connect timeout and output limit are part of the future adapter contract; no network transport exists to exercise them yet. A future streaming adapter must enforce output-byte limits while reading and implement separate connect/read timeouts according to official instructions.
- Deduplication and cached explanations are process-local, bounded to 128 episodes, and reset when the backend restarts.
- Diagnostic text is advisory. Mock results are not model results, qualitative uncertainty is not calibrated confidence, and synthetic evidence does not establish real-world fault diagnosis.
