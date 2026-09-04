"""Use case: ingest a telemetry reading (validate, persist, classify, cache).

Cache-aside: a write invalidates the cached device status so the next read
recomputes from the freshly persisted data.
"""
from __future__ import annotations
from industrial.domain.models import TelemetryReading, DeviceStatus
from industrial.domain.thresholds import classify
from industrial.use_cases.ports import TelemetryRepository, CachePort


class IngestTelemetry:
    def __init__(self, repo: TelemetryRepository, cache: CachePort):
        self._repo = repo
        self._cache = cache

    def execute(self, reading: TelemetryReading) -> DeviceStatus:
        # 1. persist (write master)
        self._repo.save(reading)
        # 2. rolling window for context (read replica)
        window = self._repo.fetch_window(reading.device_id, reading.metric, limit=50)
        # 3. classify the latest reading
        status_str = classify(reading.metric, reading.value)
        # 4. write-through: invalidate stale cached status, then refresh L1+L2
        self._cache.delete(f"status:{reading.device_id}")
        self._cache.set(f"status:{reading.device_id}", status_str, ttl=300)
        # 5. increment counters for warnings/critical (for dashboards)
        if status_str != "NORMAL":
            self._cache.incr(f"alerts:{reading.device_id}:{status_str}")
        return DeviceStatus(
            device_id=reading.device_id, status=status_str,
            anomalies=sum(1 for r in window if classify(r.metric, r.value) != "NORMAL"),
            last_value=reading.value,
            window_start=window[0].timestamp if window else None,
            window_end=window[-1].timestamp if window else None,
        )
