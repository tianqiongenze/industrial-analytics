"""Real-time analytics engine: rolling stats + anomaly detection.
Pure logic operating on plain lists / numpy arrays so it is fast and unit-testable
without a running server or database."""
from __future__ import annotations
import math
from typing import Sequence
import numpy as np
from industrial.domain.models import TelemetryReading, Anomaly
from industrial.domain.thresholds import classify


def to_series(readings: Sequence[TelemetryReading]) -> np.ndarray:
    """Extract the scalar values of a sequence of readings into a numpy array."""
    return np.array([r.value for r in readings], dtype=float)


def rolling_stats(values: np.ndarray, window: int = 30) -> dict[str, float]:
    """Return mean/std/min/max over the last `window` values."""
    if values.size == 0:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "count": 0}
    w = values[-window:]
    return {
        "mean": float(np.mean(w)),
        "std": float(np.std(w, ddof=1)) if w.size > 1 else 0.0,
        "min": float(np.min(w)),
        "max": float(np.max(w)),
        "count": int(w.size),
    }


def detect_zscore_anomalies(readings: Sequence[TelemetryReading],
                           threshold: float = 3.0) -> list[Anomaly]:
    """Flag readings whose z-score exceeds `threshold` standard deviations.
    Uses the historical mean/std of the prior readings as the expected baseline.
    Returns a list of Anomaly events."""
    if len(readings) < 2:
        return []
    values = to_series(readings)
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    anomalies: list[Anomaly] = []
    if std == 0.0:
        return anomalies
    for r in readings:
        z = (r.value - mean) / std
        if abs(z) > threshold:
            anomalies.append(Anomaly(
                device_id=r.device_id, metric=r.metric, value=r.value,
                expected_mean=mean, expected_std=std, zscore=z,
                timestamp=r.timestamp, rule="zscore"))
    return anomalies


def detect_iqr_anomalies(readings: Sequence[TelemetryReading]) -> list[Anomaly]:
    """Flag readings outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR] (Tukey fence)."""
    if len(readings) < 4:
        return []
    values = to_series(readings)
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mean, std = float(np.mean(values)), float(np.std(values, ddof=1))
    anomalies: list[Anomaly] = []
    for r in readings:
        if r.value < lower or r.value > upper:
            z = (r.value - mean) / std if std else 0.0
            anomalies.append(Anomaly(
                device_id=r.device_id, metric=r.metric, value=r.value,
                expected_mean=mean, expected_std=std, zscore=z,
                timestamp=r.timestamp, rule="iqr"))
    return anomalies


def evaluate_device_status(readings: Sequence[TelemetryReading]) -> str:
    """Aggregate device status from the most recent reading using threshold policy."""
    if not readings:
        return "NORMAL"
    latest = readings[-1]
    return classify(latest.metric, latest.value)
