"""Bounded, deterministic, physics-inspired pump experiment engine.

This is an illustrative synthetic model, not a validated pump digital twin.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import math

from pumpguard.models.telemetry import TelemetryReading
from pumpguard.simulator.generator import SCENARIOS, Scenario, TelemetryGenerator


@dataclass(frozen=True)
class SimulationConfig:
    scenario: Scenario = "normal"
    speed: float = 1.0
    rpm_setpoint: float = 1780.0
    load_percent: float = 65.0
    cooling_effectiveness: float = 0.8
    inlet_restriction_percent: float = 0.0
    fault_severity: float = 1.0
    fault_enabled: bool = True

    def __post_init__(self) -> None:
        if self.scenario not in SCENARIOS:
            raise ValueError("unsupported scenario")
        for name, value, low, high in (
            ("speed", self.speed, .25, 4), ("rpm_setpoint", self.rpm_setpoint, 1200, 2500), ("load_percent", self.load_percent, 10, 100),
            ("cooling_effectiveness", self.cooling_effectiveness, .2, 1),
            ("inlet_restriction_percent", self.inlet_restriction_percent, 0, 70),
            ("fault_severity", self.fault_severity, 0, 1),
        ):
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")


@dataclass
class SimulationState:
    time_seconds: float = 0.0
    step: int = 0
    fault_level: float = 0.0
    events: list[dict[str, object]] | None = None
    cavitation_state: float = 0.0


class PumpSimulationEngine:
    """Generate one synchronized telemetry frame per call; seeded noise is repeatable."""

    def __init__(self, seed: int, config: SimulationConfig | None = None) -> None:
        self.seed = seed
        self.config = config or SimulationConfig()
        self.state = SimulationState(events=[])
        self.generator = TelemetryGenerator(seed)
        self._last_automatic_timestamp: datetime | None = None
        self._last_fault_enabled = False
        self._last_fault_severity = self.config.fault_severity

    def update(self, **changes: object) -> None:
        previous = self.config
        self.config = replace(self.config, **changes)
        conditions = ("rpm_setpoint", "load_percent", "cooling_effectiveness", "inlet_restriction_percent")
        if any(getattr(previous, name) != getattr(self.config, name) for name in conditions):
            self.state.events.append({"time_seconds": round(self.state.time_seconds, 2), "kind": "operating_condition_changed", "scenario": self.config.scenario})
            if len(self.state.events) > 32:
                del self.state.events[:-32]

    def reset(self) -> None:
        self.state = SimulationState(events=[])
        self.generator = TelemetryGenerator(self.seed)
        self._last_automatic_timestamp = None
        self._last_fault_enabled = False
        self._last_fault_severity = self.config.fault_severity

    def snapshot(self) -> dict[str, object]:
        return {"time_seconds": round(self.state.time_seconds, 2), "step": self.state.step,
                "fault_level": round(self.state.fault_level, 3), "fault_enabled": self.config.fault_enabled,
                "scenario": self.config.scenario, "config": {"speed": self.config.speed, "rpm_setpoint": self.config.rpm_setpoint,
                "load_percent": self.config.load_percent, "cooling_effectiveness": self.config.cooling_effectiveness,
                "inlet_restriction_percent": self.config.inlet_restriction_percent,
                "fault_severity": self.config.fault_severity}, "events": list(self.state.events or [])}

    def tick(self, pump_id: str, timestamp: datetime | None = None) -> TelemetryReading:
        c, s = self.config, self.state
        dt = c.speed
        s.time_seconds += dt
        s.step += 1
        if c.fault_enabled and not self._last_fault_enabled:
            s.fault_level = c.fault_severity
        elif c.fault_enabled:
            # Controlled onset/progression, initially responsive enough for a demo.
            s.fault_level = min(c.fault_severity, s.fault_level + max(c.fault_severity / 4, .08))
        else:
            was_active = s.fault_level > 0
            s.fault_level = max(0.0, s.fault_level - .18 * dt)
            if was_active and s.fault_level == 0:
                s.events.append({"time_seconds": round(s.time_seconds, 2), "kind": "fault_recovered", "scenario": c.scenario})
        if c.fault_enabled != self._last_fault_enabled:
            s.events.append({"time_seconds": round(s.time_seconds, 2), "kind": "fault_injected" if c.fault_enabled else "fault_recovery_started", "scenario": c.scenario})
            self._last_fault_enabled = c.fault_enabled
        if c.fault_enabled and c.fault_severity != self._last_fault_severity:
            s.events.append({"time_seconds": round(s.time_seconds, 2), "kind": "severity_changed", "scenario": c.scenario})
        self._last_fault_severity = c.fault_severity
        if len(s.events) > 32:
            del s.events[:-32]

        noise = self.generator.noise
        load = c.load_percent
        rpm = c.rpm_setpoint + (load - 65) * 2 + noise(0, 8)
        restriction = c.inlet_restriction_percent
        flow = max(0.0, 48 * (load / 65) * (1 - restriction / 115))
        inlet = max(20.0, 180 - restriction * 1.15 + noise(0, 1.5))
        pressure = max(80.0, 320 * (load / 65) ** 1.4 * (1 - restriction / 150))
        fault = s.fault_level if c.fault_enabled or s.fault_level > 0 else 0.0
        scenario = c.scenario
        temp_fault = 0.0
        vibration_fault = 0.0
        sound_fault = 0.0
        rpm_fault = 0.0
        pressure_fault = 0.0
        if scenario == "overheating": temp_fault = (23 + (min(s.step * .025, 4) if c.fault_enabled else 0)) * fault
        elif scenario == "bearing_wear":
            progression = min(s.step * .02, 1.8) * fault if c.fault_enabled else 0
            vibration_fault, sound_fault, temp_fault, rpm_fault = 5.0 * fault + progression, 9.0 * fault + progression, 2.0 * fault + min(s.step * .06, 4) * fault, -8 * fault
        elif scenario == "cavitation":
            s.cavitation_state = .62 * s.cavitation_state + noise(0, 1.8) if c.fault_enabled else .62 * s.cavitation_state
            irregular = s.cavitation_state * fault
            vibration_fault, sound_fault, rpm_fault, pressure_fault = 3.1 * fault + abs(irregular) * .1, 14 * fault + irregular * .35, -35 * fault, -38 * fault + irregular * 2
            flow *= 1 - .18 * fault
        elif scenario == "imbalance":
            vibration_fault, sound_fault = 7.5 * fault + .7 * math.sin(s.step * 1.25), 3.0 * fault
        rpm = min(2500, max(1200, rpm + rpm_fault))
        pressure = max(40, pressure + pressure_fault)
        inlet = max(20, inlet + pressure_fault * .35)
        ambient = 24.0
        motor_temp = ambient + 18 + load * .28 / c.cooling_effectiveness + temp_fault + noise(0, .7)
        bearing_temp = ambient + 13 + load * .12 + (vibration_fault * .65) + noise(0, .6)
        vibration = 1.4 + load * .012 + vibration_fault + noise(0, .18)
        sound = 58 + load * .12 + sound_fault + noise(0, .8)
        power = max(.1, 3.2 + load * .095 + restriction * .018 + noise(0, .08))
        current = power * 1000 / (math.sqrt(3) * 400 * .88)
        # Keep canonical sensor channels aligned with the richer operating state.
        if timestamp is None:
            generated_timestamp = datetime.now(timezone.utc)
            if self._last_automatic_timestamp is not None and generated_timestamp <= self._last_automatic_timestamp:
                generated_timestamp = self._last_automatic_timestamp + timedelta(microseconds=1)
            self._last_automatic_timestamp = generated_timestamp
        else:
            generated_timestamp = timestamp
        return TelemetryReading.model_validate({
            "timestamp": generated_timestamp, "pump_id": pump_id,
            "temperature_c": min(150, max(-10, motor_temp)), "vibration_mm_s": min(30, max(0, vibration)),
            "sound_db": min(130, max(20, sound)), "rpm": rpm, "pressure_kpa": pressure, "operating_mode": "steady",
            "motor_temperature_c": min(150, max(-10, motor_temp)), "bearing_temperature_c": min(150, max(-10, bearing_temp)),
            "flow_rate_m3_h": flow, "inlet_pressure_kpa": inlet, "outlet_pressure_kpa": pressure,
            "load_percent": load, "power_kw": power, "current_a": current,
            "cooling_effectiveness": c.cooling_effectiveness, "inlet_restriction_percent": restriction,
            "simulation_time_seconds": s.time_seconds,
        })
