"""TDD tests for the SQLAlchemy repository adapter against in-memory SQLite."""
from datetime import datetime, timezone
from industrial.domain.models import TelemetryReading
from industrial.infrastructure.sqlalchemy_repository import SqlAlchemyTelemetryRepository


def _reading(device="dev-1", metric="temperature", value=50.0):
    return TelemetryReading(device, metric, value, datetime.now(timezone.utc))


class TestSqlAlchemyRepository:
    def test_save_and_count(self, repo):
        assert repo.count() == 0
        repo.save(_reading())
        repo.save(_reading())
        assert repo.count() == 2

    def test_count_by_device(self, repo):
        repo.save(_reading("dev-1"))
        repo.save(_reading("dev-2"))
        repo.save(_reading("dev-1"))
        assert repo.count("dev-1") == 2
        assert repo.count("dev-2") == 1

    def test_fetch_window_chronological(self, repo):
        for i in range(5):
            repo.save(_reading(value=float(i)))
        ws = repo.fetch_window("dev-1", "temperature", limit=3)
        assert len(ws) == 3
        assert [r.value for r in ws] == [2.0, 3.0, 4.0]  # last 3, chronological

    def test_fetch_window_empty(self, repo):
        assert repo.fetch_window("none", "temperature") == []

    def test_filter_by_metric(self, repo):
        repo.save(_reading("dev-1", "temperature", 10.0))
        repo.save(_reading("dev-1", "vibration", 5.0))
        ws = repo.fetch_window("dev-1", "vibration")
        assert len(ws) == 1
        assert ws[0].metric == "vibration"
