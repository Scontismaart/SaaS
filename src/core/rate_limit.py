"""Rate limiting backends.

Redis/Valkey is the production backend so counters are shared across workers.
The in-memory backend remains for tests/dev without Redis.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from typing import Protocol


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        """Return True when the limit has been exceeded."""

    async def push(self, key: str, window_seconds: int) -> None:
        """Registra un evento (timestamp) nella finestra scorrevole del key."""

    async def count(self, key: str, window_seconds: int) -> int:
        """Eventi del key dentro la finestra scorrevole, SENZA incrementare."""

    async def reset(self, key: str) -> None:
        """Azzera gli eventi del key."""


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.windows: dict[str, list[float]] = defaultdict(list)

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        window = self.windows[key]
        window[:] = [t for t in window if t > now - window_seconds]
        if len(window) >= limit:
            return True
        window.append(now)
        return False

    async def push(self, key: str, window_seconds: int) -> None:
        self.windows[key].append(time.time())

    async def count(self, key: str, window_seconds: int) -> int:
        now = time.time()
        return len([t for t in self.windows.get(key, ()) if t > now - window_seconds])

    async def reset(self, key: str) -> None:
        self.windows.pop(key, None)

    def clear(self) -> None:
        self.windows.clear()


class RedisRateLimiter:
    def __init__(self, redis_client, prefix: str = "rl") -> None:
        self.redis = redis_client
        self.prefix = prefix

    async def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        redis_key = f"{self.prefix}:{key}"
        count = await self.redis.incr(redis_key)
        if count == 1:
            await self.redis.expire(redis_key, window_seconds)
        return int(count) > limit

    # Finestra scorrevole via ZSET: condivisa tra worker/repliche e
    # sopravvive ai restart (a differenza del contatore INCR a finestra
    # fissa usato dal middleware globale).
    def _sw_key(self, key: str) -> str:
        return f"{self.prefix}:sw:{key}"

    async def push(self, key: str, window_seconds: int) -> None:
        zkey = self._sw_key(key)
        now = time.time()
        await self.redis.zadd(zkey, {str(now): now})
        await self.redis.expire(zkey, max(window_seconds, 1))

    async def count(self, key: str, window_seconds: int) -> int:
        zkey = self._sw_key(key)
        cutoff = time.time() - window_seconds
        await self.redis.zremrangebyscore(zkey, "-inf", cutoff)
        return int(await self.redis.zcard(zkey))

    async def reset(self, key: str) -> None:
        await self.redis.delete(self._sw_key(key))


_memory_limiter = InMemoryRateLimiter()
_redis_client = None
_limiter: RateLimiter | None = None


async def get_rate_limiter() -> RateLimiter:
    global _redis_client, _limiter
    backend = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
    if backend != "redis":
        return _memory_limiter
    if _limiter is None:
        from redis.asyncio import Redis

        _redis_client = Redis.from_url(
            os.getenv("REDIS_URL", "redis://valkey:6379/0"),
            encoding="utf-8",
            decode_responses=True,
        )
        _limiter = RedisRateLimiter(_redis_client)
    return _limiter


async def close_rate_limiter() -> None:
    global _redis_client, _limiter
    if _redis_client is not None:
        await _redis_client.aclose()
    _redis_client = None
    _limiter = None


def reset_memory_rate_limiter() -> None:
    _memory_limiter.clear()
