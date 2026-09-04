"""Pydantic v2 schemas (API boundary)."""
from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class TelemetryIn(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    metric: str = Field(..., min_length=1, max_length=32)
    value: float
    unit: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("value")
    @classmethod
    def value_not_nan(cls, v: float) -> float:
        if v != v:
            raise ValueError("value cannot be NaN")
        return v


class DeviceStatusOut(BaseModel):
    device_id: str
    status: str
    anomalies: int
    last_value: float
    window_start: datetime | None = None
    window_end: datetime | None = None


class AnalyticsOut(BaseModel):
    device_id: str
    metric: str
    mean: float
    std: float
    min: float
    max: float
    count: int
    anomalies_zscore: int
    anomalies_iqr: int


class HealthOut(BaseModel):
    status: str
    telemetry_count: int
    cache: str
