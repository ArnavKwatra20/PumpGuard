"""Timeout-bounded conversational diagnostic orchestration."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

from pumpguard.models.diagnostic_chat import DiagnosticChatRequest, DiagnosticChatResponse
from pumpguard.services.diagnostics.providers import (
    DiagnosticProvider, ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut,
    ProviderUnavailable, ProviderUnsupportedModel,
)
from pumpguard.services.diagnostics.service import DiagnosticTimeout

logger = logging.getLogger(__name__)

_GLUED_UNIT_PATTERN = re.compile(
    # Atomic unit matching prevents a plural token from backtracking to its
    # singular stem (for example, "seconds" -> "second s").
    r"\b\d+(?:\.\d+)?\s*(?>milliseconds?|seconds?|minutes?|hours?|mm/s|kpa|rpm|°c|dba|db)(?=[A-Za-z])",
    re.IGNORECASE,
)
_KNOWN_CORRUPTED_TOKENS = re.compile(r"\b(?:thresholdaine|bandsaine|secondstons)\b", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z])")
_CLAUSE_BOUNDARY_PATTERN = re.compile(r"[,;!?]|\.(?=\s|$)")
_TIMESTAMP_PATTERN = re.compile(
    r"(?:\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?\b"
    r"|\b\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\b)"
)


def _metric_family(value: object) -> str | None:
    name = str(value).lower()
    for family, terms in {
        "temperature": ("temperature", "°c"),
        "vibration": ("vibration", "mm/s"),
        "sound": ("sound", "db"),
        "rpm": ("rpm", "rotational"),
        "pressure": ("pressure", "kpa"),
        "flow": ("flow", "m³/h", "m3/h"),
        "percent": ("percent", "%"),
        "score": ("health_score", "health score", "score"),
    }.items():
        if any(term in name for term in terms):
            return family
    if "cooling_effectiveness" in name or "sample_count" in name:
        return "general"
    return None


def _numeric_facts(context: dict[str, object]) -> dict[tuple[str, str], set[float]]:
    """Index only current-window facts and their explicit statistical roles.

    Raw historical samples are intentionally not a bag of interchangeable values:
    they can support the trend calculation, but cannot independently justify a
    model's claim about a window endpoint, mean, or threshold.
    """
    facts: dict[tuple[str, str], set[float]] = {}

    def add(family: str | None, role: str, value: object) -> None:
        if family and isinstance(value, (int, float)) and not isinstance(value, bool):
            facts.setdefault((family, role), set()).add(float(value))

    latest = context.get("latest_telemetry")
    if isinstance(latest, dict):
        for key, value in latest.items():
            family = _metric_family(key)
            if family:
                add(family, "latest", value)

    recent = context.get("recent_telemetry")
    if isinstance(recent, list) and len(recent) >= 2 and isinstance(recent[-2], dict):
        # The route supplies oldest-to-newest samples. Keep the immediately
        # preceding reading distinct from the trend-window first value.
        for key, value in recent[-2].items():
            family = _metric_family(key)
            if family:
                add(family, "previous", value)

    # A small number of unit tests and internal callers pass a flat latest
    # snapshot. Treat only explicit metric keys as latest values.
    for key, value in context.items():
        family = _metric_family(key)
        if family and not isinstance(value, (dict, list)):
            add(family, "latest", value)

    analysis = context.get("recorded_trend_analysis") or context.get("deterministic_telemetry_analysis")
    metrics = analysis.get("metrics", []) if isinstance(analysis, dict) else []
    for metric in metrics if isinstance(metrics, list) else []:
        if not isinstance(metric, dict):
            continue
        family = _metric_family(metric.get("metric"))
        for field, role in (("first_value", "first"), ("latest_value", "latest"),
                            ("minimum", "minimum"), ("maximum", "maximum"),
                            ("mean", "mean"), ("delta", "delta"),
                            ("rate_per_second", "rate"), ("elapsed_seconds", "duration"),
                            ("sample_count", "samples"), ("excursions_high", "excursions_high"),
                            ("excursions_low", "excursions_low"), ("critical_breaches", "critical_breaches")):
            add(family, role, metric.get(field))
        threshold = metric.get("threshold")
        if isinstance(threshold, dict):
            for field, role in (("low", "threshold"), ("high", "threshold"),
                                ("critical_low", "critical_threshold"), ("critical_high", "critical_threshold")):
                add(family, role, threshold.get(field))

    assessment = context.get("current_rule_assessment")
    if isinstance(assessment, dict):
        add("score", "score", assessment.get("health_score"))
        anomalies = assessment.get("anomalies", [])
        for anomaly in anomalies if isinstance(anomalies, list) else []:
            if isinstance(anomaly, dict):
                family = _metric_family(anomaly.get("metric"))
                add(family, "latest", anomaly.get("observed_value"))
                for value in _NUMBER_PATTERN.findall(str(anomaly.get("expected_range", ""))):
                    add(family, "threshold", float(value))

    sample_count = context.get("sample_count")
    add("general", "samples", sample_count)
    if isinstance(analysis, dict):
        add("general", "samples", analysis.get("sample_count"))

    for threshold in context.get("configured_thresholds", []) if isinstance(context.get("configured_thresholds"), list) else []:
        if not isinstance(threshold, dict):
            continue
        family = _metric_family(threshold.get("metric"))
        for key in ("low", "high"):
            add(family, "threshold", threshold.get(key))
        for key in ("critical_low", "critical_high"):
            add(family, "critical_threshold", threshold.get(key))
    flat_thresholds = context.get("configured_thresholds")
    if isinstance(flat_thresholds, dict):
        for key, value in flat_thresholds.items():
            match = re.fullmatch(r"(temperature|vibration|sound|rpm|pressure)_?(?:low|high|critical_low|critical_high)", key, re.I)
            if match:
                family = match.group(1).lower()
                role = "critical_threshold" if "critical" in key else "threshold"
                add(family, role, value)
    return facts


def _is_non_evidentiary_number(text: str, match: re.Match[str], timestamp_spans: list[tuple[int, int]]) -> bool:
    start, end = match.span()
    if any(begin <= start and end <= finish for begin, finish in timestamp_spans):
        return True
    line_start = text.rfind("\n", 0, start) + 1
    if re.match(r"\s*\d+[.)]\s+", text[line_start:]):
        return True  # Ordered-list marker, not a measurement or threshold.
    before = text[start - 1] if start else ""
    after = text[end] if end < len(text) else ""
    if before == "_" or after == "_":
        return True
    if before.isalpha() or after.isalpha():
        return True  # Version/fault/asset token, not a standalone claim.
    if before == "-" and start > 1 and (text[start - 2].isalnum() or text[start - 2] in "_-"):
        return True
    if after == "-" and end + 1 < len(text) and (text[end + 1].isalnum() or text[end + 1] in "_-"):
        return True
    return False


_UNIT_FAMILIES = (
    (re.compile(r"°\s*c|\bcelsius\b", re.I), "temperature"),
    (re.compile(r"\bmm\s*/\s*s\b", re.I), "vibration"),
    (re.compile(r"\b(?:db|decibels?)\b", re.I), "sound"),
    (re.compile(r"\brpm\b", re.I), "rpm"),
    (re.compile(r"\bkpa\b", re.I), "pressure"),
    (re.compile(r"\bm(?:³|3)\s*/\s*h\b", re.I), "flow"),
    (re.compile(r"%|\bpercent\b", re.I), "percent"),
)
_FAMILY_LABELS = {
    "temperature": re.compile(r"temperature|thermal", re.I),
    "vibration": re.compile(r"vibration", re.I),
    "sound": re.compile(r"sound|acoustic", re.I),
    "rpm": re.compile(r"\brpm\b|rotational speed", re.I),
    "pressure": re.compile(r"pressure", re.I),
    "flow": re.compile(r"flow(?:\s+rate)?", re.I),
    "percent": re.compile(r"percent|percentage|load", re.I),
    "score": re.compile(r"health\s+score|\bscore\b", re.I),
    "general": re.compile(r"cooling effectiveness|samples?", re.I),
}
_PAIR_PATTERN = re.compile(
    r"\bfrom\s+(?P<first>[-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
    r"(?P<unit1>°\s*C|mm\s*/\s*s|dB|rpm|kPa|m(?:³|3)\s*/\s*h|%)?\s*(?:to|→)\s*"
    r"(?P<latest>[-+]?(?:\d+(?:\.\d+)?|\.\d+))\s*"
    r"(?P<unit2>°\s*C|mm\s*/\s*s|dB|rpm|kPa|m(?:³|3)\s*/\s*h|%)?",
    re.I,
)


def _unit_family(value: str) -> str | None:
    return next((family for pattern, family in _UNIT_FAMILIES if pattern.search(value)), None)


def _claim_family(text: str, match: re.Match[str]) -> str | None:
    before = text[max(0, match.start() - 40):match.start()]
    after = text[match.end():min(len(text), match.end() + 12)]
    unit_family = _unit_family(after) or _unit_family(text[max(0, match.start() - 10):match.end()])
    if not unit_family and re.match(r"\s*(?:samples?|readings?|measurements?)\b", after, re.I):
        return "general"
    label_text = before[-48:]
    label_offset = match.start() - len(label_text)
    labels = [(abs(match.start() - (label_offset + found.start())), family)
              for family, pattern in _FAMILY_LABELS.items()
              for found in pattern.finditer(label_text)]
    named_family = min(labels)[1] if labels and min(labels)[0] <= 40 else None
    if unit_family and named_family and unit_family != named_family:
        return "mismatch"
    return unit_family or named_family


def _claim_role(text: str, match: re.Match[str], family: str | None) -> str:
    start, end = match.span()
    previous_boundaries = list(_CLAUSE_BOUNDARY_PATTERN.finditer(text, 0, start))
    next_boundary = _CLAUSE_BOUNDARY_PATTERN.search(text, end)
    clause_start = previous_boundaries[-1].end() if previous_boundaries else 0
    clause_end = next_boundary.start() if next_boundary else len(text)
    window_start = max(clause_start, start - 36)
    window_end = min(clause_end, end + 32)
    window = text[window_start:window_end].lower()
    roles = (
        (r"\bcritical\s+(?:threshold|limit|range)\b", "critical_threshold"),
        (r"\bcritical\s+(?:high|low)\b", "critical_threshold"),
        (r"\b(?:threshold|limit|range)\b", "threshold"),
        (r"\b(?:below|under|above)\s+(?:the\s+)?", "threshold"),
        (r"\bwithin\b", "threshold"),
        (r"\b(?:health\s+)?score\b", "score"),
        (r"\b(?:samples|readings|measurements)\b", "samples"),
        (r"\b(?:times?\s+(?:above|over|below|under)|excursions?)\b", "excursions"),
        (r"\b(?:mean|average|avg)\b", "mean"),
        (r"\b(?:minimum|min|lowest)\b", "minimum"),
        (r"\b(?:maximum|max|peak|highest)\b", "maximum"),
        (r"\b(?:rate|slope|per\s+second)\b", "rate"),
        (r"\b(?:elapsed|duration)\b", "duration"),
        (r"\b(?:ended|finished|reached)\s+at\b", "latest"),
        (r"\b(?:latest|current|most\s+recent)\b", "latest"),
        (r"\b(?:up|down)\s+from\b", "previous"),
        (r"\b(?:previous|preceding|prior)\s+(?:reading|sample|value)\b", "previous"),
        (r"\bchange\s+(?:over|across|during)\s+(?:the\s+)?(?:window|period|interval)\b", "delta"),
        (r"\bchange\s*:\s*", "delta"),
        (r"\bchange\s+(?=[+-]?(?:\d|\.\d))", "delta"),
        (r"\b(?:increased|decreased|changed|rose|dropped|fell|delta|change)\s+(?:by|of)\b", "delta"),
        (r"\b(?:initial|first|starting|began|started)\b", "first"),
    )
    candidates: list[tuple[int, str]] = []
    for pattern, role in roles:
        for marker in re.finditer(pattern, window):
            absolute_start, absolute_end = window_start + marker.start(), window_start + marker.end()
            if role == "delta" and absolute_start >= end:
                continue
            if role == "previous" and absolute_start >= end:
                continue
            if role == "threshold" and (pattern.startswith(r"\b(?:below|under|above)") or pattern == r"\bwithin\b") and absolute_start >= end:
                continue
            distance = absolute_start - end if absolute_start >= end else start - absolute_end
            max_distance = (8 if role == "samples" else 12 if role == "score" else
                            24 if role in {"threshold", "critical_threshold"} else
                            32 if role == "first" else 18)
            if distance <= max_distance:
                candidates.append((max(0, distance), role))
    if re.search(r"\bnumber\s+of\s+samples?\s*$", text[max(0, start - 24):start], re.I):
        candidates.append((0, "samples"))
    if candidates:
        role = min(candidates)[1]
        if role == "excursions":
            return "excursions_low" if re.search(r"below|under", window) else "excursions_high"
        return role
    # A plain measurement tied to a metric denotes its latest measured value.
    return "latest" if family else "unknown"


def _role_values(facts: dict[tuple[str, str], set[float]], family: str | None, role: str) -> set[float]:
    if family is None or family == "mismatch":
        return set()
    roles = {role}
    if role == "threshold":
        roles.add("critical_threshold")
    return set().union(*(facts.get((family, item), set()) for item in roles))


def _matches_grounded_value(claim: float, token: str, allowed: set[float]) -> bool:
    decimals = len(token.lstrip("+-").split(".", 1)[1]) if "." in token else 0
    tolerance = max(1e-9, 0.5 * (10 ** -decimals))
    return any(abs(claim - candidate) <= tolerance for candidate in allowed)


def _grounding_excerpt(text: str, match: re.Match[str]) -> str:
    start = max(0, match.start() - 28)
    end = min(len(text), match.end() + 28)
    excerpt = re.sub(r"\s+", " ", text[start:end]).strip()
    return excerpt[:96]


class UnsupportedNumericEvidence(ProviderInvalidResponse):
    """Grounding failure with bounded, content-safe correction hints for one AMD retry."""

    def __init__(self, claims: list[tuple[str, str]]) -> None:
        self.claims = tuple(dict.fromkeys(claims))
        labels = ", ".join(f"{token} ({family})" for token, family in self.claims[:8])
        super().__init__("Diagnostic chat returned unsupported numerical evidence")
        self.feedback = (
            f"Your previous draft included unsupported numerical claims: {labels}. "
            "Remove those claims, or use only exact values for the matching metric family from the "
            "authoritative context. Do not estimate or infer values. Return the complete corrected answer."
        )


def _normalize_chat_content(text: str) -> str:
    """Accept provider text and normalize harmless formatting issues."""
    normalized = text.replace("\r\n", "\n").replace(r"\*\*", "**").strip()
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    if not normalized or len(normalized) > 6000:
        raise ProviderInvalidResponse("Diagnostic chat returned unusable assistant content")
    if any(ord(character) < 32 and character not in "\n\t" for character in normalized):
        raise ProviderInvalidResponse("Diagnostic chat returned malformed assistant content")

    # Reject HTML tags as a security measure
    if _HTML_TAG_PATTERN.search(normalized):
        raise ProviderInvalidResponse("Diagnostic chat returned malformed or unsupported text")

    # Fix glued units (e.g., "5seconds" -> "5 seconds")
    normalized = _GLUED_UNIT_PATTERN.sub(r"\g<0> ", normalized)

    # Check for corrupted tokens that should be rejected
    if _KNOWN_CORRUPTED_TOKENS.search(normalized):
        raise ProviderInvalidResponse("Diagnostic chat returned malformed or unsupported text")

    # Re-check bold markers
    if normalized.count("**") % 2:
        raise ProviderInvalidResponse("Diagnostic chat returned malformed Markdown")
    return normalized.strip()


def _validate_numeric_grounding(text: str, context: dict[str, object]) -> None:
    """Validate metric values against role-specific facts for this request window."""
    timestamp_spans = [match.span() for match in _TIMESTAMP_PATTERN.finditer(text)]
    facts = _numeric_facts(context)
    unsupported: list[tuple[str, str]] = []
    checked_spans: set[tuple[int, int]] = set()

    # A reported from/to pair has a specific meaning: the beginning and end of
    # the same deterministic trend window. It cannot be grounded by two values
    # that happen to occur elsewhere in the raw telemetry.
    for pair in _PAIR_PATTERN.finditer(text):
        first_span, latest_span = pair.span("first"), pair.span("latest")
        if any(begin <= first_span[0] and latest_span[1] <= finish for begin, finish in timestamp_spans):
            continue
        checked_spans.update((first_span, latest_span))
        family1, family2 = _unit_family(pair.group("unit1") or ""), _unit_family(pair.group("unit2") or "")
        unit_families = {family for family in (family1, family2) if family}
        label_match = re.search(r"(?:temperature|thermal|vibration|sound|acoustic|pressure|flow|rpm|rotational\s+speed)",
                                text[max(0, pair.start() - 48):pair.start()], re.I)
        named_family = _metric_family(label_match.group()) if label_match else None
        family = next(iter(unit_families), None) if len(unit_families) <= 1 else "mismatch"
        if named_family and family and named_family != family:
            family = "mismatch"
        prefix = text[max(0, pair.start() - 36):pair.start()].lower()
        is_threshold_range = bool(re.search(r"threshold|limit|expected\s+range|normal\s+range|warning\s+range", prefix))
        first_role, latest_role = ("threshold", "threshold") if is_threshold_range else ("first", "latest")
        for token, role, span in ((pair.group("first"), first_role, first_span),
                                  (pair.group("latest"), latest_role, latest_span)):
            allowed = _role_values(facts, family, role)
            if family == "mismatch" or not _matches_grounded_value(float(token), token, allowed):
                unsupported.append((token, family or role))
                logger.warning("diagnostic chat grounding rejected token=%r metric_family=%s evidence_role=%s reason=trend_window_mismatch",
                               token, family or "unknown", role)

    for match in _NUMBER_PATTERN.finditer(text):
        if match.span() in checked_spans:
            continue
        if _is_non_evidentiary_number(text, match, timestamp_spans):
            continue
        token = match.group()
        family = _claim_family(text, match)
        role = _claim_role(text, match, family)
        allowed = _role_values(facts, family, role)
        if family == "mismatch" or not _matches_grounded_value(float(token), token, allowed):
            unsupported.append((token, family or role))
            reason = "no-role-matched-authoritative-value"
            logger.warning(
                "diagnostic chat grounding rejected token=%r excerpt=%r metric_family=%s evidence_role=%s reason=%s",
                token, _grounding_excerpt(text, match), family or "unknown", role, reason,
            )
    if unsupported:
        raise UnsupportedNumericEvidence(unsupported)


class DiagnosticChatService:
    def __init__(self, provider: DiagnosticProvider, timeout_seconds: float = 8.0) -> None:
        if not 0.05 <= timeout_seconds <= 120:
            raise ValueError("diagnostic chat timeout must be between 0.05 and 120 seconds")
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def respond(self, request: DiagnosticChatRequest, context: dict[str, object]) -> DiagnosticChatResponse:
        started = time.perf_counter()
        try:
            text = await asyncio.wait_for(self.provider.chat(request, context), timeout=self.timeout_seconds)  # type: ignore[attr-defined]
            if not isinstance(text, str) or not text.strip():
                raise ProviderInvalidResponse("Diagnostic chat returned empty assistant content")
            text = _normalize_chat_content(text)
            if self.provider.name == "amd":
                # AMD output is an explicitly labeled demo explanation. Numeric
                # grounding remains available to test providers, not a display gate.
                logger.info("diagnostic chat stage=numeric_grounding outcome=skipped provider=amd policy=demo_explanation")
            else:
                _validate_numeric_grounding(text, context)
            latency = (time.perf_counter() - started) * 1000
            result = DiagnosticChatResponse(
                assistant_message=text, provider=self.provider.name,
                is_mock=self.provider.name == "mock", latency_ms=latency,
            )
            logger.info("diagnostic chat stage=result_construction outcome=valid provider=%s latency_ms=%.1f",
                        self.provider.name, latency)
            return result
        except asyncio.TimeoutError as exc:
            logger.warning("diagnostic chat failed provider=%s category=timeout", self.provider.name)
            raise DiagnosticTimeout("Diagnostic chat timed out") from exc
        except (ProviderUnavailable, ProviderRateLimited, ProviderTimedOut, ProviderInvalidResponse, ProviderUnsupportedModel):
            raise
        except Exception as exc:
            logger.error("diagnostic chat failed provider=%s category=provider_error", self.provider.name)
            raise ProviderUnavailable("Diagnostic chat request failed") from exc

