"""Domain entities for industrial equipment telemetry."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class TelemetryReading:
    """An immutable sensor reading from a piece of equipment."""
    device_id: str
    metric: str          # temperature, vibration, pressure, current ...
    value: float
    timestamp: datetime
    unit: str = ""

    def __post_init__(self):
        if not self.device_id:
            raise ValueError("device_id is required")
        if not self.metric:
            raise ValueError("metric is required")
        if self.value != self.value:  # NaN check
            raise ValueError("value cannot be NaN")
        if self.timestamp is None:
            raise ValueError("timestamp is required")


@dataclass
class DeviceStatus:
    """Computed operational status of a device over a window."""
    device_id: str
    status: str          # NORMAL, WARNING, CRITICAL
    anomalies: int = 0
    last_value: float = 0.0
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None

    @property
    def is_healthy(self) -> bool:
        return self.status == "NORMAL"


@dataclass
class Anomaly:
    """A detected anomaly event."""
    device_id: str
    metric: str
    value: float
    expected_mean: float
    expected_std: float
    zscore: float
    timestamp: datetime
    rule: str  # zscore, threshold, iqr
