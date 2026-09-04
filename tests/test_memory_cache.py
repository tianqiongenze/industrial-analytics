"""TDD tests for the in-memory cache adapter."""
import time
from industrial.infrastructure.redis_cache import _MemoryCache


class TestMemoryCache:
    def test_set_get(self):
        c = _MemoryCache()
        c.set("k", "v")
        assert c.get("k") == "v"

    def test_missing_returns_none(self):
        assert _MemoryCache().get("nope") is None

    def test_ttl_expiry(self):
        c = _MemoryCache()
        c.set("k", "v", ttl=1)
        assert c.get("k") == "v"
        time.sleep(1.1)
        assert c.get("k") is None

    def test_incr(self):
        c = _MemoryCache()
        assert c.incr("counter") == 1
        assert c.incr("counter") == 2
        assert c.incr("counter") == 3

    def test_set_overwrites(self):
        c = _MemoryCache()
        c.set("k", "v1")
        c.set("k", "v2")
        assert c.get("k") == "v2"
