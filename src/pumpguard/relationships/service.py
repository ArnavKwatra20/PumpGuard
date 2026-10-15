"""Deterministic fault-relationship analysis service.

Maps rule-engine observed faults onto the component/fault graph, performs
cycle-safe traversal to surface plausible cascading chains, resolves per-component
alarm state, and renders a human-readable causal narrative strictly from verified
relationships. No language model is involved; nothing here infers causation.
"""
from __future__ import annotations

from pumpguard.models.assessment import HealthAssessment
from pumpguard.models.relationships import (
    ComponentState,
    Confidence,
    FaultChain,
    FaultChainNode,
    RelationshipAnalysis,
    Severity,
)
from pumpguard.relationships.knowledge import (
    component_index,
    fault_index,
    pattern_to_fault,
    relationships,
)

_SEVERITY_RANK: dict[str, int] = {"normal": 0, "warning": 1, "critical": 2}
_CONFIDENCE_RANK: dict[str, int] = {"low": 0, "moderate": 1, "high": 2}
_MAX_CHAIN_DEPTH = 6
_MAX_CHAINS = 16


def _escalate(current: str, candidate: str) -> str:
    return candidate if _SEVERITY_RANK[candidate] > _SEVERITY_RANK[current] else current


def _min_confidence(confidences: list[str]) -> Confidence:
    return min(confidences, key=lambda value: _CONFIDENCE_RANK[value])  # type: ignore[return-value]


