"""Deterministic fault-relationship and cascading-failure tests."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from pumpguard.api.app import create_app
from pumpguard.models.assessment import HealthAssessment, Anomaly
from pumpguard.models.telemetry import TelemetryReading
from pumpguard.relationships.service import RelationshipService
from pumpguard.simulator.generator import TelemetryGenerator


def _assessment(pump_id: str, faults: list[str], anomalies: list[Anomaly] | None = None) -> HealthAssessment:
    reading = TelemetryReading(pump_id=pump_id, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                               temperature_c=68, vibration_mm_s=2, sound_db=68, rpm=1780)
    return HealthAssessment(pump_id=pump_id, timestamp=reading.timestamp, health_score=70, status="warning",
                            anomalies=anomalies or [], detected_faults=faults, recommendations=["inspect"])


def test_bearing_wear_produces_multi_step_cascade():
    service = RelationshipService()
    result = service.analyze(_assessment("pump-01", ["bearing_wear_pattern"]))
    assert result.observed_faults == ["bearing_wear"]
    # bearing_wear -> friction_increase -> overheating is a grounded 3-node chain.
    longest = max(result.chains, key=lambda c: len(c.nodes))
    assert [n.fault_id for n in longest.nodes] == ["bearing_wear", "friction_increase", "overheating"]
    assert longest.nodes[0].observed is True
    assert all(n.observed is False for n in longest.nodes[1:])
    assert longest.overall_confidence in {"low", "moderate", "high"}
    assert "Bearing wear" in result.explanation


def test_no_fault_yields_no_chains():
    service = RelationshipService()
    result = service.analyze(_assessment("pump-01", []))
    assert result.observed_faults == []
    assert result.chains == []
    assert "No rule-based fault pattern" in result.explanation
    assert all(c.severity == "normal" for c in result.components)


def test_unknown_pattern_is_ignored():
    service = RelationshipService()
    result = service.analyze(_assessment("pump-01", ["not_a_real_pattern", "bearing_wear_pattern"]))
    assert result.observed_faults == ["bearing_wear"]


def test_analysis_is_deterministic():
    service = RelationshipService()
    a = service.analyze(_assessment("pump-01", ["cavitation_pattern"]))
    b = service.analyze(_assessment("pump-01", ["cavitation_pattern"]))
    assert a.model_dump() == b.model_dump()


def test_component_severity_reflects_anomalous_metrics():
    service = RelationshipService()
    anomalies = [Anomaly(metric="vibration_mm_s", observed_value=9.0, expected_range="0-4.5 mm/s",
                         severity="critical", explanation="high vibration")]
    result = service.analyze(_assessment("pump-01", ["bearing_wear_pattern"], anomalies))
    bearing = next(c for c in result.components if c.component_id == "bearing")
    assert bearing.severity == "critical"
    assert "vibration_mm_s" in bearing.anomalous_metrics


def test_relationships_are_hypotheses_not_confirmed_causes():
    service = RelationshipService()
    result = service.analyze(_assessment("pump-01", ["bearing_wear_pattern"]))
    for node in [n for c in result.chains for n in c.nodes[1:]]:
        assert node.observed is False
        assert node.provenance in {"engineering_hypothesis", "observed_correlation"}
    assert any("hypothes" in lim.lower() for lim in result.limitations)


def test_cycles_do_not_cause_infinite_traversal():
    service = RelationshipService()
    result = service.analyze(_assessment("pump-01", ["cavitation_pattern"]))
    for chain in result.chains:
        ids = [n.fault_id for n in chain.nodes]
        assert len(ids) == len(set(ids)), "chain repeated a fault (cycle not guarded)"
        assert len(ids) <= 7


def test_endpoint_404_for_unknown_asset():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/pumps/does-not-exist/relationships")
    assert response.status_code == 404


def test_endpoint_analysis_does_not_mutate_assessment():
    with TestClient(create_app()) as client:
        client.post("/api/v1/simulation/generate", json={"pump_id": "pump-01", "scenario": "bearing_wear", "random_seed": 7, "sample_count": 30})
        before = client.get("/api/v1/pumps/pump-01/assessment").json()
        analysis = client.get("/api/v1/pumps/pump-01/relationships")
        after = client.get("/api/v1/pumps/pump-01/assessment").json()
    assert analysis.status_code == 200
    assert analysis.json()["observed_faults"] == ["bearing_wear"]
    assert before == after


def test_scenarios_map_to_expected_seed_faults():
    service = RelationshipService()
    for scenario, expected in (("bearing_wear", "bearing_wear"), ("cavitation", "cavitation"),
                               ("imbalance", "imbalance"), ("overheating", "overheating")):
        reading, _ = TelemetryGenerator(11).generate_one(scenario)
        from pumpguard.detection.rules import identify_faults
        from pumpguard.relationships.knowledge import pattern_to_fault
        patterns = identify_faults(reading)
        fault_ids = {pattern_to_fault()[p] for p in patterns if p in pattern_to_fault()}
        assert expected in fault_ids
        result = service.analyze(_assessment("pump-01", patterns))
        assert expected in result.observed_faults


def test_catalog_endpoint_exposes_full_knowledge_base():
    with TestClient(create_app()) as client:
        catalog = client.get("/api/v1/relationships/catalog").json()
    assert catalog["generator"] == "deterministic_graph"
    assert len(catalog["faults"]) >= 9
    assert len(catalog["relationships"]) >= 9
    for rel in catalog["relationships"]:
        assert rel["provenance"] in {"engineering_hypothesis", "observed_correlation"}
