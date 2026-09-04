"""L1+L2 multi-level cache for the analytics platform.

L1 = in-process (functools-style LRU/TTL dict, no external deps).
L2 = Redis (distributed, shared across instances).

Read flow:  L1 -> (miss) -> L2 -> (miss) -> DB, then backfill L2 then L1.
Write flow: DB -> invalidate L2 -> invalidate L1.

TTLs: L1 = 30s, L2 = 300s (5 min). Counters (incr) are Redis-only.
"""
from __future__ import annotations
import os, time, json, threading
from typing import Dict, Optional
from industrial.use_cases.ports import CachePort

L1_TTL = 30          # seconds, in-process
L2_TTL = 300         # seconds, Redis
L1_MAX = 4096        # max entries in L1


class _L1Cache:
    """Thread-safe in-process cache with TTL + a simple LRU cap."""

    def __init__(self, ttl: int = L1_TTL, max_size: int = L1_MAX):
        self._store: Dict[str, tuple[str, float]] = {}
        self._ttl = ttl
        self._max = max_size
        self._lock = threading.Lock()
        # stats
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._store.get(key)
            if not item:
                self.misses += 1
                return None
            val, exp = item
            if exp and time.time() > exp:
                self._store.pop(key, None)
                self.misses += 1
                return None
            # refresh LRU order
            self._store.pop(key, None)
            self._store[key] = (val, exp)
            self.hits += 1
            return val

    def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        with self._lock:
            if len(self._store) >= self._max and key not in self._store:
                # evict oldest (first inserted)
                self._store.pop(next(iter(self._store)), None)
            self._store[key] = (value, time.time() + (ttl or self._ttl))

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"l1_hits": self.hits, "l1_misses": self.misses, "l1_size": len(self._store)}


class _MemoryCache(CachePort):
    """Pure in-memory fallback when Redis is unavailable (tests/offline)."""
    def __init__(self):
        self._l1 = _L1Cache()
        self._counters: Dict[str, int] = {}

    def get(self, key):
        return self._l1.get(key)

    def set(self, key, value, ttl=60):
        self._l1.set(key, value, ttl)

    def incr(self, key):
        self._counters[key] = self._counters.get(key, 0) + 1
        return self._counters[key]

    def delete(self, key):
        self._l1.delete(key)


class TwoLevelCache(CachePort):
    """L1 (in-process) + L2 (Redis) read-through cache."""

    def __init__(self, url: str | None = None):
        import redis
        self._client = redis.Redis.from_url(
            url or os.getenv("REDIS_URL", "redis://:difyai123456@redis.dify-plus.svc.cluster.local:6379/0"),
            socket_connect_timeout=2, socket_timeout=2,
        )
        self._l1 = _L1Cache()
        # stats
        self._l2_hits = 0
        self._l2_misses = 0
        self._db_loads = 0

    def client(self):
        return self._client

    def get(self, key) -> Optional[str]:
        # L1
        v = self._l1.get(key)
        if v is not None:
            return v
        # L2 (Redis)
        try:
            raw = self._client.get(key)
        except Exception:
            raw = None
        if raw is not None:
            self._l2_hits += 1
            val = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            # backfill L1
            self._l1.set(key, val)
            return val
        self._l2_misses += 1
        return None

    def set(self, key, value, ttl=60):
        # write-through: populate both levels
        self._l1.set(key, value, ttl=min(ttl, L1_TTL))
        try:
            self._client.set(key, value, ex=ttl or L2_TTL)
        except Exception:
            pass

    def delete(self, key):
        self._l1.delete(key)
        try:
            self._client.delete(key)
        except Exception:
            pass

    def incr(self, key):
        try:
            return self._client.incr(key)
        except Exception:
            return 0

    def stats(self) -> dict:
        s = self._l1.stats()
        s.update({"l2_hits": self._l2_hits, "l2_misses": self._l2_misses, "db_loads": self._db_loads})
        return s


# Module-level singleton (created once per process).
_cache_singleton = None


def make_cache() -> CachePort:
    """Factory: use L1+L2 Redis cache when available, else in-memory cache."""
    global _cache_singleton
    if _cache_singleton is not None:
        return _cache_singleton
    try:
        cache = TwoLevelCache()
        cache.client().ping()
        _cache_singleton = cache
        return cache
    except Exception:
        _cache_singleton = _MemoryCache()
        return _cache_singleton
