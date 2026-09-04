"""ORM models mapping the domain to relational tables."""
from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import String, Float, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from industrial.infrastructure.database import Base


def _now():
    return datetime.now(timezone.utc)


class TelemetryModel(Base):
    __tablename__ = "telemetry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    metric: Mapped[str] = mapped_column(String(32), index=True)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
