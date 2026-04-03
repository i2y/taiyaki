"""LRU response cache with ETag support."""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class CacheEntry:
    """A cached SSR response."""

    body: str
    etag: str
    created_at: float
    ttl: float  # seconds, 0 = no expiry

    @property
    def expired(self) -> bool:
        if self.ttl <= 0:
            return False
        return (time.monotonic() - self.created_at) > self.ttl


def _default_cache_key(path: str, query_string: str) -> str:
    if query_string:
        return f"{path}?{query_string}"
    return path


class ResponseCache:
    """OrderedDict-based LRU cache for SSR responses."""

    def __init__(
        self,
        max_entries: int = 128,
        key_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        self._max_entries = max_entries
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._key_fn = key_fn or _default_cache_key

    def get(self, path: str, query_string: str) -> CacheEntry | None:
        key = self._key_fn(path, query_string)
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expired:
            del self._cache[key]
            return None
        self._cache.move_to_end(key)
        return entry

    def put(
        self, path: str, query_string: str, body: str, ttl: float = 0
    ) -> CacheEntry:
        key = self._key_fn(path, query_string)
        etag = hashlib.md5(body.encode("utf-8")).hexdigest()
        entry = CacheEntry(
            body=body,
            etag=etag,
            created_at=time.monotonic(),
            ttl=ttl,
        )
        if key in self._cache:
            del self._cache[key]
        self._cache[key] = entry
        while len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)
        return entry

    def invalidate(self, path: str | None = None) -> None:
        if path is None:
            self._cache.clear()
        else:
            keys = [k for k in self._cache if k == path or k.startswith(path + "?")]
            for k in keys:
                del self._cache[k]

    def __len__(self) -> int:
        return len(self._cache)
