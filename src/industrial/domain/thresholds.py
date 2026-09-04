"""Domain policy: per-metric warning/critical thresholds."""
from __future__ import annotations
from typing import Mapping

# Industry-typical limits (configurable). Units are in the engineering unit
# reported by the sensor (e.g. temperature=C, vibration=mm/s, pressure=bar).
DEFAULT_THRESHOLDS: Mapping[str, tuple[float, float]] = {
    "temperature": (75.0, 95.0),   # warn>=75, critical>=95
    "vibration":  (5.0, 8.0),     # warn>=5, critical>=8
    "pressure":   (8.0, 12.0),
    "current":    (40.0, 60.0),
    "rpm":        (2500.0, 3000.0),
}


def classify(metric: str, value: float,
             thresholds: Mapping[str, tuple[float, float]] | None = None) -> str:
    """Return NORMAL / WARNING / CRITICAL for a single reading."""
    table = thresholds or DEFAULT_THRESHOLDS
    if metric not in table:
        return "NORMAL"
    warn, crit = table[metric]
    if value >= crit:
        return "CRITICAL"
    if value >= warn:
        return "WARNING"
    return "NORMAL"
