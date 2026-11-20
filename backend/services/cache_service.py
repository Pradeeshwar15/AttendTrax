# =============================================================================
# cache_service.py – Ultra-Low Latency In-Memory Cache with TTL
# =============================================================================
import time
import threading
from typing import Any, Optional


class InMemoryCache:
    """Thread-safe in-memory cache with sliding TTL expiry."""
    def __init__(self):
        self._cache = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            val, expiry = entry
            if expiry and now > expiry:
                del self._cache[key]
                return None
            return val

    def set(self, key: str, value: Any, ttl_seconds: int = 30):
        expiry = time.time() + ttl_seconds if ttl_seconds > 0 else 0
        with self._lock:
            self._cache[key] = (value, expiry)

    def invalidate(self, key_or_prefix: str):
        with self._lock:
            keys_to_del = [k for k in self._cache if k == key_or_prefix or k.startswith(key_or_prefix)]
            for k in keys_to_del:
                self._cache.pop(k, None)

    def clear(self):
        with self._lock:
            self._cache.clear()


cache = InMemoryCache()
