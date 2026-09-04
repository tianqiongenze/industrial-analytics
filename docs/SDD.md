# Software Design Document (SDD)
## 工业设备数据分析平台 — Industrial Equipment Data Analysis Platform

**Project:** Industrial Analytics &nbsp; **Student:** student-python &nbsp;
**Language:** Python 3.11 &nbsp; **Framework:** FastAPI 0.111 + SQLAlchemy 2.0 &nbsp;
**Architecture:** Clean Architecture (TOGAF Technology & Application Architecture)

> AI-assisted design: anomaly-detection algorithm selection and threshold
> defaults were validated against the `qwen2.5-coder:7b` model via the platform
> LiteLLM gateway. Implementation and tests are hand-written per the verified
> specifications.

---

## 1. Introduction

### 1.1 Purpose
This SDD describes a platform that turns raw industrial equipment telemetry into
actionable operational insight: real-time classification of device health,
statistical anomaly detection, and a queryable analytics API. It targets
continuous-monitoring use cases for pumps, motors, furnaces and CNC machines in
a smart factory.

### 1.2 Scope
Inbound: JSON telemetry over MQTT and REST. Processing: validation, persistence,
threshold classification, rolling statistics, z-score and IQR anomaly detection.
Outbound: a REST API with OpenAPI docs, live device status (cached), and
computed analytics. Out of scope: streaming ML model serving and a UI dashboard
(intentionally left to a separate frontend project).

### 1.3 Definitions
- **Telemetry reading** — an immutable (device_id, metric, value, timestamp) tuple.
- **Z-score anomaly** — |value − mean| / std > threshold (default 3σ).
- **IQR anomaly** — value outside the Tukey fence [Q1−1.5·IQR, Q3+1.5·IQR].
- **FPY / OEE** — see glossary in the Java project SDD; reused here.
- **Clean Architecture** — concentric layers with the dependency rule pointing
  inward; outer = frameworks/IO, inner = policy.

---

## 2. Architecture (TOGAF + Clean Architecture)

### 2.1 Layered Structure
The system follows the Clean Architecture dependency rule. Arrows point
inward (toward higher policy):

```
[ infrastructure: web (FastAPI), db (SQLAlchemy), cache (Redis), mqtt ] ─►
[ use_cases: IngestTelemetry, analytics_engine, ports ] ─►
[ domain: TelemetryReading, DeviceStatus, Anomaly, threshold policy ]
```

In TOGAF terms: the domain is the **Business Architecture** layer, the
use-cases are the **Business Process/Application** layer, and the
infrastructure/adapters are the **Application Platform** (technology) layer.
This separation lets each layer evolve and be tested independently.

### 2.2 Components

| Layer | Module | Responsibility |
|-------|--------|----------------|
| domain | `domain/models.py` | `TelemetryReading` (frozen dataclass), `DeviceStatus`, `Anomaly` |
| domain | `domain/thresholds.py` | per-metric warn/critical policy + `classify()` |
| use_cases | `use_cases/ports.py` | abstract `TelemetryRepository`, `CachePort`, `EventPublisher` |
| use_cases | `use_cases/analytics_engine.py` | `rolling_stats`, `detect_zscore_anomalies`, `detect_iqr_anomalies` |
| use_cases | `use_cases/ingest_telemetry.py` | `IngestTelemetry` orchestrating save→classify→cache |
| infra | `infrastructure/database.py` + `orm.py` | SQLAlchemy engine, `TelemetryModel` |
| infra | `infrastructure/sqlalchemy_repository.py` | `TelemetryRepository` adapter |
| infra | `infrastructure/redis_cache.py` | `RedisCache` + `_MemoryCache` fallback |
| infra | `infrastructure/mqtt_ingestor.py` | MQTT→TelemetryReading adapter |
| api | `api/schemas.py` + `api/routes.py` + `api/app.py` | FastAPI REST + OpenAPI |

