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
