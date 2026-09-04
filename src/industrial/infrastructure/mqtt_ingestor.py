"""MQTT data ingestion adapter: subscribes to a topic and ingests readings.
Decoupled from the HTTP API so it can run as a standalone worker. Uses a
pluggable MQTT client; falls back to a file/sim source when no broker present.
"""
from __future__ import annotations
import json, os, logging
from datetime import datetime, timezone
from industrial.domain.models import TelemetryReading
from industrial.use_cases.ingest_telemetry import IngestTelemetry

log = logging.getLogger(__name__)


class MqttIngestor:
    """Adapter that converts MQTT messages into TelemetryReading objects.

    A real deployment passes a paho-mqtt client; tests inject a fake
    publisher so no broker is required. Messages are JSON:
    {"device_id":"..","metric":"temperature","value":42.1,"unit":"C"}.
    """
    def __init__(self, use_case: IngestTelemetry, client=None):
        self._uc = use_case
        self._client = client

    def handle_message(self, payload: bytes | str) -> dict:
        """Process a single MQTT message payload. Returns the device status."""
        data = json.loads(payload) if isinstance(payload, (bytes, bytearray, str)) else payload
        reading = TelemetryReading(
            device_id=data["device_id"], metric=data["metric"],
            value=float(data["value"]), unit=data.get("unit", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(timezone.utc))
        st = self._uc.execute(reading)
        return {"device_id": st.device_id, "status": st.status, "anomalies": st.anomalies}

    def start(self, topic: str = "industrial/telemetry/+") -> None:
        """Subscribe to the MQTT topic. No-op when no client is configured."""
        if self._client is None:
            log.warning("MQTT client not configured; ingestor in dry mode")
            return
        self._client.subscribe(topic)
        self._client.loop_forever()
