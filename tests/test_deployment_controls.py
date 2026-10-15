from fastapi.testclient import TestClient

from pumpguard.api.app import create_app


def test_rate_limit_returns_retry_after_for_expensive_routes(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "mock")
    monkeypatch.setenv("PUMPGUARD_RATE_LIMIT_DIAGNOSTICS", "1")
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/diagnostics/models").status_code == 200
        limited = client.get("/api/v1/diagnostics/models")
    assert limited.status_code == 429
    assert limited.headers["retry-after"].isdigit()
    assert "rate limit" in limited.json()["detail"].lower()


def test_simulation_limit_is_separate_from_diagnostics(monkeypatch):
    monkeypatch.setenv("PUMPGUARD_DIAGNOSTIC_PROVIDER", "mock")
    monkeypatch.setenv("PUMPGUARD_RATE_LIMIT_SIMULATION", "1")
    with TestClient(create_app()) as client:
        assert client.post("/api/v1/simulation/generate", json={"random_seed": 1}).status_code == 200
        assert client.get("/api/v1/diagnostics/models").status_code == 200
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
