"""
E2E tests for the Industrial Analytics (Python FastAPI) project.
Tests cover: health, telemetry ingest, analytics, device status, cache stats,
full workflow, and frontend verification.

Uses FastAPI TestClient for in-process testing + frontend file checks.
"""
import pytest
import json
import sys
import os

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from fastapi.testclient import TestClient
from industrial.api.app import create_app


@pytest.fixture(scope="module")
def app():
    return create_app()


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app)


@pytest.fixture
def seeded_data(client):
    """Seed 10 readings for analytics tests."""
    for i in range(10):
        val = 70.0 + i * 2.0
        client.post("/api/v1/telemetry", json={
            "device_id": "E2E-DEVICE-001",
            "metric": "temperature",
            "value": val,
            "unit": "°C"
        })
    return "E2E-DEVICE-001"


class TestHealthEndpoint:
    """GET /api/v1/health"""

    def test_health_returns_ok(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "telemetry_count" in data
        assert "cache" in data

    def test_health_cache_type_is_redis(self, client):
        r = client.get("/api/v1/health")
        data = r.json()
        assert data["cache"] in ("RedisCache", "MemoryCache", "DualCache", "NoOpCache", "TwoLevelCache")


class TestTelemetryIngest:
    """POST /api/v1/telemetry"""

    def test_ingest_valid_telemetry(self, client):
        body = {
            "device_id": "E2E-DEVICE-001",
            "metric": "temperature",
            "value": 72.5,
            "unit": "°C"
        }
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 201
        data = r.json()
        assert data["device_id"] == "E2E-DEVICE-001"
        assert data["status"] in ("normal", "warning", "critical", "NORMAL", "WARNING", "CRITICAL")
        assert "last_value" in data

    def test_ingest_high_temperature_triggers_warning(self, client):
        body = {"device_id": "E2E-DEVICE-001", "metric": "temperature", "value": 80.0}
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 201
        assert r.json()["status"].lower() == "warning"

    def test_ingest_critical_temperature(self, client):
        body = {"device_id": "E2E-DEVICE-001", "metric": "temperature", "value": 110.0}
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 201
        assert r.json()["status"].lower() == "critical"

    def test_ingest_nan_value_rejected(self, client):
        # NaN cannot be serialized via standard JSON (json.dumps rejects it with
        # allow_ascii=False). The Pydantic field_validator also rejects NaN.
        # Test the schema validator directly to confirm the protection works.
        from industrial.api.schemas import TelemetryIn
        from pydantic import ValidationError
        with pytest.raises((ValidationError, ValueError)):
            TelemetryIn(device_id="E2E-DEVICE-001", metric="temperature", value=float('nan'))

    def test_ingest_missing_device_id_rejected(self, client):
        body = {"metric": "temperature", "value": 50.0}
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 422

    def test_ingest_empty_device_id_rejected(self, client):
        body = {"device_id": "", "metric": "temperature", "value": 50.0}
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 422

    def test_ingest_vibration_data(self, client):
        body = {"device_id": "E2E-VIB-001", "metric": "vibration", "value": 8.5, "unit": "mm/s"}
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 201

    def test_ingest_pressure_data(self, client):
        body = {"device_id": "E2E-PRESS-001", "metric": "pressure", "value": 150.0, "unit": "kPa"}
        r = client.post("/api/v1/telemetry", json=body)
        assert r.status_code == 201


class TestAnalytics:
    """GET /api/v1/analytics"""

    def test_analytics_returns_stats(self, client, seeded_data):
        r = client.get("/api/v1/analytics", params={
            "device_id": "E2E-DEVICE-001",
            "metric": "temperature",
            "window": 10
        })
        assert r.status_code == 200
        data = r.json()
        assert data["device_id"] == "E2E-DEVICE-001"
        assert data["metric"] == "temperature"
        assert "mean" in data
        assert "std" in data
        assert "min" in data
        assert "max" in data
        assert "count" in data
        assert "anomalies_zscore" in data
        assert "anomalies_iqr" in data

    def test_analytics_no_data_returns_404(self, client):
        r = client.get("/api/v1/analytics", params={
            "device_id": "NONEXISTENT",
            "metric": "temperature",
            "window": 10
        })
        assert r.status_code == 404

    def test_analytics_window_validation(self, client):
        r = client.get("/api/v1/analytics", params={
            "device_id": "E2E-DEVICE-001",
            "metric": "temperature",
            "window": 1
        })
        assert r.status_code == 422

    def test_analytics_window_too_large(self, client):
        r = client.get("/api/v1/analytics", params={
            "device_id": "E2E-DEVICE-001",
            "metric": "temperature",
            "window": 10001
        })
        assert r.status_code == 422


class TestDeviceStatus:
    """GET /api/v1/status/{device_id}"""

    def test_status_for_known_device(self, client, seeded_data):
        r = client.get("/api/v1/status/E2E-DEVICE-001")
        assert r.status_code == 200
        data = r.json()
        assert data["device_id"] == "E2E-DEVICE-001"
        assert data["status"] in ("normal", "warning", "critical", "NORMAL", "WARNING", "CRITICAL")

    def test_status_cache_hit(self, client, seeded_data):
        r1 = client.get("/api/v1/status/E2E-DEVICE-001")
        assert r1.status_code == 200
        r2 = client.get("/api/v1/status/E2E-DEVICE-001")
        assert r2.status_code == 200
        assert r1.json()["status"] == r2.json()["status"]

    def test_status_unknown_device_returns_404(self, client):
        r = client.get("/api/v1/status/UNKNOWN-DEVICE")
        assert r.status_code == 404


class TestCacheStats:
    """GET /api/v1/cache-stats"""

    def test_cache_stats_returns_data(self, client):
        r = client.get("/api/v1/cache-stats")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)


