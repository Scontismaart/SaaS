"""Store dei token di export GDPR (Bloccante B3).

Il dict in-memory per-processo e' stato rimosso: i token devono sopravvivere
ai restart ed essere condivisi tra i worker uvicorn. Con REDIS_URL usano
Redis/Valkey con TTL 15 minuti; in dev/test senza Redis si degrada sul
backend in-memory (stesso contratto, stessi TTL)."""
import json
import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

TOKEN_TTL_SECONDS = 15 * 60
_PREFIX = "gdpr:export:"
_memory: dict[str, dict[str, Any]] = {}
_redis = None
_warned = False


async def _get_redis():
    global _redis, _warned
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        from src.core.security.docs import is_production
        if is_production() and not _warned:
            _warned = True
            logger.warning(
                "token_store: REDIS_URL assente in produzione: fallback in-memory, "
                "i token NON saranno condivisi tra i worker"
            )
        return None
    from redis.asyncio import Redis

    _redis = Redis.from_url(url, decode_responses=True)
    return _redis


async def save_token(token: str, org_id: str, data: dict) -> None:
    payload = json.dumps(
        {"org_id": org_id, "data": data, "expires": time.time() + TOKEN_TTL_SECONDS}
    )
    r = await _get_redis()
    if r is not None:
        await r.set(_PREFIX + token, payload, ex=TOKEN_TTL_SECONDS)
    else:
        _memory[token] = {
            "org_id": org_id, "data": data,
            "expires": time.time() + TOKEN_TTL_SECONDS,
        }


async def pop_token(token: str) -> dict | None:
    """Consuma il token (one-time). None se assente o scaduto."""
    r = await _get_redis()
    if r is not None:
        raw = await r.getdel(_PREFIX + token)  # atomico: un solo consumo
        if raw is None:
            return None
        meta = json.loads(raw)
    else:
        meta = _memory.pop(token, None)
        if meta is None:
            return None
    if meta.get("expires", 0) < time.time():
        return None
    return meta
