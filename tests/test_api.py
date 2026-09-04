"""TDD integration tests for the FastAPI REST API (TestClient, no live server)."""
from fastapi.testclient import TestClient
from industrial.api.app import create_app


class TestApi:
    def setup_method(self):
        self.client = TestClient(create_app())

    def test_root(self):
        r = self.client.get("/")
        assert r.status_code == 200
        assert r.json()["service"] == "industrial-analytics"

    def test_openapi_available(self):
        r = self.client.get("/openapi.json")
        assert r.status_code == 200
        assert r.json()["info"]["title"].startswith("Industrial Equipment")

    def test_docs_available(self):
        assert self.client.get("/docs").status_code == 200

    def test_health(self):
        r = self.client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "cache" in body

    def test_ingest_then_analytics(self):
        # ingest several readings
        for v in [20.0, 21.0, 19.0, 20.5, 22.0, 18.5]:
            r = self.client.post("/api/v1/telemetry", json={
                "device_id": "pump-1", "metric": "temperature",
                "value": v, "unit": "C"})
            assert r.status_code == 201, r.text
        # analytics should now return stats
        r = self.client.get("/api/v1/analytics", params={"device_id": "pump-1", "metric": "temperature"})
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 6
        assert body["anomalies_iqr"] == 0  # tight cluster, no IQR outliers

    def test_ingest_validates_value(self):
        r = self.client.post("/api/v1/telemetry", json={
            "device_id": "", "metric": "temperature", "value": 10.0})
        assert r.status_code == 422

    def test_ingest_critical_status(self):
        r = self.client.post("/api/v1/telemetry", json={
            "device_id": "furnace-1", "metric": "temperature", "value": 96.0})
        assert r.status_code == 201
        assert r.json()["status"] == "CRITICAL"

    def test_analytics_404_when_no_data(self):
        r = self.client.get("/api/v1/analytics", params={"device_id": "ghost", "metric": "temperature"})
        assert r.status_code == 404

    def test_device_status(self):
        self.client.post("/api/v1/telemetry", json={
            "device_id": "pump-1", "metric": "temperature", "value": 80.0})
        r = self.client.get("/api/v1/status/pump-1")
        assert r.status_code == 200
        assert r.json()["status"] == "WARNING"

    def test_device_status_404(self):
        r = self.client.get("/api/v1/status/ghost")
        assert r.status_code == 404

    def test_zscore_anomaly_detection_via_api(self):
        # 50 stable + 1 spike
        for v in [20.0] * 50:
            self.client.post("/api/v1/telemetry", json={
                "device_id": "pump-2", "metric": "temperature", "value": v})
        self.client.post("/api/v1/telemetry", json={
            "device_id": "pump-2", "metric": "temperature", "value": 200.0})
        r = self.client.get("/api/v1/analytics", params={"device_id": "pump-2", "metric": "temperature"})
        assert r.status_code == 200
        assert r.json()["anomalies_zscore"] >= 1
