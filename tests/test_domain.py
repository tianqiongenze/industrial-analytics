"""TDD tests for domain entities & threshold policy."""
from datetime import datetime, timezone
import pytest
from industrial.domain.models import TelemetryReading
from industrial.domain.thresholds import classify, DEFAULT_THRESHOLDS


def _r(device="dev-1", metric="temperature", value=50.0):
    return TelemetryReading(device_id=device, metric=metric, value=value,
                            timestamp=datetime.now(timezone.utc))


class TestTelemetryReading:
    def test_valid_reading(self):
        r = _r()
        assert r.device_id == "dev-1"
        assert r.value == 50.0

    def test_missing_device_id_raises(self):
        with pytest.raises(ValueError, match="device_id"):
            TelemetryReading("", "temperature", 10.0, datetime.now(timezone.utc))

    def test_missing_metric_raises(self):
        with pytest.raises(ValueError, match="metric"):
            TelemetryReading("dev", "", 10.0, datetime.now(timezone.utc))

    def test_nan_value_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            TelemetryReading("dev", "temperature", float("nan"), datetime.now(timezone.utc))

    def test_missing_timestamp_raises(self):
        with pytest.raises(ValueError, match="timestamp"):
            TelemetryReading("dev", "temperature", 10.0, None)

    def test_immutable(self):
        r = _r()
        with pytest.raises(Exception):
            r.value = 99.0  # frozen dataclass


class TestThresholdPolicy:
    @pytest.mark.parametrize("metric,value,expected", [
        ("temperature", 30.0, "NORMAL"),
        ("temperature", 80.0, "WARNING"),
        ("temperature", 96.0, "CRITICAL"),
        ("vibration", 2.0, "NORMAL"),
        ("vibration", 6.0, "WARNING"),
        ("vibration", 9.0, "CRITICAL"),
        ("unknown_metric", 9999.0, "NORMAL"),
    ])
    def test_classify(self, metric, value, expected):
        assert classify(metric, value) == expected

    def test_custom_thresholds(self):
        assert classify("temperature", 50.0,
                        {"temperature": (40.0, 60.0)}) == "WARNING"