### 2.3 Data Flow (ingestion)
```
MQTT msg ─► MqttIngestor.handle_message ─► IngestTelemetry.execute
        ─► repo.save(reading)                    [persistence]
        ─► repo.fetch_window(device, metric,50)  [rolling context]
        ─► classify(metric, value)              [threshold policy]
        ─► cache.set("status:<device>", status)  [live status cache]
        ─► cache.incr("alerts:<device>:<status>") [dashboard counters]
```

### 2.4 Deployment View
- REST API: `uvicorn industrial.api.app:app` (port 8000) — primary adapter.
- MQTT worker: `python -m industrial.infrastructure.mqtt_ingestor` — secondary
  adapter, scales horizontally, shares the same code/use-cases.
- PostgreSQL holds `telemetry` table; Redis holds status/alerts caches.

---

## 3. Domain Model

```
TelemetryReading (frozen)        DeviceStatus
  device_id : str                  device_id : str
  metric : str                     status : str   (NORMAL|WARNING|CRITICAL)
  value : float                    anomalies : int
  timestamp : datetime             last_value : float
  unit : str                       window_start/end : datetime

Anomaly
  device_id, metric, value, expected_mean, expected_std, zscore, timestamp, rule
```
Invariants enforced in the domain constructor (e.g. non-empty device_id, no NaN,
required timestamp) so invalid data can never enter the system.

---

## 4. Analytics Engine Design

### 4.1 Rolling Statistics
`rolling_stats(values, window=30)` computes mean, std (ddof=1), min, max, count
over the last `window` values using NumPy — O(window) per call, suitable for
streaming ingestion where the window slides forward with each new reading.

### 4.2 Anomaly Detection
Two complementary statistical detectors:
- **Z-score**: for each reading, z = (value − mean)/std; flag if |z| > threshold.
  Sensitive to drift and spikes. Requires ≥2 readings and non-zero variance.
- **IQR (Tukey)**: compute Q1/Q3 over the window; flag values outside
  [Q1−1.5·IQR, Q3+1.5·IQR]. Robust to a few extreme values inflating the std.
  Requires ≥4 readings.

Both are pure functions of `list[TelemetryReading]`, making them trivially
unit-testable and reusable by the API and the MQTT worker.

### 4.3 Threshold Policy
`DEFAULT_THRESHOLDS` map metric→(warn, critical). `classify()` is O(1) and used
both at ingestion (live status) and on demand (device status endpoint). The map
is overridable per call, enabling per-device calibration.

---

## 5. Sequence Diagrams

### 5.1 REST ingestion
```
Client   POST /api/v1/telemetry        routes.ingest          IngestTelemetry
  │  {device_id,metric,value,unit}        │                       │
  │──────────────────────────────────────►│ execute(reading)     │
  │                                        │──────────────────────►│ repo.save
  │                                        │                       │ repo.fetch_window
  │                                        │                       │ classify(value)
  │                                        │                       │ cache.set/incr
  │  201 DeviceStatusOut ◄────────────────│◄──────────────────────│
  │◄──────────────────────────────────────│
```

### 5.2 Analytics query
```
Client  GET /api/v1/analytics?device&metric&window
  │ routes.analytics
  │  repo.fetch_window(device, metric, window)
  │  analytics_engine.rolling_stats(values)
  │  analytics_engine.detect_zscore_anomalies(readings)
  │  analytics_engine.detect_iqr_anomalies(readings)
  │ 200 AnalyticsOut
  │◄
```

---

## 6. Test Strategy (TDD)

Tests are written per layer and run with `pytest --cov=src`:

