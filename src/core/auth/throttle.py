"""Throttle distribuito per tentativi di login e registrazione.

Sostituisce i contatori in-memory per-processo: con RATE_LIMIT_BACKEND=redis
gli eventi vivono in ZSET condivisi tra worker/repliche e sopravvivono ai
restart; senza Redis si degrada sul backend in-memory (dev/test), stesse
semantica a finestra scorrevole.
"""

from __future__ import annotations

from src.core.rate_limit import get_rate_limiter


async def is_throttled(key: str, max_events: int, window_seconds: int) -> bool:
    """True se l'evento corrente supererebbe max_events nella finestra."""
    limiter = await get_rate_limiter()
    return await limiter.count(key, window_seconds) >= max_events


async def record_event(key: str, window_seconds: int) -> None:
    limiter = await get_rate_limiter()
    await limiter.push(key, window_seconds)


async def clear_events(key: str) -> None:
    limiter = await get_rate_limiter()
    await limiter.reset(key)
