"""Shared industrial relationships, fault, and component contracts.

These models are the common vocabulary used across capabilities: stable fault and
component identifiers, explicit provenance, and a hard separation between
*observed* (rule/telemetry-derived) facts and *hypothesized* engineering
relationships. Nothing here infers causation from an LLM.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["normal", "warning", "critical"]
Confidence = Literal["low", "moderate", "high"]
Provenance = Literal[
    "rule_engine",            # derived from the deterministic rule/telemetry assessment
    "engineering_hypothesis",  # a documented physical hypothesis, never a confirmed cause
    "simulator_invariant",    # a property the synthetic simulator encodes by construction
    "observed_correlation",   # supported by more than one concurrent observation
]
RelationshipType = Literal[
    "known_dependency",      # structural/engineering dependency between components/faults
    "observed_correlation",  # two conditions are concurrently observed, not necessarily causal
    "hypothesized_cause",    # a plausible upstream cause of a condition
    "potential_consequence",  # a plausible downstream effect of a condition
]
ComponentType = Literal[
    "motor", "bearing", "coupling", "impeller", "mechanical_seal",
    "cooling_system", "power_supply", "base_mount", "lubrication_system",
]


class Component(BaseModel):
    """A machine component with a stable identifier and its monitored metrics."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    type: ComponentType
    asset_id: str = Field(min_length=1, max_length=64)
    monitored_metrics: list[str] = Field(default_factory=list, max_length=32)


class FaultDefinition(BaseModel):
    """A named fault with a stable identifier, independent of how it was detected."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    component_id: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=400)
    # Rule-engine pattern string(s) that, when present, ground this fault as observed.
    detector_patterns: list[str] = Field(default_factory=list, max_length=8)


class FaultRelationship(BaseModel):
    """A directed relationship between two faults, with provenance and confidence.

    ``source_fault`` is the upstream condition; ``target_fault`` is the downstream
    one. Every relationship is an explicit engineering hypothesis or dependency; it
    is never treated as a confirmed causal mechanism.
    """
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    source_fault: str = Field(min_length=1, max_length=64)
    target_fault: str = Field(min_length=1, max_length=64)
    type: RelationshipType
    provenance: Provenance = "engineering_hypothesis"
    confidence: Confidence
    rationale: str = Field(min_length=1, max_length=400)
    # Optional precondition over simulator/telemetry fields; empty means always
    # applicable when both faults are present.
    requires: list[str] = Field(default_factory=list, max_length=16)
    # Telemetry/evidence fields a human can check to confirm or reject this link.
    confirm_by: list[str] = Field(default_factory=list, max_length=16)


class ComponentState(BaseModel):
    """Resolved alarm state for one component on one asset."""
    model_config = ConfigDict(extra="forbid")
    component_id: str
    component_type: ComponentType
    name: str
    asset_id: str
    severity: Severity
    observed_faults: list[str] = Field(default_factory=list, max_length=16)
    hypothesized_faults: list[str] = Field(default_factory=list, max_length=16)
    # Canonical metrics (temperature_c, vibration_mm_s, ...) currently out of range.
    anomalous_metrics: list[str] = Field(default_factory=list, max_length=16)
    rationale: str = Field(min_length=1, max_length=400)


class FaultChainNode(BaseModel):
    """One step in a plausible fault chain; ``observed`` marks rule-grounded faults."""
    model_config = ConfigDict(extra="forbid")
    fault_id: str
    fault_name: str
    component_id: str
    relationship_type: RelationshipType
    provenance: Provenance
    confidence: Confidence
    observed: bool


class FaultChain(BaseModel):
    """An ordered sequence of relationships starting from an observed fault."""
    model_config = ConfigDict(extra="forbid")
    id: str
    seed_fault_id: str
    nodes: list[FaultChainNode] = Field(min_length=1, max_length=8)
    overall_confidence: Confidence
    rationale: str = Field(min_length=1, max_length=600)


class RelationshipAnalysis(BaseModel):
    """Deterministic fault-relationship analysis for a single asset snapshot."""
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    timestamp: datetime
    generator: Literal["deterministic_graph"] = "deterministic_graph"
    synthetic: bool = True
    components: list[ComponentState] = Field(default_factory=list, max_length=32)
    observed_faults: list[str] = Field(default_factory=list, max_length=16)
    chains: list[FaultChain] = Field(default_factory=list, max_length=16)
    # Human-readable causal narrative built only from verified relationships.
    explanation: str = Field(min_length=1, max_length=2000)
    limitations: list[str] = Field(min_length=1, max_length=10)