| File | Tests | Covers |
|------|-------|--------|
| test_domain.py | 11 | entity invariants, threshold classify (parametrised) |
| test_analytics_engine.py | 13 | rolling stats, z-score, IQR, status eval |
| test_use_cases.py | 4 | IngestTelemetry orchestration with fakes |
| test_sqlalchemy_repository.py | 5 | save/count/window/metric-filter (in-memory SQLite) |
| test_memory_cache.py | 5 | set/get/ttl/incr/overwrite |
| test_mqtt_ingestor.py | 4 | JSON message handling, no-broker start |
| test_api.py | 10 | full HTTP stack: ingest, analytics, status, health, OpenAPI, 422/404 |

Pure-logic tests (domain, analytics, use-cases, cache) require no I/O and run
in milliseconds. The repository tests use an in-memory SQLite. The API tests use
FastAPI's `TestClient` against an isolated in-memory DB (recreated per test via
an `autouse` fixture) so they are deterministic and parallel-safe.

---

## 7. Non-Functional Requirements
- **Performance:** NumPy-vectorised analytics; Redis caches hot device status
  (TTL 300s) so the status endpoint is O(1) for cached devices.
- **Reliability:** in-memory cache fallback means the system degrades
  gracefully when Redis is unavailable; SQLite default makes local runs
  zero-config.
- **Security:** Pydantic v2 validation at the API boundary; 422 for invalid
  input; no raw SQL (SQLAlchemy ORM + parameterised queries).
- **Portability:** DATABASE_URL switches between SQLite/PostgreSQL; REDIS_URL
  switches Redis instance; no code changes required.

## 8. Future Work
- Add Exponentially-Weighted Moving Average (EWMA) for drift detection.
- Persist anomaly events to a separate table for auditing.
- WebSocket endpoint for real-time dashboard push.

## 9. Revision History
| Version | Date | Author | Notes |
|---------|------|--------|-------|
| 1.0 | 2026-08-31 | student-python | Initial SDD, Clean Architecture, 52 tests |
---

## 10. Design Rationale & Trade-offs

### 10.1 Why Clean Architecture over a layered framework
The platform deliberately avoids pinning business rules to a specific web
framework or ORM. `domain/` imports only the standard library, so the
threshold policy and anomaly detectors can be reused from a CLI, a batch
job, or a different web framework without rewrites. This is the single most
load-bearing decision in the codebase: it makes the analytics engine
unit-testable in milliseconds (no fixtures, no I/O) and lets the MQTT worker
and the REST API share identical processing logic. The cost is a little more
boilerplate (ports + adapters) and an extra mapping layer between the Pydantic
schema and the domain `TelemetryReading` — a price willingly paid for the
ability to evolve the database and the broker independently.

### 10.2 Two anomaly detectors instead of one
The z-score detector is sensitive to drift and spikes but is itself inflated
by the very outliers it tries to detect (a single huge value inflates the
standard deviation, suppressing subsequent detections). The IQR detector is
robust to a few extreme values because quartiles are resistant to outliers.
Running both and reporting their counts separately gives the operator two
complementary signals: z-score flags rapid deviations from a recent baseline,
while IQR flags values that are statistically improbable for the population.
A production tuning would let each device configure which detector (or both)
applies to which metric — e.g. vibration favours IQR (skewed distributions),
temperature favours z-score (roughly Gaussian).

### 10.3 Rolling window with NumPy
`rolling_stats` slices the last `window` values and computes mean/std/min/max
in vectorised NumPy operations. This is O(window) per call and allocation-free
beyond the slice view, which matters because ingestion is hot-path code called
on every MQTT message. The window is fetched from the repository per request;
for higher throughput the repository could maintain a pre-materialised ring
buffer, but the current design favours simplicity and correctness over
micro-optimisation, with the optimisation path left as a documented future work
item.

### 10.4 In-memory cache fallback
`make_cache()` probes Redis and falls back to `_MemoryCache` on any failure.
This means the system is runnable and testable with zero infrastructure (no
Redis required) while still exercising the full `CachePort` contract. In
production the fallback is a graceful degradation: if Redis blips, device
status is computed fresh from the repository rather than served stale. The
trade-off is that the in-memory cache is per-process and not shared across
horizontal replicas — acceptable for a status cache that is regenerated on
each ingestion.

