# 工业设备数据分析平台 (Industrial Equipment Data Analysis Platform)

> Student: `student-python` — Language: Python 3.11 + FastAPI + SQLAlchemy
> Architecture: Clean Architecture (TOGAF)

A platform for ingesting, analysing and anomaly-detecting industrial equipment
telemetry. Telemetry arrives via an MQTT ingestion adapter and a REST API,
is persisted to PostgreSQL (SQLite in tests), classified against configurable
thresholds, and analysed with a pandas/numpy-backed analytics engine that
performs rolling statistics and statistical anomaly detection (z-score + IQR).
Redis caches live device status; an in-memory cache is used offline.

## Architecture (Clean Architecture / TOGAF)

```
                 ┌─────────────────────────────────────┐
   MQTT ───────► │ infrastructure/mqtt_ingestor        │  (secondary adapter)
                 │ api/routes.py (FastAPI REST)        │  (primary adapter)
   HTTP ───────► │                                     │
                 └───────────────┬─────────────────────┘
                                 │  (depends inward)
                 ┌───────────────▼─────────────────────┐
                 │ use_cases/ (IngestTelemetry, ports) │  application layer
                 └───────────────┬─────────────────────┘
                                 │  (depends inward)
                 ┌───────────────▼─────────────────────┐
                 │ domain/ (TelemetryReading, status,  │  enterprise
                 │        thresholds policy)             │  business rules
                 └─────────────────────────────────────┘
   Ports implemented by adapters:
     TelemetryRepository -> SqlAlchemyTelemetryRepository (PostgreSQL/SQLite)
     CachePort            -> RedisCache / _MemoryCache
```

The dependency rule of Clean Architecture holds: outer layers (web, db, mqtt)
depend on inner layers; the domain depends on nothing.

## Modules
- **domain/** — pure entities (`TelemetryReading`, `DeviceStatus`, `Anomaly`)
  and the threshold policy.
- **use_cases/** — application logic: `IngestTelemetry` use case, the
  `analytics_engine` (rolling stats, z-score & IQR anomaly detection), and
  the `ports` (abstract `TelemetryRepository`, `CachePort`).
- **infrastructure/** — adapters: SQLAlchemy ORM + repository, Redis cache
  (with in-memory fallback), and the MQTT ingestor.
- **api/** — FastAPI primary adapter: Pydantic schemas, routes, app factory
  with auto-generated OpenAPI at `/docs`.

## Run

```bash
pip install -r requirements.txt
uvicorn industrial.api.app:app --reload --port 8000   # REST API + /docs
# Or run the MQTT ingestor worker separately (broker optional)
python -m industrial.infrastructure.mqtt_ingestor
```

## Test (TDD, with coverage)
```bash
pytest --cov=src --cov-report=term-missing
```
Tests are organised per layer: `test_domain.py`, `test_analytics_engine.py`,
`test_use_cases.py`, `test_sqlalchemy_repository.py`, `test_memory_cache.py`,
`test_mqtt_ingestor.py`, `test_api.py`. Pure logic tests need no DB/network;
API tests use FastAPI's `TestClient` against an in-memory SQLite.

## Environment
- `DATABASE_URL` (default `sqlite:///./industrial.db`) — set to
  `postgresql://user:pass@host/db` for PostgreSQL.
- `REDIS_URL` (default `redis://localhost:6379/0`).

See `docs/SDD.md` for the full Software Design Document.
