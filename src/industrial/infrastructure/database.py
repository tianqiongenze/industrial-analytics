"""SQLAlchemy engines + session factory with CRDB read-write separation.

Two connection pools:
  * WRITE engine -> CRDB write node (port 26257 on master, accepts writes).
  * READ  engine -> CRDB read  node (port 26267 on master, read-only/followers).

Falls back to SQLite when DATABASE_URL is a sqlite URL (keeps tests portable).
"""
from __future__ import annotations
import os
from sqlalchemy import create_engine, dialects
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager

# Register the custom CockroachDB dialect under the '+crdb' driver token so
# URLs of the form 'postgresql+crdb://...' resolve to our CockroachDialect.
dialects.registry.register("postgresql.crdb", "industrial.infrastructure.crdb_dialect", "CockroachDialect")

CRDB_WRITE_URL = os.getenv(
    "WRITE_DB_URL",
    "postgresql+crdb://root@10.167.2.175:26257/industrial_analytics?sslmode=disable",
)
CRDB_READ_URL = os.getenv(
    "READ_DB_URL",
    "postgresql+crdb://root@10.167.2.175:26267/industrial_analytics?sslmode=disable",
)

LEGACY_URL = os.getenv("DATABASE_URL")

if LEGACY_URL and LEGACY_URL.startswith("sqlite"):
    _is_sqlite = True
    WRITE_URL = READ_URL = LEGACY_URL
elif LEGACY_URL:
    _is_sqlite = False
    WRITE_URL = READ_URL = LEGACY_URL
else:
    _is_sqlite = False
    WRITE_URL = CRDB_WRITE_URL
    READ_URL = CRDB_READ_URL


def _build_engine(url: str, is_write: bool):
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        pool_kwargs = {"poolclass": StaticPool} if ":memory:" in url else {}
    else:
        connect_args = {}
        pool_kwargs = {
            "pool_size": 20 if is_write else 10,
            "max_overflow": 10,
            "pool_pre_ping": True,
            "pool_recycle": 1800,
        }
    return create_engine(url, connect_args=connect_args, future=True, **pool_kwargs)


engine = _build_engine(WRITE_URL, is_write=True)
read_engine = _build_engine(READ_URL, is_write=False) if WRITE_URL != READ_URL else engine

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
ReadSessionLocal = (
    sessionmaker(bind=read_engine, autoflush=False, autocommit=False, future=True)
    if read_engine is not engine else SessionLocal
)

Base = declarative_base()


@contextmanager
def session_scope() -> Session:
    """Write session (CRDB write node). Use for INSERT/UPDATE/DELETE."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def read_session_scope() -> Session:
    """Read session (CRDB read node). Use for SELECT only."""
    session = ReadSessionLocal()
    try:
        yield session
        session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create all tables on the WRITE node. Called on startup."""
    from industrial.infrastructure import orm  # noqa: F401 ensure models imported
    Base.metadata.create_all(bind=engine)
