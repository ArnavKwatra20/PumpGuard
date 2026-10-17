import pytest
from fastapi.testclient import TestClient

from pumpguard.api.app import create_app
from pumpguard.config import get_settings
from pumpguard.services.diagnostics.providers import MockDiagnosticProvider


def test_rate_limit_returns_retry_after_for_simulation_routes(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_RATE_LIMIT_SIMULATION", "1")
    with TestClient(create_app(diagnostic_provider=MockDiagnosticProvider())) as client:
        assert client.post("/api/v1/simulation/generate", json={"random_seed": 1}).status_code == 200
        limited = client.post("/api/v1/simulation/generate", json={"random_seed": 2})
    assert limited.status_code == 429
    assert limited.headers["retry-after"].isdigit()
    assert "rate limit" in limited.json()["detail"].lower()


def test_simulation_limit_is_separate_from_diagnostics(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_RATE_LIMIT_SIMULATION", "1")
    with TestClient(create_app(diagnostic_provider=MockDiagnosticProvider())) as client:
        assert client.post("/api/v1/simulation/generate", json={"random_seed": 1}).status_code == 200
        assert client.post("/api/v1/simulation/generate", json={"random_seed": 2}).status_code == 429


def test_cors_allows_configured_origin_and_rejects_other_origin(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_CORS_ORIGINS", "https://demo.example")
    with TestClient(create_app()) as client:
        allowed = client.options("/api/v1/simulation/generate", headers={
            "Origin": "https://demo.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        })
        denied = client.options("/api/v1/simulation/generate", headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        })
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://demo.example"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_diagnostic_timeout_budgets_are_configurable_and_ordered(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_CATALOG_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_COMPLETION_TIMEOUT_SECONDS", "240")
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS", "250")
    settings = get_settings()
    assert settings.diagnostic_catalog_timeout_seconds == 5
    assert settings.diagnostic_completion_timeout_seconds == 240
    assert settings.diagnostic_timeout_seconds == 250

    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_TIMEOUT_SECONDS", "245")
    with pytest.raises(ValueError, match="must exceed catalog plus completion"):
        get_settings()
