"""Deterministic pump fault-relationship knowledge base.

A curated catalog of components, faults, and directed engineering relationships.
Relationships are explicit hypotheses with provenance and confidence; they are never
confirmed causal mechanisms and are never inferred by a language model. Confidence
and applicability are conservative by design.
"""
from __future__ import annotations

from pumpguard.models.relationships import (
    Component,
    ComponentType,
    FaultDefinition,
    FaultRelationship,
)

# Asset-agnostic component definitions: id, name, type, monitored_metrics.
_COMPONENTS: tuple[tuple[str, str, ComponentType, list[str]], ...] = (
    ("motor", "Drive motor", "motor", ["temperature_c", "motor_temperature_c", "current_a"]),
    ("bearing", "Shaft bearing assembly", "bearing", ["vibration_mm_s", "bearing_temperature_c", "sound_db"]),
    ("coupling", "Drive coupling", "coupling", ["vibration_mm_s"]),
    ("impeller", "Pump impeller", "impeller", ["flow_rate_m3_h", "pressure_kpa", "inlet_pressure_kpa", "outlet_pressure_kpa"]),
    ("mechanical_seal", "Mechanical seal", "mechanical_seal", ["flow_rate_m3_h", "pressure_kpa"]),
    ("cooling_system", "Cooling / ventilation", "cooling_system", ["temperature_c", "motor_temperature_c", "cooling_effectiveness"]),
    ("power_supply", "Electrical power supply", "power_supply", ["current_a", "power_kw", "rpm"]),
    ("base_mount", "Base / mounting", "base_mount", ["vibration_mm_s", "sound_db"]),
    ("lubrication_system", "Lubrication system", "lubrication_system", ["bearing_temperature_c", "vibration_mm_s"]),
)

# Stable fault identifiers mapped to the rule-engine pattern strings that ground them:
# id, name, component_id, description, detector_patterns.
_FAULTS: tuple[tuple[str, str, str, str, list[str]], ...] = (
    ("overheating", "Overheating", "cooling_system",
     "Elevated winding/casing temperature relative to load and cooling.", ["overheating_pattern"]),
    ("bearing_wear", "Bearing wear / degradation", "bearing",
     "Elevated broadband vibration and acoustic energy consistent with bearing degradation.", ["bearing_wear_pattern"]),
    ("cavitation", "Cavitation", "impeller",
     "Irregular vibration and pressure/flow loss consistent with vapour bubble collapse.", ["cavitation_pattern"]),
    ("imbalance", "Rotor imbalance", "coupling",
     "Synchronous vibration amplitude consistent with mass imbalance.", ["imbalance_pattern"]),
    ("lubrication_degradation", "Lubrication degradation", "lubrication_system",
     "Reduced lubrication quality increasing friction and bearing temperature.", []),
    ("friction_increase", "Increased friction", "bearing",
     "Elevated mechanical friction raising local bearing temperature.", []),
    ("misalignment", "Shaft misalignment", "coupling",
     "Angular/parallel misalignment producing vibration and mechanical stress.", []),
    ("cooling_degradation", "Cooling degradation", "cooling_system",
     "Reduced heat removal causing winding temperature to rise with load.", []),
    ("seal_degradation", "Seal degradation", "mechanical_seal",
     "Worn seal associated with reduced discharge/flow performance.", []),
)


def components_for(asset_id: str) -> list[Component]:
    """Return the component catalog instantiated for one asset."""
    return [Component(id=cid, name=name, type=ctype, asset_id=asset_id, monitored_metrics=metrics)
            for cid, name, ctype, metrics in _COMPONENTS]


def fault_definitions() -> list[FaultDefinition]:
    """Return all fault definitions (asset-agnostic)."""
    return [FaultDefinition(id=fid, name=name, component_id=cid, description=desc, detector_patterns=patterns)
            for fid, name, cid, desc, patterns in _FAULTS]


def fault_index() -> dict[str, FaultDefinition]:
    return {fault.id: fault for fault in fault_definitions()}


def component_index(asset_id: str) -> dict[str, Component]:
    return {component.id: component for component in components_for(asset_id)}


# Directed relationships:
# id, source_fault, target_fault, type, confidence, rationale, requires, confirm_by.
_RELATIONSHIPS: tuple[tuple[str, str, str, str, str, str, list[str], list[str]], ...] = (
    ("lubrication_to_bearing_wear", "lubrication_degradation", "bearing_wear", "hypothesized_cause", "moderate",
     "Loss of lubrication raises bearing friction and accelerates surface wear.",
     [], ["bearing_temperature_c", "vibration_mm_s"]),
    ("bearing_wear_to_friction", "bearing_wear", "friction_increase", "potential_consequence", "high",
     "Degraded bearing surfaces increase mechanical friction.",
     [], ["bearing_temperature_c"]),
    ("friction_to_overheating", "friction_increase", "overheating", "potential_consequence", "moderate",
     "Increased friction converts mechanical work into heat, raising temperature.",
     ["temperature_c"], ["temperature_c", "motor_temperature_c"]),
    ("cooling_to_overheating", "cooling_degradation", "overheating", "hypothesized_cause", "high",
     "Reduced cooling effectiveness limits heat rejection as load increases.",
     ["cooling_effectiveness"], ["cooling_effectiveness", "motor_temperature_c"]),
    ("misalignment_to_bearing_wear", "misalignment", "bearing_wear", "hypothesized_cause", "moderate",
     "Sustained misalignment loads the bearing and accelerates wear.",
     [], ["vibration_mm_s", "bearing_temperature_c"]),
    ("misalignment_to_friction", "misalignment", "friction_increase", "potential_consequence", "moderate",
     "Misalignment increases reaction loads and friction at the bearing.",
     [], ["vibration_mm_s"]),
    ("imbalance_misalignment_correlation", "imbalance", "misalignment", "observed_correlation", "low",
     "Imbalance and misalignment both elevate vibration; their concurrence is not causal.",
     [], ["vibration_mm_s"]),
    ("seal_to_cavitation", "seal_degradation", "cavitation", "hypothesized_cause", "low",
     "Seal/leakage losses can lower suction head and predispose cavitation.",
     ["inlet_pressure_kpa", "flow_rate_m3_h"], ["inlet_pressure_kpa", "flow_rate_m3_h"]),
    ("cavitation_to_bearing_wear", "cavitation", "bearing_wear", "potential_consequence", "moderate",
     "Cavitation erosion of the impeller and irregular loading can load the bearing.",
     [], ["vibration_mm_s"]),
)

_PROVENANCE_BY_TYPE = {
    "hypothesized_cause": "engineering_hypothesis",
    "potential_consequence": "engineering_hypothesis",
    "known_dependency": "engineering_hypothesis",
    "observed_correlation": "observed_correlation",
}


def relationships() -> list[FaultRelationship]:
    """Return all directed engineering relationships."""
    result: list[FaultRelationship] = []
    for rid, source, target, rtype, confidence, rationale, requires, confirm_by in _RELATIONSHIPS:
        result.append(FaultRelationship(
            id=rid, source_fault=source, target_fault=target, type=rtype,  # type: ignore[arg-type]
            provenance=_PROVENANCE_BY_TYPE[rtype], confidence=confidence,  # type: ignore[arg-type]
            rationale=rationale, requires=requires, confirm_by=confirm_by,
        ))
    return result


def pattern_to_fault() -> dict[str, str]:
    """Map a rule-engine pattern string to its stable fault identifier."""
    return {pattern: fault.id for fault in fault_definitions() for pattern in fault.detector_patterns}

