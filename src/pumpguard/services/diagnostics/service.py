"""Timeout-bounded inference orchestration with process-local episode deduplication."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import logging
import math
import re
import time
import uuid

from pydantic import ValidationError
from pydantic import BaseModel

from pumpguard.models.diagnostic import DiagnosticContent, DiagnosticRequest, DiagnosticResult, DiagnosticTrend
from pumpguard.services.diagnostics.providers import (
    DiagnosticProvider, ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut, ProviderUnavailable, ProviderUnsupportedModel,
)

logger = logging.getLogger(__name__)

_PROSE_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z])")
_PROSE_TIMESTAMP_PATTERN = re.compile(
    r"(?:\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    r"|\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b)"
)
_PROSE_TREND_PAIR_PATTERN = re.compile(
    r"(?:\bfrom\s+)?(?P<first>[-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
    r"(?P<unit1>°\s*C|mm\s*/\s*s|dB|rpm|kPa|%)?\s*(?:to|→)\s*"
    r"(?P<latest>[-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
    r"(?P<unit2>°\s*C|mm\s*/\s*s|dB|rpm|kPa|%)?",
    re.IGNORECASE,
)


def _prose_number_is_metadata(text: str, match: re.Match[str], timestamp_spans: list[tuple[int, int]]) -> bool:
    start, end = match.span()
    if any(begin <= start and end <= finish for begin, finish in timestamp_spans):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    if re.match(r"\s*\d+[.)]\s+", text[line_start:]):
        return True
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    if before.isalpha() or after.isalpha():
        return True
    if before == "-" and start > 1 and (text[start - 2].isalnum() or text[start - 2] in "_-"):
        return True
    if after == "-" and end + 1 < len(text) and (text[end + 1].isalnum() or text[end + 1] in "_-"):
        return True
    return False


def _diagnostic_metric_family(value: object) -> str | None:
    name = str(value).lower()
    families = _diagnostic_metric_families(name)
    return next(iter(families), None)


def _diagnostic_metric_families(value: object) -> set[str]:
    name = str(value).lower()
    matches: set[str] = set()
    for family, terms in {
        "temperature": ("temperature", "°c", "celsius"),
        "vibration": ("vibration", "mm/s"),
        "sound": ("sound", "db", "decibel"),
        "rpm": ("rpm", "rotational"),
        "pressure": ("pressure", "kpa"),
        "percent": ("percent", "%"),
        "score": ("health_score", "health score", "score"),
        "confidence": ("confidence",),
    }.items():
        if any(term in name for term in terms):
            matches.add(family)
    return matches


def _grounded_prose_number(claim: float, token: str, claim_family: str | None,
                           evidence_values: list[tuple[float, str | None]]) -> bool:
    decimals = len(token.lstrip("+-").split(".", 1)[1]) if "." in token else 0
    tolerance = max(1e-9, 0.5 * (10 ** -decimals))
    return any(
        claim_family == family
        and math.isclose(claim, value, rel_tol=0, abs_tol=tolerance)
        for value, family in evidence_values
    )


def _prose_claim_role(text: str, match: re.Match[str]) -> str:
    """Infer a numeric claim's statistic role from its local clause."""
    start, end = match.span()
    boundaries = list(re.finditer(r"[.!?;\n]", text[:start]))
    clause_start = boundaries[-1].end() if boundaries else 0
    boundary = re.search(r"[.!?;\n]", text[end:])
    clause_end = end + boundary.start() if boundary else len(text)
    clause = text[clause_start:clause_end]
    roles = (
        (r"\b(?:threshold|limit|expected\s+range|normal\s+range)\b", "threshold"),
        (r"\b(?:mean|average|avg)\b", "mean"),
        (r"\b(?:minimum|min|lowest)\b", "minimum"),
        (r"\b(?:maximum|max|peak|highest)\b", "maximum"),
        (r"\b(?:sample|reading|measurement)\s+count\b|\bcount\s+of\s+(?:samples?|readings?|measurements?)\b|\bnumber\s+of\s+(?:samples?|readings?|measurements?)\b|\b\d+\s+(?:[\w-]+\s+){0,2}(?:samples?|readings?|measurements?)\b", "samples"),
        (r"\b(?:elapsed|duration|across)\b", "duration"),
        (r"\b(?:delta|change)\s*:?\s*(?:by|of)?\b|\b(?:increased|decreased|rose|dropped|fell)\s+(?:by|of)\b", "delta"),
        (r"\b(?:initial|first|starting|began|started)\b", "first"),
        (r"\b(?:warning|critical|alert|observed|measured)\s+at\b", "latest"),
        (r"\b(?:latest|current|most\s+recent|observed|measured|now)\b", "latest"),
    )
    candidates: list[tuple[int, int, str]] = []
    local_start, local_end = start - clause_start, end - clause_start
    for priority, (pattern, role) in enumerate(roles):
        for marker in re.finditer(pattern, clause, re.IGNORECASE):
            distance = (local_start - marker.end() if marker.end() <= local_start else
                        marker.start() - local_end if marker.start() >= local_end else 0)
            if distance <= 48:
                candidates.append((distance, priority, role))
    if not candidates:
        return "latest"
    candidates.sort()
    nearest = candidates[0][0]
    nearest_roles = {role for distance, _, role in candidates if distance == nearest}
    return next(iter(nearest_roles)) if len(nearest_roles) == 1 else "ambiguous"


