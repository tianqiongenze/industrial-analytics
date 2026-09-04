"""TDD tests for the analytics engine (rolling stats, z-score & IQR anomalies)."""
from datetime import datetime, timezone, timedelta
import math
import numpy as np
from industrial.domain.models import TelemetryReading
from industrial.use_cases import analytics_engine as ae


def _readings(values, device="dev-1", metric="temperature"):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [TelemetryReading(device, metric, v, base + timedelta(minutes=i))
            for i, v in enumerate(values)]


def _r_single(v):
    return TelemetryReading("d", "temperature", v, datetime.now(timezone.utc))


class TestRollingStats:
    def test_empty_returns_zeros(self):
        s = ae.rolling_stats(np.array([]))
        assert s["mean"] == 0.0 and s["count"] == 0

    def test_stats_computation(self):
        # ddof=1 sample std of [10,20,30]: mean=20, variance=(100+0+100)/2=100, std=10
        s = ae.rolling_stats(np.array([10, 20, 30]), window=10)
        assert s["mean"] == 20.0
        assert s["min"] == 10.0
        assert s["max"] == 30.0
        assert s["count"] == 3
        assert math.isclose(s["std"], 10.0, rel_tol=1e-9)

    def test_single_value_has_zero_std(self):
        s = ae.rolling_stats(np.array([5.0]))
        assert s["mean"] == 5.0
        assert s["std"] == 0.0  # one value -> ddof=1 would be nan, we guard to 0
        assert s["count"] == 1

    def test_window_truncates(self):
        s = ae.rolling_stats(np.array(list(range(100))), window=5)
        assert s["count"] == 5
        # last 5 of 0..99 are 95..99, mean = 97
        assert s["mean"] == 97.0


class TestZScoreAnomalies:
    def test_no_anomalies_on_naturally_varying_data(self):
        # values with enough natural variation that none exceed 3 sigma
        rs = _readings([20.0, 20.5, 19.5, 20.2, 19.8, 20.1, 19.9, 20.3,
                        19.7, 20.4, 19.6, 20.0, 20.2, 19.8, 20.1])
        assert ae.detect_zscore_anomalies(rs) == []

    def test_detects_spike(self):
        # 50 stable + 1 huge spike
        rs = _readings([20.0] * 50 + [200.0])
        anomalies = ae.detect_zscore_anomalies(rs, threshold=3.0)
        assert len(anomalies) == 1
        assert anomalies[0].rule == "zscore"
        assert anomalies[0].value == 200.0
        assert abs(anomalies[0].zscore) > 3.0

    def test_threshold_parameter(self):
        # stable baseline + a mild deviation that only trips a low threshold
        rs = _readings([20.0] * 50 + [21.0])
        assert ae.detect_zscore_anomalies(rs, threshold=1000.0) == []

    def test_too_few_readings(self):
        assert ae.detect_zscore_anomalies([_r_single(20.0)]) == []

    def test_zero_variance_no_anomalies(self):
        rs = _readings([20.0] * 30)
        assert ae.detect_zscore_anomalies(rs) == []


class TestIQRAnomalies:
    def test_too_few_readings(self):
        rs = _readings([10, 20, 30])
        assert ae.detect_iqr_anomalies(rs) == []

    def test_detects_outliers(self):
        rs = _readings([10, 12, 11, 13, 12, 10, 11, 999, 13, 12])
        anomalies = ae.detect_iqr_anomalies(rs)
        assert any(a.value == 999 for a in anomalies)
        assert all(a.rule == "iqr" for a in anomalies)


class TestDeviceStatusEvaluation:
    def test_empty_is_normal(self):
        assert ae.evaluate_device_status([]) == "NORMAL"

    def test_latest_reading_drives_status(self):
        rs = _readings([20.0, 90.0])  # last is 90 -> WARNING
        assert ae.evaluate_device_status(rs) == "WARNING"
        rs2 = _readings([90.0, 20.0])  # last is 20 -> NORMAL
        assert ae.evaluate_device_status(rs2) == "NORMAL"
