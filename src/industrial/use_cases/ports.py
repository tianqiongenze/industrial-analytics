"""Port interfaces (abstract). Implementations live in infrastructure."""
from __future__ import annotations
import abc
from typing import Iterable, Sequence
from industrial.domain.models import TelemetryReading, DeviceStatus, Anomaly


class TelemetryRepository(abc.ABC):
    """Persistence port for telemetry readings (PostgreSQL/SQLite)."""
    @abc.abstractmethod
    def save(self, reading: TelemetryReading) -> None: ...
    @abc.abstractmethod
    def fetch_window(self, device_id: str, metric: str, limit: int = 100) -> Sequence[TelemetryReading]: ...
    @abc.abstractmethod
    def count(self, device_id: str | None = None) -> int: ...


class CachePort(abc.ABC):
    """Caching port (Redis + in-process L1)."""
    @abc.abstractmethod
    def get(self, key: str) -> str | None: ...
    @abc.abstractmethod
    def set(self, key: str, value: str, ttl: int = 60) -> None: ...
    @abc.abstractmethod
    def delete(self, key: str) -> None: ...
    @abc.abstractmethod
    def incr(self, key: str) -> int: ...


class EventPublisher(abc.ABC):
    """Optional event publisher port (for anomaly alerts)."""
    @abc.abstractmethod
    def publish(self, topic: str, payload: str) -> None: ...
