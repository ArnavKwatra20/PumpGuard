"""Bounded process-local telemetry history."""
from collections import deque
from threading import RLock
from pumpguard.models.telemetry import TelemetryReading
class UnknownPumpError(KeyError): """Requested pump is unknown."""
class TelemetryService:
    """Store recent samples; process restart discards all history."""
    def __init__(self, history_limit: int = 1000) -> None:
        if history_limit<1:raise ValueError("history_limit must be positive")
        self.history_limit=history_limit; self.data={}; self.lock=RLock()
    def add_readings(self, items: list[TelemetryReading]) -> None:
        """Append records to bounded per-pump queues."""
        with self.lock:
            for r in items:self.data.setdefault(r.pump_id,deque(maxlen=self.history_limit)).append(r)
    def list_pumps(self) -> list[str]:
        """Return sorted known identifiers."""
        with self.lock:return sorted(self.data)
    def latest(self, pump_id: str) -> TelemetryReading:
        """Return latest record or raise unknown pump."""
        with self.lock:
            if pump_id not in self.data or not self.data[pump_id]:raise UnknownPumpError(pump_id)
            return self.data[pump_id][-1]
    def history(self, pump_id: str, limit: int = 100, offset: int = 0) -> list[TelemetryReading]:
        """Return newest-first page."""
        with self.lock:
            if pump_id not in self.data:raise UnknownPumpError(pump_id)
            return list(reversed(self.data[pump_id]))[offset:offset+limit]