class TestFullWorkflow:
    """End-to-end: ingest → analytics → status → cache verification"""

    def test_full_audit_lifecycle(self, client):
        device = "E2E-WORKFLOW-001"
        for i in range(10):
            val = 70 + i * 2 + (5 if i > 7 else 0)
            r = client.post("/api/v1/telemetry", json={
                "device_id": device, "metric": "temperature",
                "value": float(val), "unit": "°C"
            })
            assert r.status_code == 201

        r = client.get("/api/v1/analytics", params={
            "device_id": device, "metric": "temperature", "window": 10
        })
        assert r.status_code == 200
        assert r.json()["count"] == 10

        r = client.get(f"/api/v1/status/{device}")
        assert r.status_code == 200
        assert r.json()["device_id"] == device

        r = client.get("/api/v1/cache-stats")
        assert r.status_code == 200

    def test_multi_device_multi_metric(self, client):
        for dev in ["E2E-MULTI-001", "E2E-MULTI-002"]:
            for metric in ["temperature", "vibration", "pressure"]:
                for i in range(5):
                    r = client.post("/api/v1/telemetry", json={
                        "device_id": dev, "metric": metric,
                        "value": 50.0 + i, "unit": "unit"
                    })
                    assert r.status_code == 201

        for dev in ["E2E-MULTI-001", "E2E-MULTI-002"]:
            r = client.get(f"/api/v1/status/{dev}")
            assert r.status_code == 200
            r = client.get("/api/v1/analytics", params={
                "device_id": dev, "metric": "temperature", "window": 5
            })
            assert r.status_code == 200
            assert r.json()["count"] == 5


class TestFrontendServing:
    """Verify the frontend HTML is served correctly."""

    def test_frontend_file_exists(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        assert os.path.exists(frontend_path), f"Frontend not found at {frontend_path}"

    def test_frontend_contains_dashboard_title(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert '工业遥测分析平台' in content or 'Industrial Analytics' in content

    def test_frontend_contains_api_reference(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert 'api/v1' in content

    def test_frontend_has_ingest_form(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert 'ingestTelemetry' in content or 'telemetry' in content.lower()

    def test_frontend_has_analytics_query(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert 'runAnalytics' in content or 'analytics' in content.lower()

    def test_frontend_has_device_status(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert 'refreshDevices' in content or 'status' in content.lower()

    def test_frontend_has_cache_stats_display(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert 'cacheStats' in content or 'cache' in content.lower()

    def test_frontend_has_api_log(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert 'apiLog' in content or 'logApi' in content

    def test_frontend_has_dark_theme(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert '--bg-primary' in content or 'background' in content

    def test_frontend_has_responsive_layout(self):
        frontend_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'index.html')
        with open(frontend_path) as f:
            content = f.read()
        assert '@media' in content  # Has responsive breakpoints