class DiagnosticTimeout(Exception):
    pass


class DiagnosticService:
    """Single service boundary; detector/alert state is never modified here."""
    def __init__(self, provider: DiagnosticProvider, timeout_seconds: float = 8.0, cache_limit: int = 128) -> None:
        if not 0.05 <= timeout_seconds <= 120:
            raise ValueError("diagnostic timeout must be between 0.05 and 120 seconds")
        if cache_limit < 1:
            raise ValueError("cache_limit must be positive")
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.cache_limit = cache_limit
        self._cache: OrderedDict[str, DiagnosticResult] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[DiagnosticResult]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(request: DiagnosticRequest) -> str:
        episode = request.alert_episode_id or (request.alert.episode_id if request.alert else None)
        evidence = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(evidence.encode("utf-8")).hexdigest()[:16]
        return f"{request.pump_id}|{request.client_session_id or 'legacy'}|{episode or request.assessment_timestamp.isoformat()}|{fingerprint}"

    async def diagnose(self, request: DiagnosticRequest) -> DiagnosticResult:
        key = self._key(request)
        async with self._lock:
            # Repeated AMD requests should generate a fresh Token Factory answer;
            # keep the cache only for explicit offline/test providers.
            cached = self._cache.get(key) if self.provider.name != "amd" else None
            if cached:
                self._cache.move_to_end(key)
                return cached.model_copy(update={"cached": True})
            task = self._inflight.get(key)
            is_duplicate = task is not None
            if task is None:
                correlation_id = str(uuid.uuid4())
                task = asyncio.create_task(self._infer_and_cache(key, request, correlation_id))
                self._inflight[key] = task
        result = await asyncio.shield(task)
        return result.model_copy(update={"cached": True}) if is_duplicate else result

    async def _infer_and_cache(self, key: str, request: DiagnosticRequest, correlation_id: str) -> DiagnosticResult:
        started = time.perf_counter()
        try:
            self._validate_request_trends(request)
            # The request telemetry is the authoritative evidence window. Derive
            # provider-facing trend facts here so browser date parsing/rounding can
            # never make a client-computed summary disagree with that window.
            request = request.model_copy(update={"trends": self._calculate_request_trends(request)})
            raw = await asyncio.wait_for(self._call_provider(request), timeout=self.timeout_seconds)
            wire_value = raw.model_dump() if isinstance(raw, BaseModel) else raw
            try:
                if len(json.dumps(wire_value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > 32 * 1024:
                    raise ProviderInvalidResponse("Diagnostic provider response exceeds the 32 KiB limit")
            except (TypeError, ValueError) as exc:
                raise ProviderInvalidResponse("Diagnostic provider response is not valid JSON data") from exc
            try:
                content = DiagnosticContent.model_validate(wire_value)
            except ValidationError as exc:
                logger.warning("diagnostic stage=pydantic_validation outcome=invalid errors=%s",
                               sorted((tuple(error.get("loc", ())), error.get("type", "unknown")) for error in exc.errors()))
                raise ProviderInvalidResponse("Diagnostic provider returned an invalid response") from exc
            logger.info("diagnostic stage=pydantic_validation outcome=valid")
            if self.provider.name == "amd":
                # Demo explanations are model output. Keep the typed response
                # contract, but do not make deterministic rules a display gate.
                logger.info("diagnostic stage=evidence_grounding outcome=skipped provider=amd policy=demo_explanation")
            else:
                try:
                    self._validate_grounding(content, request)
                except ProviderInvalidResponse:
                    logger.warning("diagnostic stage=evidence_grounding outcome=invalid")
                    raise
                logger.info("diagnostic stage=evidence_grounding outcome=valid")
            latency = (time.perf_counter() - started) * 1000
            result = DiagnosticResult.model_validate({**content.model_dump(), "provider": self.provider.name,
                "is_mock": self.provider.name == "mock", "latency_ms": latency, "correlation_id": correlation_id,
                "assessment_timestamp": request.assessment_timestamp, "ml_prediction": request.ml_prediction})
            if self.provider.name != "amd":
                async with self._lock:
                    self._cache[key] = result
                    self._cache.move_to_end(key)
                    while len(self._cache) > self.cache_limit:
                        self._cache.popitem(last=False)
            logger.info("diagnostic stage=result_construction outcome=valid provider=%s latency_ms=%.1f",
                        self.provider.name, latency)
            logger.info("diagnostic completed provider=%s correlation_id=%s latency_ms=%.1f",
                        self.provider.name, correlation_id, latency)
            return result
        except asyncio.TimeoutError as exc:
            logger.warning("diagnostic failed provider=%s correlation_id=%s category=timeout",
                           self.provider.name, correlation_id)
            raise DiagnosticTimeout("Diagnostic inference timed out") from exc
        except (ProviderUnavailable, ProviderRateLimited, ProviderTimedOut, ProviderInvalidResponse, ProviderUnsupportedModel) as exc:
            logger.warning("diagnostic failed provider=%s correlation_id=%s category=%s",
                           self.provider.name, correlation_id, type(exc).__name__)
            raise
        except Exception as exc:
            # Do not log exception text: provider transports can include request headers.
            logger.error("diagnostic failed provider=%s correlation_id=%s category=provider_error",
                         self.provider.name, correlation_id)
            raise ProviderUnavailable("Diagnostic provider request failed") from exc
        finally:
            async with self._lock:
                current = self._inflight.get(key)
                if current is asyncio.current_task():
                    self._inflight.pop(key, None)

    @staticmethod
    def _validate_request_trends(request: DiagnosticRequest) -> None:
        """Require every client-supplied trend to describe this request's telemetry window."""
        seen: set[str] = set()
        for trend in request.trends:
            if trend.metric in seen:
                raise ProviderInvalidResponse("Diagnostic trend contains a duplicate metric")
            seen.add(trend.metric)
            points = [item for item in request.telemetry if getattr(item, trend.metric) is not None]
            if not points:
                raise ProviderInvalidResponse("Diagnostic trend has no matching telemetry evidence")
            first, latest = points[0], points[-1]
            first_value = getattr(first, trend.metric)
            latest_value = getattr(latest, trend.metric)
            expected = {
                "initial_value": first_value,
                "latest_value": latest_value,
                "delta": latest_value - first_value,
                "elapsed_seconds": max(0.0, (latest.timestamp - first.timestamp).total_seconds()),
                "samples": len(points),
            }
            for field, value in expected.items():
                actual = getattr(trend, field)
                # The browser computes elapsed time with Date.parse millisecond
                # precision while Python retains timestamp microseconds. Allow
                # only that sub-millisecond representation difference.
                tolerance = 1e-3 if field == "elapsed_seconds" else 1e-9
                matches = math.isclose(actual, value, rel_tol=1e-9, abs_tol=tolerance) if isinstance(value, float) else actual == value
                if not matches:
                    raise ProviderInvalidResponse("Diagnostic trend does not match its telemetry evidence window")

    @staticmethod
    def _calculate_request_trends(request: DiagnosticRequest) -> list[DiagnosticTrend]:
        """Calculate provider-facing trend facts only from this request's telemetry."""
        trends: list[DiagnosticTrend] = []
        for metric in ("temperature_c", "vibration_mm_s", "sound_db", "rpm", "pressure_kpa"):
            points = [item for item in request.telemetry if getattr(item, metric) is not None]
            if not points:
                continue
            first, latest = points[0], points[-1]
            initial_value = getattr(first, metric)
            latest_value = getattr(latest, metric)
            trends.append(DiagnosticTrend(
                metric=metric,
                initial_value=initial_value,
                latest_value=latest_value,
                delta=latest_value - initial_value,
                elapsed_seconds=max(0.0, (latest.timestamp - first.timestamp).total_seconds()),
                samples=len(points),
            ))
        return trends

    @staticmethod
    def _validate_grounding(content: DiagnosticContent, request: DiagnosticRequest) -> None:
        texts = [content.summary, content.priority_rationale, *content.missing_evidence,
                 *content.inspection_steps, *content.limitations]
        for hypothesis in content.hypotheses:
            texts.extend([hypothesis.cause, *hypothesis.missing_evidence])
        telemetry_fields = {"temperature_c", "vibration_mm_s", "sound_db", "rpm", "pressure_kpa", "load_percent"}
        trend_fields = {"metric", "initial_value", "latest_value", "delta", "elapsed_seconds", "samples"}
        detector_fields = {"status", "score", "predicted_faults", "confidence"}
        alert_fields = {"episode_id", "metric", "severity", "observed_value", "expected_range", "explanation"}
        event_fields = {"time_seconds", "kind", "scenario"}
        field_sets = {"telemetry": telemetry_fields, "trend": trend_fields, "detector": detector_fields,
                      "alert": alert_fields, "event": event_fields,
                      "ml_prediction": {"label", "score"}, "assessment": {"status", "health_score"}}
        grounded_values: list[tuple[float, str | None]] = []
        grounded_role_values: dict[tuple[str, str], list[float]] = {}

        def add_role_value(family: str | None, role: str, value: object) -> None:
            if family and isinstance(value, (int, float)) and not isinstance(value, bool):
                grounded_role_values.setdefault((family, role), []).append(float(value))

        def reject_reference(reason: str, ref: object) -> None:
            source = getattr(ref, "source", "unknown")
            fields = field_sets.get(source, set())
            raw_field = getattr(ref, "field", None)
            safe_field = raw_field if raw_field in fields else "unsupported"
            metric = getattr(ref, "metric", None) or "none"
            value = getattr(ref, "value", None)
            logger.warning("diagnostic grounding rejected reason=%s source=%s field=%s metric=%s value_type=%s",
                           reason, source, safe_field, metric, type(value).__name__ if value is not None else "missing")

        for hypothesis in content.hypotheses:
            for ref in hypothesis.evidence:
                if ref.field not in field_sets[ref.source] or ref.value is None:
                    reject_reference("evidence_reference_unsupported_or_incomplete", ref)
                    raise ProviderInvalidResponse("Diagnostic evidence reference is unsupported or incomplete")
                if ref.source == "telemetry":
                    if ref.metric != ref.field:
                        reject_reference("telemetry_metric_mismatch", ref)
                        raise ProviderInvalidResponse("Diagnostic telemetry evidence has an incorrect metric association")
                    if ref.reading_index is None or ref.reading_index >= len(request.telemetry):
                        reject_reference("telemetry_reference_out_of_window", ref)
                        raise ProviderInvalidResponse("Diagnostic evidence points outside supplied telemetry")
                    expected = getattr(request.telemetry[ref.reading_index], ref.field)
                elif ref.source == "trend":
                    metric = next((item for item in request.trends if item.metric == ref.metric), None)
                    if metric is None or ref.field not in trend_fields - {"metric"}:
                        reject_reference("trend_reference_unsupported", ref)
                        raise ProviderInvalidResponse("Diagnostic evidence points to an unsupported trend")
                    expected = getattr(metric, ref.field)
                elif ref.source == "detector":
                    expected = getattr(request.detector, ref.field)
                    if ref.field == "predicted_faults":
                        if ref.value not in expected:
                            reject_reference("detector_evidence_mismatch", ref)
                            raise ProviderInvalidResponse("Diagnostic evidence does not match detector output")
                        continue
                elif ref.source == "alert":
                    expected = getattr(request.alert, ref.field) if request.alert else None
                elif ref.source == "ml_prediction":
                    expected = getattr(request.ml_prediction, ref.field) if request.ml_prediction else None
                elif ref.source == "assessment":
                    expected = getattr(request.assessment, ref.field) if request.assessment else None
                else:
                    if ref.event_index is None or ref.event_index >= len(request.events):
                        reject_reference("event_reference_out_of_window", ref)
                        raise ProviderInvalidResponse("Diagnostic evidence points outside supplied events")
                    expected = getattr(request.events[ref.event_index], ref.field)
                if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                    matches = isinstance(ref.value, (int, float)) and math.isclose(float(ref.value), float(expected), rel_tol=0, abs_tol=1e-9)
                else:
                    matches = ref.value == expected
                if not matches:
                    reject_reference("evidence_value_mismatch", ref)
                    raise ProviderInvalidResponse("Diagnostic evidence does not match supplied evidence")
                if isinstance(ref.value, (int, float)) and not isinstance(ref.value, bool):
                    if ref.source == "alert" and request.alert:
                        family = _diagnostic_metric_family(request.alert.metric)
                    else:
                        family = _diagnostic_metric_family(ref.metric or ref.field)
                    grounded_values.append((float(ref.value), family))
                    if ref.source == "trend":
                        role = {"initial_value": "first", "latest_value": "latest", "delta": "delta",
                                "elapsed_seconds": "duration", "samples": "samples"}.get(ref.field)
                        if role:
                            add_role_value(family, role, ref.value)
                    elif ref.source == "telemetry" and ref.field in telemetry_fields:
                        if ref.reading_index == 0:
                            add_role_value(family, "first", ref.value)
                        if ref.reading_index == len(request.telemetry) - 1:
                            add_role_value(family, "latest", ref.value)
                    elif ref.source == "alert" and ref.field == "observed_value" and request.alert:
                        add_role_value(family, "latest", ref.value)
                elif ref.source == "alert" and ref.field == "expected_range" and request.alert:
                    family = _diagnostic_metric_family(request.alert.metric)
                    if family and isinstance(ref.value, str):
                        unit_families = _diagnostic_metric_families(ref.value)
                        if unit_families and unit_families != {family}:
                            reject_reference("alert_threshold_metric_mismatch", ref)
                            raise ProviderInvalidResponse("Diagnostic alert threshold has an incorrect metric association")
                        for token in _PROSE_NUMBER_PATTERN.findall(ref.value):
                            add_role_value(family, "threshold", float(token))

        for text in texts:
            timestamp_spans = [match.span() for match in _PROSE_TIMESTAMP_PATTERN.finditer(text)]
            checked_trend_spans: set[tuple[int, int]] = set()
            for pair in _PROSE_TREND_PAIR_PATTERN.finditer(text):
                first_span, latest_span = pair.span("first"), pair.span("latest")
                if any(begin <= first_span[0] and latest_span[1] <= finish for begin, finish in timestamp_spans):
                    continue
                prefix = text[max(0, pair.start() - 48):pair.start()]
                # Threshold ranges have a different evidence role from trend endpoints.
                if re.search(r"\b(?:threshold|limit|expected\s+range)\b", prefix, re.IGNORECASE):
                    continue
                checked_trend_spans.update((first_span, latest_span))
                units = [unit for unit in (pair.group("unit1"), pair.group("unit2")) if unit]
                unit_families = set().union(*(_diagnostic_metric_families(unit) for unit in units)) if units else set()
                named_families = _diagnostic_metric_families(prefix)
                families = unit_families | named_families
                family = next(iter(families)) if len(families) == 1 else None
                trend = next((item for item in request.trends
                              if _diagnostic_metric_family(item.metric) == family), None)
                first_valid = trend is not None and _grounded_prose_number(
                    float(pair.group("first")), pair.group("first"), family,
                    [(trend.initial_value, _diagnostic_metric_family(trend.metric))],
                )
                latest_valid = trend is not None and _grounded_prose_number(
                    float(pair.group("latest")), pair.group("latest"), family,
                    [(trend.latest_value, _diagnostic_metric_family(trend.metric))],
                )
                first_referenced = trend is not None and _grounded_prose_number(
                    float(pair.group("first")), pair.group("first"), family,
                    [(value, family) for value in grounded_role_values.get((family or "", "first"), [])],
                )
                latest_referenced = trend is not None and _grounded_prose_number(
                    float(pair.group("latest")), pair.group("latest"), family,
                    [(value, family) for value in grounded_role_values.get((family or "", "latest"), [])],
                )
                if (len(unit_families) > 1 or len(named_families) > 1
                        or (unit_families and named_families and unit_families != named_families)
                        or len(families) > 1 or trend is None or not first_valid or not latest_valid
                        or not first_referenced or not latest_referenced):
                    logger.warning("diagnostic grounding rejected reason=trend_window_mismatch metric_family=%s",
                                   family or "unknown")
                    raise ProviderInvalidResponse("Diagnostic prose contains unsupported numerical evidence")

            for match in _PROSE_NUMBER_PATTERN.finditer(text):
                if match.span() in checked_trend_spans:
                    continue
                if _prose_number_is_metadata(text, match, timestamp_spans):
                    continue
                token = match.group()
                claim_context = text[max(0, match.start() - 48):min(len(text), match.end() + 48)]
                claim_families = _diagnostic_metric_families(claim_context)
                family = next(iter(claim_families)) if len(claim_families) == 1 else None
                trend = next((item for item in request.trends
                              if _diagnostic_metric_family(item.metric) == family), None)
                if len(claim_families) > 1:
                    logger.warning("diagnostic grounding rejected reason=metric_unit_mismatch")
                    raise ProviderInvalidResponse("Diagnostic prose contains unsupported numerical evidence")
                if trend:
                    role = _prose_claim_role(text, match)
                    field = {"first": "initial_value", "latest": "latest_value", "delta": "delta",
                             "duration": "elapsed_seconds", "samples": "samples"}.get(role)
                    expected = getattr(trend, field) if field else None
                    expected_values = ([float(expected)] if expected is not None else
                                       grounded_role_values.get((family, role), []) if role == "threshold" else [])
                    actual_matches = _grounded_prose_number(float(token), token, family,
                                                            [(value, family) for value in expected_values])
                    cited_matches = _grounded_prose_number(float(token), token, family,
                                                           [(value, family) for value in grounded_role_values.get((family, role), [])])
                    if not actual_matches or not cited_matches:
                        logger.warning("diagnostic grounding rejected reason=trend_role_mismatch metric_family=%s role=%s",
                                       family, role)
                        raise ProviderInvalidResponse("Diagnostic prose contains unsupported numerical evidence")
                    continue
                if _grounded_prose_number(float(token), token, family, grounded_values):
                    continue
                logger.warning("diagnostic grounding rejected reason=unsupported_prose_number metric_family=%s",
                               family or "unknown")
                raise ProviderInvalidResponse("Diagnostic prose contains unsupported numerical evidence")

    async def _call_provider(self, request: DiagnosticRequest) -> object:
        for attempt in range(2):
            try:
                return await self.provider.diagnose(request)
            except ProviderRateLimited as exc:
                # One bounded retry only when the adapter explicitly confirms
                # that replay is safe and supplies a delay from verified policy.
                if (attempt or not exc.retry_safe or exc.retry_after_seconds is None
                        or not math.isfinite(exc.retry_after_seconds) or exc.retry_after_seconds < 0):
                    raise
                await asyncio.sleep(min(max(exc.retry_after_seconds, 0.05), 1.0))
        raise ProviderRateLimited()
