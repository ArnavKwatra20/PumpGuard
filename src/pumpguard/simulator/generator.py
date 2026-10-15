"""Seedable synthetic signal generation."""
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import math
import numpy as np
from typing import Literal, TypeAlias
Scenario: TypeAlias = Literal["normal", "overheating", "bearing_wear", "cavitation", "imbalance"]
from pumpguard.models.telemetry import TelemetryReading
SCENARIOS=("normal","overheating","bearing_wear","cavitation","imbalance")

@dataclass(frozen=True)
class SimulatorConditions:
    """Explicit synthetic operating conditions; values are not field measurements."""
    noise_scale: float = 1.0
    baseline_temperature_c: float = 68.0
    baseline_vibration_mm_s: float = 2.1
    baseline_sound_db: float = 68.0
    operating_rpm: float = 1780.0
    fault_intensity: float = 1.0
    temperature_drift_c_per_sample: float = 0.0
    vibration_drift_mm_s_per_sample: float = 0.0
    rpm_drift_per_sample: float = 0.0

    def __post_init__(self) -> None:
        values = (self.noise_scale, self.baseline_temperature_c, self.baseline_vibration_mm_s,
                  self.baseline_sound_db, self.operating_rpm, self.fault_intensity, self.temperature_drift_c_per_sample,
                  self.vibration_drift_mm_s_per_sample, self.rpm_drift_per_sample)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("simulator condition values must be finite")
        if self.noise_scale < 0 or self.fault_intensity < 0:
            raise ValueError("noise_scale and fault_intensity must be non-negative")


class TelemetryGenerator:
    """Create synthetic readings; labels are returned separately."""
    def __init__(self, seed: int | None = None, noise_scale: float = 1.0,
                 conditions: SimulatorConditions | None = None) -> None:
        self.conditions = conditions or SimulatorConditions(noise_scale=noise_scale)
        self.rng=np.random.default_rng(seed)

    def _normal(self, mean: float, standard_deviation: float) -> float:
        return self.noise(mean, standard_deviation)
    def noise(self, mean: float, standard_deviation: float) -> float:
        """Sample seeded Gaussian variation using this generator's noise scale."""
        return float(self.rng.normal(mean, standard_deviation * self.conditions.noise_scale))
    def generate_one(self, scenario: Scenario = "normal", pump_id: str = "pump-01", timestamp: datetime | None = None) -> tuple[TelemetryReading, str]:
        """Generate one sensor sample and ground-truth label."""
        if scenario not in SCENARIOS: raise ValueError(f"Unknown scenario {scenario!r}; choose from {', '.join(SCENARIOS)}")
        if not pump_id or len(pump_id)>64: raise ValueError("pump_id must have 1 to 64 characters")
        conditions = self.conditions
        intensity = conditions.fault_intensity
        t=self._normal(conditions.baseline_temperature_c,2); v=self._normal(conditions.baseline_vibration_mm_s,.25)
        s=self._normal(conditions.baseline_sound_db,2); r=self._normal(conditions.operating_rpm,12)
        if scenario=="overheating": t+=24*intensity+self._normal(0,2)
        elif scenario=="bearing_wear": v+=5*intensity+self._normal(0,.45); s+=10*intensity+self._normal(0,1.5); r-=self._normal(10*intensity,4)
        elif scenario=="cavitation": v+=3.2*intensity+self._normal(0,.35); s+=17*intensity+self._normal(0,2); r-=45*intensity+self._normal(0,8)
        elif scenario=="imbalance": v+=7*intensity+self._normal(0,.5); s+=3*intensity+self._normal(0,1.2)
        item=TelemetryReading(timestamp=timestamp or datetime.now(timezone.utc),pump_id=pump_id,
          temperature_c=round(float(t),2),vibration_mm_s=round(float(v),2),sound_db=round(float(s),2),rpm=round(float(r),1))
        return item,scenario
    def generate_sequence(self, scenario: Scenario = "normal", count: int = 10, interval_seconds: float = 1.0, pump_id: str = "pump-01", start_time: datetime | None = None) -> list[tuple[TelemetryReading, str]]:
        """Generate count samples at the requested interval."""
        if scenario not in SCENARIOS: raise ValueError(f"Unknown scenario {scenario!r}")
        if isinstance(count,bool) or not isinstance(count,int) or not 1<=count<=10000: raise ValueError("count must be from 1 to 10000")
        if not np.isfinite(interval_seconds) or not .1<=interval_seconds<=86400: raise ValueError("interval_seconds must be from 0.1 to 86400")
        start=start_time or datetime.now(timezone.utc)
        generated = []
        for index in range(count):
            item, label = self.generate_one(scenario,pump_id,start+timedelta(seconds=index*interval_seconds))
            conditions = self.conditions
            if index and (conditions.temperature_drift_c_per_sample or conditions.vibration_drift_mm_s_per_sample or conditions.rpm_drift_per_sample):
                item = TelemetryReading.model_validate({
                    **item.model_dump(mode="python"),
                    "temperature_c": item.temperature_c + index * conditions.temperature_drift_c_per_sample,
                    "vibration_mm_s": item.vibration_mm_s + index * conditions.vibration_drift_mm_s_per_sample,
                    "rpm": item.rpm + index * conditions.rpm_drift_per_sample,
                })
            generated.append((item, label))
        return generated
