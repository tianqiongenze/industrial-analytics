"""Custom CockroachDB dialect for SQLAlchemy (psycopg2-based).

SQLAlchemy's stock PostgreSQL dialect cannot parse CRDB's version string
('CockroachDB CCL v24.3.11 ...'), so we subclass the psycopg2 dialect and
override version detection. Registered in database.py as 'postgresql.crdb'.
"""
import re
from sqlalchemy.dialects.postgresql.psycopg2 import PGDialect_psycopg2


class CockroachDialect(PGDialect_psycopg2):
    name = "postgresql"

    def _get_server_version_info(self, connection):
        vers = connection.exec_driver_sql("SELECT version()").scalar()
        m = re.search(r"v(\d+)\.(\d+)\.(\d+)", vers or "")
        if m:
            return tuple(int(x) for x in m.groups())
        return (24, 3, 11)
