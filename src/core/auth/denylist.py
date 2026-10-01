"""Token denylist per la revoca server-side delle sessioni JWT e refresh token.

Consente di invalidare un JWT o refresh token prima della sua naturale scadenza
(es. al logout o in caso di rotazione del refresh token).
Supporta backend distribuito Redis/Valkey (RATE_LIMIT_BACKEND=redis) con fallback
in-memory per dev/test.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time

from fastapi import HTTPException

_DEFAULT_TTL = 3600
_KEY_PREFIX = "auth:revoked"
_memory_denylist: dict[str, float] = {}


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _estimate_ttl_from_jwt(token: str, default_ttl: int = _DEFAULT_TTL) -> int:
    """Estrae il claim `exp` dal payload JWT senza verificarne la firma
    al solo fine di calcolare il TTL di retention nella denylist."""
    parts = token.split(".")
    if len(parts) >= 2:
        try:
            padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
            payload_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
            payload = json.loads(payload_bytes)
            exp = payload.get("exp")
            if isinstance(exp, (int, float)):
                remaining = int(exp - time.time())
                return max(remaining, 60)
        except Exception:  # noqa: BLE001, S110 - malformed JWTs use the safe TTL fallback
            pass
    return default_ttl


async def revoke_token(token: str, ttl_seconds: int | None = None) -> None:
    """Inserisce un token nella denylist fino alla sua scadenza naturale.
    In ambiente con RATE_LIMIT_BACKEND=redis, se Redis è down fallisce in modo
    esplicito (fail-closed) per evitare revoche parziali e incoerenti tra repliche.
    """
    if not token:
        return
    token_key = _token_hash(token)
    ttl = ttl_seconds if ttl_seconds is not None else _estimate_ttl_from_jwt(token)

    backend = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
    if backend == "redis":
        try:
            from redis.asyncio import Redis

            redis_client = Redis.from_url(
                os.getenv("REDIS_URL", "redis://valkey:6379/0"),
                encoding="utf-8",
                decode_responses=True,
            )
            async with redis_client:
                await redis_client.set(f"{_KEY_PREFIX}:{token_key}", "1", ex=ttl)
            return
        except Exception as e:  # noqa: BLE001 - authentication revocation fails closed
            logging.getLogger("src.core.auth.denylist").critical(
                "REDIS_DENYLIST_DOWN operation=revoke error_type=%s",
                type(e).__name__,
            )
            raise RuntimeError("Storage sessioni distribuito non disponibile") from None

    # In-memory backend (esclusivamente quando RATE_LIMIT_BACKEND != 'redis', es. test/dev)
    now = time.time()
    _memory_denylist[token_key] = now + ttl
    for k, expire_at in list(_memory_denylist.items()):
        if expire_at <= now:
            _memory_denylist.pop(k, None)


async def is_token_revoked(token: str) -> bool:
    """Verifica se il token è presente nella denylist.
    In ambiente con RATE_LIMIT_BACKEND=redis, se Redis non è raggiungibile
    applica una policy fail-closed sollevando 503 per impedire accessi non autorizzati.
    """
    if not token:
        return False
    token_key = _token_hash(token)

    backend = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
    if backend == "redis":
        try:
            from redis.asyncio import Redis

            redis_client = Redis.from_url(
                os.getenv("REDIS_URL", "redis://valkey:6379/0"),
                encoding="utf-8",
                decode_responses=True,
            )
            async with redis_client:
                exists = await redis_client.exists(f"{_KEY_PREFIX}:{token_key}")
                return bool(exists)
        except Exception as e:  # noqa: BLE001 - session checks fail closed on backend errors
            logging.getLogger("src.core.auth.denylist").critical(
                "REDIS_DENYLIST_DOWN operation=check error_type=%s",
                type(e).__name__,
            )
            raise HTTPException(
                status_code=503,
                detail="Servizio di autenticazione temporaneamente non disponibile (storage sessioni non raggiungibile)",
            ) from None

    now = time.time()
    expires_at = _memory_denylist.get(token_key)
    if expires_at is None:
        return False
    if expires_at <= now:
        _memory_denylist.pop(token_key, None)
        return False
    return True


def clear_memory_denylist() -> None:
    """Azzera la denylist in memoria (usato nei test di unità)."""
    _memory_denylist.clear()
