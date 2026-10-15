# PumpGuard ACTIII Phase 2 — AI diagnostic infrastructure

## Boundary and current provider state

The optional explanation path is backend-only and separate from the deterministic `assess_reading` rule engine. The default `PUMPGUARD_DIAGNOSTIC_PROVIDER=mock` runs offline. The mock is explicitly identified in API responses and the inspector as **MOCK RESULT · NOT AN AMD MODEL**. `PUMPGUARD_DIAGNOSTIC_PROVIDER=amd` selects an unavailable placeholder; the API starts, reports `amd_unavailable`, and returns HTTP 503 for inference. No AMD request, endpoint, model, or authentication format is implemented or assumed.

The operator explicitly requests a diagnostic from the existing inspector. Telemetry polling never invokes the provider. The request uses a stable active alert episode ID where available; duplicate in-flight requests share one inference, and successful results are cached in a bounded process-local cache (128 episodes). A retry for an already completed episode returns the cached result. Failures are not cached, so the operator may retry. The service does not change telemetry, detector predictions, alerts, siren state, or equipment controls.

## Contracts

Backend contracts are in `src/pumpguard/models/diagnostic.py`:

- Request: pump/session/episode identifiers; assessment time; at most 12 ordered telemetry points; at most five bounded trends; detector status, score, optional confidence and predicted fault names; synthetic/scenario context; optional active alert; at most 16 bounded event markers.
- Response: concise summary; up to five rank-ordered hypotheses; machine-checkable evidence pointers; uncertainty; missing evidence; inspection steps; priority and rationale; limitations; and a required human-review flag.
- Evidence pointers must reference a value that exactly matches the submitted telemetry, trend, detector, alert or event. Numeric measurement claims in provider prose are rejected; measurements must be displayed through verified structured references. Unknown fields, unsupported references, oversized payloads, invalid priorities/ranks, malformed schemas and missing human-review requirements are rejected.
- Requests are streamed with a 32 KiB input cap. The provider result is capped at 32 KiB and individual fields/list counts are bounded. The current frontend submits only a 12-sample recent window, supported trends, detector output, current alert context, and recent simulation events.

`DIAGNOSTIC_INSTRUCTIONS` in `src/pumpguard/services/diagnostics/instructions.py` is the grounding policy for a future text-model adapter: distinguish measurements from hypotheses, state uncertainty and gaps, do not use simulated labels as independent proof, and require human review.

## Provider and configuration contract

`DiagnosticProvider` is the async interface in `src/pumpguard/services/diagnostics/providers.py`; `DiagnosticService` in `src/pumpguard/services/diagnostics/service.py` selects the single service boundary, bounds time and output, validates grounding, correlates/logs calls, and deduplicates episodes. The mock supports `success`, `timeout`, `rate_limit`, `malformed`, and `unavailable` modes for deterministic tests and offline development.

Server-side settings are listed in `.env.example`:

- `PUMPGUARD_DIAGNOSTIC_PROVIDER=mock|amd` selects the provider (defaults to mock so the feature works offline).
- `PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS` bounds the overall response wait (0.05–120 seconds).
- `PUMPGUARD_DIAGNOSTIC_CONNECT_TIMEOUT_SECONDS` reserves a bounded connect timeout for a future transport (0.05–30 seconds).
- `PUMPGUARD_DIAGNOSTIC_MOCK_MODE` selects a mock success or deterministic failure mode.
- `PUMPGUARD_AMD_BASE_URL`, `PUMPGUARD_AMD_MODEL`, and `PUMPGUARD_AMD_CREDENTIAL` are internal placeholder configuration names only; they are not verified AMD environment variable names. Credentials are never passed to the frontend or included in logs. The placeholder discards the credential and makes no network call.

An adapter can retry a rate-limited inference once only when its verified response contract marks replay safe and supplies a retry delay; the delay is clamped to one second and remains within the overall timeout. The current mock rate-limit mode is deterministic and non-retryable. The placeholder makes no network calls. No automatic retry is enabled based on guessed AMD behavior.

## AMD information still required

Before implementing the real provider, obtain the official AMD Token Factory documentation and verify all of the following:

1. Canonical service/base URL, API version, required TLS/network constraints, and supported regions.
2. Exact model identifier and availability/lifecycle policy.
3. Credential issuance, scope, expiry/refresh, and exact authorization mechanism/header. Do not assume a Bearer token or OpenAI-compatible API.
4. Request envelope, supported structured-output/schema mode, message roles, content-type, and response/error envelope.
5. Input context and output limits, token accounting, and how to enforce a streaming response-byte cap.
6. Connect/read timeout guidance and cancellation behavior.
7. Rate-limit signals, `Retry-After` or equivalent, idempotency/replay behavior, and whether retrying a request can incur duplicate charges.
8. Data retention, logging, privacy, and whether synthetic telemetry may be sent to the service.

Until those points are verified, the “AMD” selection is deliberately unavailable. No AMD integration, authenticated inference, accuracy, or production safety claim is made.

## Operational limitations

- Provider output is advisory and not a failure probability. Hypothesis uncertainty is a qualitative label, not calibrated confidence.
- Mock output is deterministic scaffolding, not a language-model response.
- Cache/deduplication is process-local and resets when the backend restarts. There is no persistent diagnosis history.
- The existing sensor streams and fault labels are synthetic. A selected/injected scenario is not independent evidence of a real equipment fault.
- The inspector keeps the original detector evidence and alarm actions authoritative. A provider timeout, rate limit, unavailable state, or malformed response cannot suppress warning/critical alarms or siren behavior.