### 10.5 H2/SQLite for tests, PostgreSQL for production
The SQLAlchemy ORM and parameterised queries make the storage engine
interchangeable via `DATABASE_URL`. Tests use `:memory:` SQLite with a
`StaticPool` so all threads/connections share a single in-memory database
(the default pool would give each connection its own empty DB, causing
"no such table" errors in FastAPI's `TestClient` which runs in a separate
thread). This is a subtle but critical detail: the test fixtures recreate
tables per test for isolation, and importing the ORM module once at fixture
collection time keeps the models registered on `Base.metadata` so that
`create_all` actually emits the `telemetry` table.

---

## 11. Quality Attributes (NFRs) in detail

| Attribute | Strategy |
|-----------|----------|
| Performance | NumPy-vectorised analytics; O(1) cached status lookups; indexed `(device_id, metric, timestamp)` |
| Reliability | Graceful cache fallback; per-test DB isolation; no shared mutable state in domain |
| Security | Pydantic v2 validation at boundary; no raw SQL; 422 for invalid input; immutable domain entities |
| Portability | DATABASE_URL / REDIS_URL switches backends with no code change |
| Maintainability | One responsibility per module; pure functions in domain; thin adapters |
| Observability | `/health` exposes reading count + cache type; OpenAPI at `/docs` |

---

## 12. Glossary
- **Clean Architecture** — concentric layers with the dependency rule pointing
  inward; dependencies may only point toward higher-level policy.
- **Port** — an interface defined by an inner layer that an outer adapter
  implements (here: `TelemetryRepository`, `CachePort`, `EventPublisher`).
- **Adapter** — a concrete implementation of a port bound to a technology.
- **FPY** — First Pass Yield; the fraction of units that pass inspection
  without rework.
- **IQR** — Interquartile Range (Q3 − Q1); the basis of the Tukey fence.
- **StaticPool** — a SQLAlchemy pool that pins a single connection, used so
  that an in-memory SQLite DB is shared across threads in tests.
---

## 13. Operational Runbook

### 13.1 Startup sequence
1. Provision PostgreSQL and Redis (or rely on the in-memory fallback for
   development). 2. Set `DATABASE_URL` and `REDIS_URL` environment variables.
3. `pip install -r requirements.txt`. 4. Start the REST API:
   `uvicorn industrial.api.app:app --port 8000`. 5. (Optional) start the MQTT
   worker: `python -m industrial.infrastructure.mqtt_ingestor`.

### 13.2 Failure modes
- **MQTT broker unreachable**: the ingestor logs a warning and exits its
  loop; the REST API continues to accept manual ingestions. No data loss for
  in-flight messages because each message is processed independently.
- **PostgreSQL unreachable**: ingestion saves fail and the 500 propagates to
  the caller; cached device status (TTL 300s) remains queryable until expiry.
- **Redis unreachable**: `make_cache` returns the in-memory cache on the next
  call; live status degrades to fresh-from-repo computation.

### 13.3 Capacity notes
The analytics window defaults to 100 readings; with NumPy this is sub-millisecond.
For very high-cardinality device fleets the `(device_id, metric, timestamp)`
index and the per-request window fetch keep query cost linear in the window
size, not the table size. Horizontal scaling of the API is stateless.

---

## 14. Alternatives Considered
- **FastAPI background task for ingestion**: rejected because ingestion must
  be transactionally consistent with persistence; a synchronous request
  guarantees the 201 response reflects the persisted state.
- **paho-mqtt hard dependency**: rejected in favour of the abstracted
  `Client` port so the ingestor is testable and broker-agnostic.
- **Single Pandas DataFrame for all devices**: rejected; per-device windows
  via NumPy arrays avoid the overhead of DataFrame construction on the hot
  path and keep memory bounded by the window size.
