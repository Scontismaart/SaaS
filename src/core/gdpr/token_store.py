"""Store dei token di export GDPR (Bloccante B3).

Il dict in-memory per-processo e' stato rimosso: i token devono sopravvivere
ai restart ed essere condivisi tra i worker uvicorn. Con REDIS_URL usano
Redis/Valkey con TTL 15 minuti; in dev/test senza Redis si degrada sul
backend in-memory (stesso contratto, stessi TTL)."""
import asyncio
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

    try:
        current_loop = asyncio.get_running_loop()
        if _redis is not None:
            pool = getattr(_redis, "connection_pool", None)
            pool_loop = getattr(pool, "_loop", None)
            if pool_loop is not None and (pool_loop != current_loop or pool_loop.is_closed()):
                _redis = None
    except Exception:
        _redis = None

    if _redis is not None:
        return _redis

    try:
        from redis.asyncio import Redis
        _redis = Redis.from_url(url, decode_responses=True)
        return _redis
    except Exception:
        return None


async def save_token(token: str, org_id: str, data: dict) -> None:
    payload = json.dumps(
        {"org_id": org_id, "data": data, "expires": time.time() + TOKEN_TTL_SECONDS}
    )
    r = await _get_redis()
    if r is not None:
        try:
            await r.set(_PREFIX + token, payload, ex=TOKEN_TTL_SECONDS)
            return
        except Exception as e:
            logger.warning("token_store: redis set failed, falling back to memory: %s", e)
    _memory[token] = {
        "org_id": org_id, "data": data,
        "expires": time.time() + TOKEN_TTL_SECONDS,
    }


async def pop_token(token: str) -> dict | None:
    """Consuma il token (one-time). None se assente o scaduto."""
    r = await _get_redis()
    if r is not None:
        try:
            raw = await r.getdel(_PREFIX + token)  # atomico: un solo consumo
            if raw:
                doc = json.loads(raw)
                if doc.get("expires", 0) >= time.time():
                    return doc
            return None
        except Exception as e:
            logger.warning("token_store: redis getdel failed, falling back to memory: %s", e)
    entry = _memory.pop(token, None)
    if entry and entry["expires"] >= time.time():
        return entry
    return None
