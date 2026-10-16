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
    r"\b\d+(?:\.\d+)?\s*(?:seconds?|minutes?|hours?|milliseconds?|mm/s|kpa|rpm|°c|db)(?=[A-Za-z])",
    re.IGNORECASE,
)
_KNOWN_CORRUPTED_TOKENS = re.compile(r"\b(?:thresholdaine|bandsaine|secondstons)\b", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?![A-Za-z])")
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
    }.items():
        if any(term in name for term in terms):
            return family
    return None


def _numeric_values(value: object, *, metric: str | None = None) -> dict[str, set[float]]:
    """Collect context numbers by telemetry family, excluding identifiers and timestamps."""
    values: dict[str, set[float]] = {family: set() for family in
                                     ("temperature", "vibration", "sound", "rpm", "pressure", "flow", "percent", "general")}
    if isinstance(value, dict):
        current_metric = value.get("metric", metric)
        for key, item in value.items():
            if key in {"timestamp", "pump_id", "asset_id", "operating_mode", "scenario", "direction", "unit"}:
                continue
            family = _metric_family(key) or _metric_family(current_metric)
            if isinstance(item, (int, float)) and not isinstance(item, bool):
                values[family or "general"].add(float(item))
            elif isinstance(item, str) and key in {"expected_range", "value"}:
                for match in _NUMBER_PATTERN.finditer(item):
                    values[family or "general"].add(float(match.group()))
            else:
                # Preserve the enclosing telemetry metric while descending into
                # nested threshold/statistics objects. Otherwise values such as
                # a temperature high threshold become untyped ``general`` values
                # and valid chat explanations are rejected as unsupported.
                nested = _numeric_values(item, metric=current_metric)
                for nested_family, numbers in nested.items():
                    values[nested_family].update(numbers)
    elif isinstance(value, list):
        for item in value:
            nested = _numeric_values(item, metric=metric)
            for nested_family, numbers in nested.items():
                values[nested_family].update(numbers)
    return values


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


def _claim_family(text: str, match: re.Match[str]) -> str | None:
    window_start = max(0, match.start() - 48)
    window_end = min(len(text), match.end() + 48)
    window = text[window_start:window_end].lower()
    markers = {
        "temperature": (r"°c", r"celsius", r"degrees?\s*c", r"temperature"),
        "vibration": (r"mm/s", r"vibration"),
        "sound": (r"\bdb\b", r"decibel", r"sound"),
        "rpm": (r"\brpm\b", r"rotat(?:ional|ion)"),
        "pressure": (r"\bkpa\b", r"pressure"),
        "flow": (r"m³/h", r"m3/h", r"flow(?:\s+rate)?"),
        "percent": (r"%", r"percent"),
        "general": (r"samples?", r"health\s+score", r"cooling\s+effectiveness"),
    }
    candidates: list[tuple[int, int, str]] = []
    for family, patterns in markers.items():
        for pattern in patterns:
            for marker in re.finditer(pattern, window):
                marker_position = window_start + marker.start()
                distance = abs(marker_position - match.start())
                # Prefer an adjacent unit, then a label immediately before the
                # value. This avoids assigning a value to a later unrelated
                # metric in the same sentence.
                if marker_position >= match.end() and marker_position - match.end() <= 8:
                    priority = 0
                elif marker_position < match.start() and match.start() - marker_position <= 32:
                    priority = 1
                else:
                    priority = 2
                candidates.append((priority, distance, family))
    if not candidates:
        return None
    best = min(candidates)
    # A distant marker is not a reliable metric association. Leave the claim
    # untyped so it must still match an authoritative value somewhere in the
    # server-owned context, without being compared to the wrong family.
    return best[2] if best[0] < 2 else None


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
    """Reject unsupported measurements while ignoring list ordinals and metadata identifiers."""
    timestamp_spans = [match.span() for match in _TIMESTAMP_PATTERN.finditer(text)]
    allowed_by_family = _numeric_values(context)
    unsupported: list[tuple[str, str]] = []
    for match in _NUMBER_PATTERN.finditer(text):
        if _is_non_evidentiary_number(text, match, timestamp_spans):
            continue
        token = match.group()
        family = _claim_family(text, match)
        allowed = allowed_by_family[family] if family else set().union(*allowed_by_family.values())
        if not _matches_grounded_value(float(token), token, allowed):
            unsupported.append((token, family or "unknown"))
            reason = ("no-authoritative-values-for-metric-family" if family and not allowed
                      else "value-not-present-or-outside-rounding-tolerance")
            logger.warning(
                "diagnostic chat grounding rejected token=%r excerpt=%r metric_family=%s reason=%s",
                token, _grounding_excerpt(text, match), family or "unknown", reason,
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
            try:
                _validate_numeric_grounding(text, context)
            except UnsupportedNumericEvidence as exc:
                # A single correction helps recover from occasional model fabrication while
                # preserving the same total request deadline and fail-closed validation.
                if self.provider.name != "amd":
                    raise
                remaining = self.timeout_seconds - (time.perf_counter() - started)
                if remaining <= 0.05:
                    raise
                retry_context = dict(context)
                retry_context["_numeric_grounding_feedback"] = exc.feedback
                logger.warning("diagnostic chat grounding repair provider=amd retry=1 rejected_claims=%d",
                               len(exc.claims))
                text = await asyncio.wait_for(
                    self.provider.chat(request, retry_context), timeout=remaining  # type: ignore[attr-defined]
                )
                if not isinstance(text, str) or not text.strip():
                    raise ProviderInvalidResponse("Diagnostic chat returned empty assistant content")
                text = _normalize_chat_content(text)
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

