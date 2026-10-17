"""Consistent HTTP mapping for diagnostic-provider failures."""
from fastapi import HTTPException

from pumpguard.services.diagnostics.providers import (
    ProviderInvalidResponse, ProviderRateLimited, ProviderTimedOut, ProviderUnavailable,
    ProviderUnsupportedModel,
)
from pumpguard.services.diagnostics.service import DiagnosticTimeout


def provider_http_error(exc: Exception, provider_name: str, *, include_context: bool = False) -> HTTPException:
    if isinstance(exc, (DiagnosticTimeout, ProviderTimedOut)):
        status_code = 504
    elif isinstance(exc, ProviderRateLimited):
        status_code = 429
    elif isinstance(exc, ProviderInvalidResponse):
        status_code = 502
    elif isinstance(exc, ProviderUnsupportedModel):
        status_code = 422
    elif isinstance(exc, ProviderUnavailable):
        status_code = 503
    else:
        raise TypeError(f"Unsupported diagnostic provider error type: {type(exc).__name__}")

    detail = str(exc)
    if include_context:
        source = "AMD" if provider_name in {"amd", "amd_unavailable"} else "test mock" if provider_name == "mock" else "configured provider"
        detail = f"{detail}. No response from {source} was produced; the existing monitoring data remains unchanged."
    headers = {"Retry-After": "1"} if status_code == 429 else None
    return HTTPException(status_code=status_code, detail=detail, headers=headers)
