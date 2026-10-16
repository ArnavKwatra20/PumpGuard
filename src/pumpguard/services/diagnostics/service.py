"""Timeout-bounded inference orchestration with process-local episode deduplication."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import json
import logging
import math
import re
import time
import uuid

from pydantic import ValidationError
from pydantic import BaseModel

from pumpguard.models.diagnostic import DiagnosticContent, DiagnosticRequest, DiagnosticResult
from pumpguard.services.diagnostics.providers import (
    DiagnosticProvider, ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut, ProviderUnavailable, ProviderUnsupportedModel,
)

logger = logging.getLogger(__name__)

_PROSE_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z])")
_PROSE_TIMESTAMP_PATTERN = re.compile(
    r"(?:\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    r"|\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b)"
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
    for family, terms in {
        "temperature": ("temperature", "°c", "celsius"),
        "vibration": ("vibration", "mm/s"),
        "sound": ("sound", "db", "decibel"),
        "rpm": ("rpm", "rotational"),
        "pressure": ("pressure", "kpa"),
        "percent": ("percent", "%"),
    }.items():
        if any(term in name for term in terms):
            return family
    return None


def _grounded_prose_number(claim: float, token: str, claim_family: str | None,
                           evidence_values: list[tuple[float, str | None]]) -> bool:
    decimals = len(token.lstrip("+-").split(".", 1)[1]) if "." in token else 0
    tolerance = max(1e-9, 0.5 * (10 ** -decimals))
    return any(
        (claim_family is None or family is None or claim_family == family)
        and math.isclose(claim, value, rel_tol=0, abs_tol=tolerance)
        for value, family in evidence_values
    )


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
        return f"{request.pump_id}|{episode or request.assessment_timestamp.isoformat()}"

    async def diagnose(self, request: DiagnosticRequest) -> DiagnosticResult:
        key = self._key(request)
        async with self._lock:
            cached = self._cache.get(key)
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
        """Require every supplied trend to describe this request's telemetry window."""
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
                matches = math.isclose(actual, value, rel_tol=1e-9, abs_tol=1e-9) if isinstance(value, float) else actual == value
                if not matches:
                    raise ProviderInvalidResponse("Diagnostic trend does not match its telemetry evidence window")

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
        for hypothesis in content.hypotheses:
            for ref in hypothesis.evidence:
                if ref.field not in field_sets[ref.source] or ref.value is None:
                    raise ProviderInvalidResponse("Diagnostic evidence reference is unsupported or incomplete")
                if ref.source == "telemetry":
                    if ref.metric != ref.field:
                        raise ProviderInvalidResponse("Diagnostic telemetry evidence has an incorrect metric association")
                    if ref.reading_index is None or ref.reading_index >= len(request.telemetry):
                        raise ProviderInvalidResponse("Diagnostic evidence points outside supplied telemetry")
                    expected = getattr(request.telemetry[ref.reading_index], ref.field)
                elif ref.source == "trend":
                    metric = next((item for item in request.trends if item.metric == ref.metric), None)
                    if metric is None or ref.field not in trend_fields - {"metric"}:
                        raise ProviderInvalidResponse("Diagnostic evidence points to an unsupported trend")
                    expected = getattr(metric, ref.field)
                elif ref.source == "detector":
                    expected = getattr(request.detector, ref.field)
                    if ref.field == "predicted_faults":
                        if ref.value not in expected:
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
                        raise ProviderInvalidResponse("Diagnostic evidence points outside supplied events")
                    expected = getattr(request.events[ref.event_index], ref.field)
                if isinstance(expected, (int, float)) and not isinstance(expected, bool):
                    matches = isinstance(ref.value, (int, float)) and math.isclose(float(ref.value), float(expected), rel_tol=0, abs_tol=1e-9)
                else:
                    matches = ref.value == expected
                if not matches:
                    raise ProviderInvalidResponse("Diagnostic evidence does not match supplied evidence")
                if isinstance(ref.value, (int, float)) and not isinstance(ref.value, bool):
                    grounded_values.append((float(ref.value), _diagnostic_metric_family(ref.metric or ref.field)))

        for text in texts:
            timestamp_spans = [match.span() for match in _PROSE_TIMESTAMP_PATTERN.finditer(text)]
            for match in _PROSE_NUMBER_PATTERN.finditer(text):
                if _prose_number_is_metadata(text, match, timestamp_spans):
                    continue
                token = match.group()
                if _grounded_prose_number(float(token), token, _diagnostic_metric_family(
                        text[max(0, match.start() - 18):min(len(text), match.end() + 18)]), grounded_values):
                    continue
                excerpt = re.sub(r"\s+", " ", text[max(0, match.start() - 28):min(len(text), match.end() + 28)]).strip()[:96]
                logger.warning("diagnostic grounding rejected token=%r excerpt=%r reason=unsupported-prose-number",
                               token, excerpt)
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
