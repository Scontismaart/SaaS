from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


def compute_advisory_lock_id(lock_key: str) -> int:
    """
    Genera un intero 64-bit signed deterministico per pg_try_advisory_lock
    nell'intervallo PostgreSQL bigint: [-2^63, 2^63 - 1].
    """
    digest = hashlib.sha256(lock_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


async def execute_with_advisory_lock(
    pool: Any,
    lock_name: str,
    job_coro: Callable[[Any], Coroutine[Any, Any, Any]],
) -> bool:
    """
    Esegue una coroutine di background job proteggendola con un PostgreSQL session-level advisory lock
    su una connessione dedicata acquisita dal pool.

    - Se un'altra istanza o worker sta già eseguendo il job con la stessa chiave, pg_try_advisory_lock
      ritorna False e l'esecuzione viene saltata immediatamente (no-op sicuro, multi-instance idempotent).
    - Alla fine (o in caso di errore), il lock viene rilasciato esplicitamente con pg_advisory_unlock
      e la connessione viene restituita al pool. In caso di crash del worker, PostgreSQL chiude il socket
      e rilascia automaticamente il lock a livello di sessione.
    """
    lock_id = compute_advisory_lock_id(lock_name)
    async with pool.acquire() as conn:
        locked = await conn.fetchval("SELECT pg_try_advisory_lock($1)", lock_id)
        if not locked:
            logger.info("job_skipped=advisory_lock_held job=%s lock_id=%d", lock_name, lock_id)
            return False

        logger.info("job_lock_acquired job=%s lock_id=%d", lock_name, lock_id)
        try:
            await job_coro(pool)
            return True
        finally:
            try:
                await conn.execute("SELECT pg_advisory_unlock($1)", lock_id)
                logger.debug("job_lock_released job=%s lock_id=%d", lock_name, lock_id)
            except Exception as e:
                logger.warning("job_lock_unlock_failed job=%s lock_id=%d error=%s", lock_name, lock_id, e)
