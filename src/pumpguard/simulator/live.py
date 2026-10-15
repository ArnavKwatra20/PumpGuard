"""Bounded process-local sessions adapting the simulator engine to live API samples."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import secrets
from threading import RLock

from pumpguard.models.telemetry import TelemetryReading
from pumpguard.simulator.engine import PumpSimulationEngine, SimulationConfig
from pumpguard.simulator.generator import SCENARIOS, Scenario


@dataclass
class _Session:
    scenario: Scenario
    requested_seed: int | None
    engine: PumpSimulationEngine


class LiveSimulationService:
    """One bounded, deterministic engine per pump/client session."""
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], _Session] = {}
        self._lock = RLock()
        self._session_limit = 256

    def snapshot(self, pump_id: str, client_session_id: str | None = None) -> dict[str, object] | None:
        with self._lock:
            session = self._sessions.get((pump_id, client_session_id or "legacy"))
            return session.engine.snapshot() if session else None

    def next_sample(
        self, pump_id: str, scenario: Scenario, random_seed: int | None = None,
        timestamp: datetime | None = None, *, client_session_id: str | None = None,
        reset_session: bool = False, speed: float = 1.0, load_percent: float = 65.0,
        cooling_effectiveness: float = 0.8, inlet_restriction_percent: float = 0.0, rpm_setpoint: float = 1780.0,
        fault_severity: float = 1.0, fault_enabled: bool | None = None,
    ) -> TelemetryReading:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario {scenario!r}")
        if not pump_id or len(pump_id) > 64:
            raise ValueError("pump_id must have 1 to 64 characters")
        if client_session_id is not None and (not client_session_id or len(client_session_id) > 64):
            raise ValueError("client_session_id must have 1 to 64 characters when provided")
        session_key = (pump_id, client_session_id or "legacy")
        with self._lock:
            session = self._sessions.get(session_key)
            if reset_session or session is None or session.scenario != scenario or session.requested_seed != random_seed:
                seed = random_seed if random_seed is not None else secrets.randbits(32)
                config = SimulationConfig(scenario=scenario, speed=speed, rpm_setpoint=rpm_setpoint, load_percent=load_percent,
                    cooling_effectiveness=cooling_effectiveness, inlet_restriction_percent=inlet_restriction_percent,
                    fault_severity=fault_severity, fault_enabled=fault_enabled if fault_enabled is not None else scenario != "normal")
                session = _Session(scenario, random_seed, PumpSimulationEngine(seed, config))
                self._sessions[session_key] = session
                if len(self._sessions) > self._session_limit:
                    self._sessions.pop(next(iter(self._sessions)))
            else:
                session.engine.update(speed=speed, rpm_setpoint=rpm_setpoint, load_percent=load_percent,
                    cooling_effectiveness=cooling_effectiveness, inlet_restriction_percent=inlet_restriction_percent,
                    fault_severity=fault_severity, fault_enabled=fault_enabled if fault_enabled is not None else scenario != "normal")
                self._sessions.pop(session_key)
                self._sessions[session_key] = session
            return session.engine.tick(pump_id, timestamp)
