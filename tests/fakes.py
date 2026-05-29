"""Test doubles: in-memory async Redis."""

from __future__ import annotations

import time
from typing import Any


class _FakePipeline:
    def __init__(self, parent: "FakeAsyncRedis") -> None:
        self._parent = parent
        self._calls: list[tuple[str, tuple, dict]] = []

    def incr(self, key: str) -> "_FakePipeline":
        self._calls.append(("incr", (key,), {}))
        return self

    def expire(self, key: str, seconds: int) -> "_FakePipeline":
        self._calls.append(("expire", (key, seconds), {}))
        return self

    async def execute(self) -> list:
        results = []
        for name, args, kwargs in self._calls:
            method = getattr(self._parent, name)
            results.append(await method(*args, **kwargs))
        return results


class FakeAsyncRedis:
    """Minimal async-Redis stand-in for tests."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self._expiry: dict[str, float] = {}

    def _purge(self) -> None:
        now = time.time()
        for k in [k for k, exp in self._expiry.items() if exp <= now]:
            self._store.pop(k, None)
            self._expiry.pop(k, None)

    async def get(self, key: str) -> bytes | None:
        self._purge()
        return self._store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> bool:
        self._store[key] = _to_bytes(value)
        if ex is not None:
            self._expiry[key] = time.time() + ex
        return True

    async def setex(self, key: str, ttl_seconds: int, value: Any) -> bool:
        return await self.set(key, value, ex=ttl_seconds)

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self._store:
                self._store.pop(k, None)
                self._expiry.pop(k, None)
                n += 1
        return n

    async def ttl(self, key: str) -> int:
        if key not in self._store:
            return -2
        exp = self._expiry.get(key)
        if exp is None:
            return -1
        return max(0, int(exp - time.time()))

    async def incr(self, key: str) -> int:
        self._purge()
        current = int(self._store.get(key, b"0"))
        current += 1
        self._store[key] = str(current).encode()
        return current

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self._store:
            return False
        self._expiry[key] = time.time() + seconds
        return True

    async def ping(self) -> bool:
        return True

    async def flushall(self) -> bool:
        self._store.clear()
        self._expiry.clear()
        return True

    async def aclose(self) -> None:
        await self.flushall()

    def pipeline(self) -> _FakePipeline:
        return _FakePipeline(self)


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode()
    return str(value).encode()
