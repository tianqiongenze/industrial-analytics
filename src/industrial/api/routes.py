"""FastAPI routes wiring use cases to the HTTP boundary."""
from __future__ import annotations
from fastapi import APIRouter, HTTPException, Query
from industrial.api.schemas import TelemetryIn, DeviceStatusOut, AnalyticsOut, HealthOut
from industrial.domain.models import TelemetryReading
from industrial.use_cases.ingest_telemetry import IngestTelemetry
from industrial.use_cases import analytics_engine
from industrial.infrastructure.database import init_db

router = APIRouter(prefix="/api/v1", tags=["industrial-analytics"])


def _container():
    """Dependency-injection container (per request)."""
    from industrial.infrastructure.sqlalchemy_repository import SqlAlchemyTelemetryRepository
    from industrial.infrastructure.redis_cache import make_cache
    return IngestTelemetry(SqlAlchemyTelemetryRepository(), make_cache())


@router.post("/telemetry", response_model=DeviceStatusOut, status_code=201)
def ingest(body: TelemetryIn):
    uc = _container()
    try:
        reading = TelemetryReading(device_id=body.device_id, metric=body.metric,
                                   value=body.value, unit=body.unit, timestamp=body.timestamp)
        st = uc.execute(reading)
        return DeviceStatusOut(**st.__dict__)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/analytics", response_model=AnalyticsOut)
def analytics(device_id: str = Query(...), metric: str = Query(...),
              window: int = Query(100, ge=2, le=10000)):
    from industrial.infrastructure.sqlalchemy_repository import SqlAlchemyTelemetryRepository
    repo = SqlAlchemyTelemetryRepository()
    readings = repo.fetch_window(device_id, metric, limit=window)
    if not readings:
        raise HTTPException(status_code=404, detail="no data for device/metric")
    stats = analytics_engine.rolling_stats(analytics_engine.to_series(readings))
    z = analytics_engine.detect_zscore_anomalies(readings)
    iqr = analytics_engine.detect_iqr_anomalies(readings)
    return AnalyticsOut(device_id=device_id, metric=metric, **stats,
                        anomalies_zscore=len(z), anomalies_iqr=len(iqr))


@router.get("/status/{device_id}", response_model=DeviceStatusOut)
def device_status(device_id: str):
    """Read-through L1+L2 cache: L1 -> L2 -> DB, backfill on miss."""
    from industrial.infrastructure.redis_cache import make_cache
    from industrial.infrastructure.sqlalchemy_repository import SqlAlchemyTelemetryRepository
    from industrial.domain.thresholds import classify
    repo = SqlAlchemyTelemetryRepository()
    cache = make_cache()
    cache_key = f"status:{device_id}"
    cached = cache.get(cache_key)
    # Try to fetch latest reading from DB (READ node) only on cache miss.
    readings = []
    if cached is None:
        for m in ("temperature", "vibration", "pressure", "current", "rpm"):
            readings = repo.fetch_window(device_id, m, limit=1)
            if readings:
                break
    if not readings and cached is None:
        raise HTTPException(status_code=404, detail="device has no telemetry")
    if readings:
        r = readings[-1]
        st = classify(r.metric, r.value)
        # populate both L2 + L1
        cache.set(cache_key, st, ttl=300)
        last_val = r.value
    else:
        st = cached
        last_val = 0.0
    return DeviceStatusOut(device_id=device_id, status=st, anomalies=0, last_value=last_val)


@router.get("/health", response_model=HealthOut)
def health():
    from industrial.infrastructure.sqlalchemy_repository import SqlAlchemyTelemetryRepository
    from industrial.infrastructure.redis_cache import make_cache
    repo = SqlAlchemyTelemetryRepository()
    cache = make_cache()
    cache_type = type(cache).__name__
    return HealthOut(status="ok", telemetry_count=repo.count(), cache=cache_type)


@router.get("/cache-stats")
def cache_stats():
    """Expose L1/L2 hit-rate metrics for verification."""
    from industrial.infrastructure.redis_cache import make_cache
    cache = make_cache()
    if hasattr(cache, "stats"):
        return cache.stats()
    return {"cache": type(cache).__name__}