class RelationshipService:
    """Analyze one asset's assessment against the deterministic fault graph."""

    def __init__(self) -> None:
        self._faults = fault_index()
        self._components_cache: dict[str, dict[str, object]] = {}
        self._relationships = relationships()
        self._out_edges: dict[str, list] = {}
        for rel in self._relationships:
            if rel.source_fault in self._faults and rel.target_fault in self._faults:
                self._out_edges.setdefault(rel.source_fault, []).append(rel)
        self._pattern_map = pattern_to_fault()

    def _components(self, asset_id: str) -> dict[str, object]:
        if asset_id not in self._components_cache:
            self._components_cache[asset_id] = component_index(asset_id)
        return self._components_cache[asset_id]

    def _observed_fault_ids(self, assessment: HealthAssessment) -> list[str]:
        seen: list[str] = []
        for pattern in assessment.detected_faults:
            fault_id = self._pattern_map.get(pattern)
            if fault_id and fault_id not in seen:
                seen.append(fault_id)
        return sorted(seen)

    def _metric_to_components(self, asset_id: str) -> dict[str, list[str]]:
        mapping: dict[str, list[str]] = {}
        for component in self._components(asset_id).values():  # type: ignore[union-attr]
            for metric in component.monitored_metrics:  # type: ignore[union-attr]
                mapping.setdefault(metric, []).append(component.id)  # type: ignore[union-attr]
        return mapping

    def analyze(self, assessment: HealthAssessment) -> RelationshipAnalysis:
        asset_id = assessment.pump_id
        observed = self._observed_fault_ids(assessment)
        observed_set = set(observed)

        anomalous_metrics = sorted({a.metric for a in assessment.anomalies})
        metric_severity = {a.metric: a.severity for a in assessment.anomalies}

        # Collect reachable (hypothesized) faults via cycle-safe DFS from observed faults.
        hypothesized: dict[str, str] = {}  # fault_id -> seed observed fault id
        chains: list[FaultChain] = []
        for seed in observed:
            for chain in self._build_chains(seed, observed_set):
                chains.append(chain)
                for node in chain.nodes[1:]:
                    hypothesized.setdefault(node.fault_id, seed)
        chains = chains[:_MAX_CHAINS]

        components: list[ComponentState] = []
        for component in sorted(self._components(asset_id).values(), key=lambda c: c.id):  # type: ignore[union-attr,arg-type]
            comp_id = component.id  # type: ignore[union-attr]
            obs = sorted(f for f in observed_set if self._faults[f].component_id == comp_id)
            hyp = sorted(f for f, seed in hypothesized.items()
                         if self._faults[f].component_id == comp_id and f not in observed_set)
            comp_metrics = sorted({m for m in component.monitored_metrics if m in set(anomalous_metrics)})  # type: ignore[union-attr]
            severity: Severity = "normal"
            for metric in comp_metrics:
                severity = _escalate(severity, metric_severity[metric])  # type: ignore[arg-type]
            if obs:
                severity = _escalate(severity, "warning")
            rationale = self._component_rationale(comp_id, obs, hyp, comp_metrics)
            components.append(ComponentState(
                component_id=comp_id, component_type=component.type,  # type: ignore[union-attr]
                name=component.name, asset_id=asset_id, severity=severity,  # type: ignore[union-attr]
                observed_faults=obs, hypothesized_faults=hyp,
                anomalous_metrics=comp_metrics, rationale=rationale,
            ))

        explanation = self._explain(observed, chains, components)
        limitations = [
            "Relationships are curated engineering hypotheses, not confirmed causal mechanisms.",
            "Correlation between concurrently observed conditions does not establish causation.",
            "Analysis is derived from synthetic simulator telemetry and deterministic rules only.",
            "A qualified engineer must confirm or reject each hypothesis against physical evidence.",
        ]
        return RelationshipAnalysis(
            asset_id=asset_id, timestamp=assessment.timestamp, synthetic=True,
            components=components, observed_faults=observed, chains=chains,
            explanation=explanation, limitations=limitations,
        )

    def _build_chains(self, seed: str, observed_set: set[str]) -> list[FaultChain]:
        """Cycle-safe enumeration of chains rooted at an observed fault."""
        chains: list[FaultChain] = []

        def walk(fault_id: str, path: list[str], nodes: list[FaultChainNode]) -> None:
            for rel in self._out_edges.get(fault_id, []):
                if len(chains) >= _MAX_CHAINS or rel.target_fault in path:  # cycle guard
                    continue
                target = self._faults[rel.target_fault]
                node = FaultChainNode(
                    fault_id=target.id, fault_name=target.name, component_id=target.component_id,
                    relationship_type=rel.type, provenance=rel.provenance, confidence=rel.confidence,
                    observed=target.id in observed_set,
                )
                new_nodes = nodes + [node]
                if len(new_nodes) <= _MAX_CHAIN_DEPTH:
                    new_path = path + [rel.target_fault]
                    chains.append(FaultChain(
                        id=f"{seed}:" + "->".join(new_path), seed_fault_id=seed, nodes=list(new_nodes),
                        overall_confidence=_min_confidence([n.confidence for n in new_nodes]),
                        rationale=self._chain_rationale(new_nodes),
                    ))
                    walk(rel.target_fault, new_path, new_nodes)

        seed_fault = self._faults[seed]
        seed_node = FaultChainNode(
            fault_id=seed_fault.id, fault_name=seed_fault.name, component_id=seed_fault.component_id,
            relationship_type="known_dependency", provenance="rule_engine", confidence="high", observed=True,
        )
        walk(seed, [seed], [seed_node])
        # Ensure the observed seed is represented even when it has no successors.
        if not any(chain.seed_fault_id == seed for chain in chains) and len(chains) < _MAX_CHAINS:
            chains.append(FaultChain(
                id=f"{seed}:{seed}", seed_fault_id=seed, nodes=[seed_node], overall_confidence="high",
                rationale=f"{seed_fault.name} was directly detected by the rule engine on this asset.",
            ))
        return chains

    def _chain_rationale(self, nodes: list[FaultChainNode]) -> str:
        if len(nodes) < 2:
            return f"{nodes[0].fault_name} was directly observed."
        steps = [nodes[0].fault_name]
        for current in nodes[1:]:
            steps.append(f"may be associated with {current.fault_name} ({current.relationship_type})")
        return "; ".join(steps) + "."

    def _component_rationale(self, component_id: str, observed: list[str], hypothesized: list[str], metrics: list[str]) -> str:
        if not observed and not hypothesized and not metrics:
            return "No fault or threshold excursion is associated with this component."
        parts: list[str] = []
        if observed:
            parts.append("Observed: " + ", ".join(self._faults[f].name for f in observed) + ".")
        if hypothesized:
            parts.append("Hypothesized related: " + ", ".join(self._faults[f].name for f in hypothesized) + ".")
        if metrics:
            parts.append("Out-of-range metrics: " + ", ".join(metrics) + ".")
        return " ".join(parts)

    def _explain(self, observed: list[str], chains: list[FaultChain], components: list[ComponentState]) -> str:
        if not observed:
            return ("No rule-based fault pattern was detected on this asset, so no fault chain can be "
                    "grounded. Component relationships are not evaluated without an observed starting point.")
        names = ", ".join(self._faults[f].name for f in observed)
        alarmed = [c.name for c in components if c.severity != "normal"]
        multi_step = [c for c in chains if len(c.nodes) > 1]
        segments = [f"Observed fault(s): {names}."]
        if multi_step:
            example = max(multi_step, key=lambda c: len(c.nodes))
            segments.append(f"Plausible cascade: {example.rationale}")
        else:
            segments.append("No multi-step cascade is currently supported by the observed evidence.")
        if alarmed:
            segments.append(f"Components affected: {', '.join(alarmed)}.")
        segments.append("All linked conditions beyond the observed fault are unconfirmed hypotheses requiring inspection.")
        return " ".join(segments)


