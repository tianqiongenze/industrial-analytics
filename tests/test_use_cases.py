"""TDD tests for the ingest-telemetry use case with fake adapters."""
from datetime import datetime, timezone
import pytest
from industrial.domain.models import TelemetryReading
from industrial.use_cases.ingest_telemetry import IngestTelemetry
from industrial.use_cases.ports import TelemetryRepository, CachePort


class FakeRepo(TelemetryRepository):
    def __init__(self):
        self.store = []
    def save(self, reading):
        self.store.append(reading)
    def fetch_window(self, device_id, metric, limit=100):
        ws = [r for r in self.store if r.device_id == device_id and r.metric == metric]
        return ws[-limit:]
    def count(self, device_id=None):
        return len(self.store)


class FakeCache(CachePort):
    def __init__(self):
        self.d = {}
        self.counters = {}
    def get(self, key): return self.d.get(key)
    def set(self, key, value, ttl=60): self.d[key] = value
    def delete(self, key):
        self.d.pop(key, None)
    def incr(self, key):
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]


def _reading(metric="temperature", value=50.0):
    return TelemetryReading("dev-1", metric, value, datetime.now(timezone.utc))


class TestIngestTelemetry:
    def test_persists_and_classifies_normal(self):
        uc = IngestTelemetry(FakeRepo(), FakeCache())
        st = uc.execute(_reading("temperature", 30.0))
        assert st.status == "NORMAL"
        assert st.device_id == "dev-1"
        assert st.last_value == 30.0

    def test_warning_status_caches_and_increments(self):
        repo, cache = FakeRepo(), FakeCache()
        uc = IngestTelemetry(repo, cache)
        st = uc.execute(_reading("temperature", 80.0))
        assert st.status == "WARNING"
        assert cache.get("status:dev-1") == "WARNING"
        assert cache.counters.get("alerts:dev-1:WARNING") == 1

    def test_critical_status(self):
        uc = IngestTelemetry(FakeRepo(), FakeCache())
        assert uc.execute(_reading("temperature", 96.0)).status == "CRITICAL"

    def test_window_provides_anomaly_count(self):
        repo = FakeRepo()
        uc = IngestTelemetry(repo, FakeCache())
        uc.execute(_reading("temperature", 80.0))
        uc.execute(_reading("temperature", 80.0))
        st = uc.execute(_reading("temperature", 80.0))
        assert st.anomalies == 3  # all three are WARNING
