"""TDD tests for the MQTT ingestion adapter (no broker required)."""
import json
from datetime import datetime, timezone
from industrial.use_cases.ingest_telemetry import IngestTelemetry
from industrial.use_cases.ports import TelemetryRepository, CachePort
from industrial.infrastructure.mqtt_ingestor import MqttIngestor


class FakeRepo(TelemetryRepository):
    def __init__(self): self.store = []
    def save(self, r): self.store.append(r)
    def fetch_window(self, d, m, limit=100): return [r for r in self.store if r.device_id == d][-limit:]
    def count(self, device_id=None): return len(self.store)


class FakeCache(CachePort):
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def set(self, k, v, ttl=60): self.d[k] = v
    def delete(self, k): self.d.pop(k, None)
    def incr(self, k): return 1


class TestMqttIngestor:
    def test_handle_valid_json_message(self):
        ing = MqttIngestor(IngestTelemetry(FakeRepo(), FakeCache()))
        payload = json.dumps({"device_id": "pump-1", "metric": "vibration",
                              "value": 7.0, "unit": "mm/s"})
        result = ing.handle_message(payload)
        assert result["device_id"] == "pump-1"
        assert result["status"] == "WARNING"

    def test_handle_critical_temperature(self):
        ing = MqttIngestor(IngestTelemetry(FakeRepo(), FakeCache()))
        result = ing.handle_message({"device_id": "furnace-1", "metric": "temperature",
                                     "value": 96.0, "unit": "C"})
        assert result["status"] == "CRITICAL"

    def test_handle_with_explicit_timestamp(self):
        ing = MqttIngestor(IngestTelemetry(FakeRepo(), FakeCache()))
        ts = "2026-08-31T10:00:00+00:00"
        ing.handle_message({"device_id": "d", "metric": "temperature",
                            "value": 30.0, "timestamp": ts})

    def test_start_without_client_is_noop(self):
        ing = MqttIngestor(IngestTelemetry(FakeRepo(), FakeCache()))
        ing.start()  # should not raise
