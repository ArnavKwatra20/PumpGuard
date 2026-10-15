from fastapi.testclient import TestClient
from pumpguard.api.app import create_app
def client():return TestClient(create_app())
def test_health_and_empty_inventory():
    c=client()
    assert c.get("/health").json()["status"]=="ok"
    assert c.get("/api/v1/pumps").json()==[]
    assert c.get("/api/v1/pumps/ghost/telemetry/latest").status_code==404
    compute=c.get("/api/v1/ml/status").json()
    assert "compute_provider" in compute and "device" in compute
    assert "model_version" in compute and "execution_path" in compute
def test_simulation_latest_history_assessment_and_bounds():
    c=client()
    res=c.post("/api/v1/simulation/generate",json={"scenario":"overheating","sample_count":5,"random_seed":3})
    assert res.status_code==200
    assert res.json()["assessment"]["status"] in ("warning","critical")
    assert c.get("/api/v1/pumps").json()==["pump-01"]
    assert c.get("/api/v1/pumps/pump-01/telemetry/latest").status_code==200
    assert len(c.get("/api/v1/pumps/pump-01/telemetry/history?limit=3").json())==3
    assert c.get("/api/v1/pumps/pump-01/assessment").json()["health_score"]<=100
    assert c.get("/api/v1/pumps/pump-01/telemetry/history?limit=2001").status_code==422

def test_live_sample_advances_process_local_session_and_returns_assessment():
    c=client()
    payload={"pump_id":"live-01","scenario":"overheating","random_seed":44}
    first=c.post("/api/v1/simulation/live-sample",json=payload)
    second=c.post("/api/v1/simulation/live-sample",json=payload)
    assert first.status_code==second.status_code==200
    assert len(first.json()["readings"])==len(second.json()["readings"])==1
    assert first.json()["readings"][0]["temperature_c"] != second.json()["readings"][0]["temperature_c"]
    assert second.json()["assessment"]["timestamp"]==second.json()["readings"][0]["timestamp"]
    assert c.get("/api/v1/pumps/live-01/telemetry/latest").json()==second.json()["readings"][0]
    assert c.post("/api/v1/simulation/live-sample",json={**payload,"scenario":"wrong"}).status_code==422

def test_live_sample_remains_available_when_diagnostic_provider_is_unavailable():
    """Live telemetry must not depend on AMD or any diagnostic provider."""
    class UnavailableProvider:
        name = "mock"

        async def diagnose(self, request):
            raise RuntimeError("diagnostic provider unavailable")

        async def chat(self, request, context):
            raise RuntimeError("diagnostic provider unavailable")

    c = TestClient(create_app(diagnostic_provider=UnavailableProvider()))
    response = c.post("/api/v1/simulation/live-sample", json={
        "pump_id": "amd-independent",
        "scenario": "normal",
        "random_seed": 7,
        "client_session_id": "dashboard",
        "reset_session": True,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["readings"]) == 1
    assert body["readings"][0]["pump_id"] == "amd-independent"
    assert body["assessment"]["status"] == "normal"

def test_live_sample_client_sessions_are_isolated_for_shared_pump_ids():
    c=client()
    bearing={"pump_id":"shared-live","scenario":"bearing_wear","random_seed":42,"client_session_id":"dashboard-a"}
    imbalance={"pump_id":"shared-live","scenario":"imbalance","random_seed":42,"client_session_id":"dashboard-b"}
    first_bearing=c.post("/api/v1/simulation/live-sample",json=bearing).json()["readings"][0]
    other_scenario=c.post("/api/v1/simulation/live-sample",json=imbalance).json()["readings"][0]
    next_bearing=c.post("/api/v1/simulation/live-sample",json=bearing).json()["readings"][0]
    assert first_bearing["vibration_mm_s"] != next_bearing["vibration_mm_s"]
    assert other_scenario["vibration_mm_s"] > 8

def test_live_sample_accepts_bounded_controls_and_returns_simulation_snapshot():
    c=client()
    payload={"pump_id":"controlled","scenario":"cavitation","random_seed":8,"client_session_id":"ui",
        "speed":2,"rpm_setpoint":1920,"load_percent":80,"inlet_restriction_percent":30,"fault_severity":0.7,"fault_enabled":True}
    response=c.post("/api/v1/simulation/live-sample",json=payload)
    assert response.status_code==200
    body=response.json()
    reading=body["readings"][0]
    assert body["simulation"]["time_seconds"]==2
    assert body["simulation"]["events"][0]["kind"]=="fault_injected"
    assert reading["load_percent"]==80
    assert 1900 <= reading["rpm"] <= 1940
    assert body["simulation"]["config"]["rpm_setpoint"]==1920
    assert reading["inlet_restriction_percent"]==30
    assert "scenario" not in reading
    assert c.post("/api/v1/simulation/live-sample",json={**payload,"speed":9}).status_code==422
    assert c.post("/api/v1/simulation/live-sample",json={**payload,"rpm_setpoint":3000}).status_code==422

def test_live_reset_restarts_seeded_session_clock():
    c=client()
    payload={"pump_id":"reset-clock","scenario":"bearing_wear","random_seed":19,"client_session_id":"ui"}
    c.post("/api/v1/simulation/live-sample",json=payload)
    c.post("/api/v1/simulation/live-sample",json=payload)
    restarted=c.post("/api/v1/simulation/live-sample",json={**payload,"speed":2,"reset_session":True}).json()
    assert restarted["simulation"]["time_seconds"]==2
    assert restarted["simulation"]["step"]==1
def test_validation_unknown_scenario_and_unknown_pump():
    c=client()
    assert c.post("/api/v1/simulation/generate",json={"scenario":"wrong"}).status_code==422
    assert c.post("/api/v1/simulation/generate",json={"sample_count":0}).status_code==422
    assert c.get("/api/v1/pumps/no/assessment").status_code==404
