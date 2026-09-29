"""Cross-process claims for review external IDs using PostgreSQL advisory locks."""

import asyncio
import threading
import weakref
from contextlib import asynccontextmanager

_semaphores: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_sync_semaphores: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_semaphores_lock = threading.Lock()


def _pool_semaphore(pool, max_size: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(pool)
    # Shared by Google sync and per-review claims. At least one connection is
    # always left free for the repositories called while claims are held.
    limit = max_size - 1
    with _semaphores_lock:
        per_loop = _semaphores.setdefault(loop, {})
        semaphore = per_loop.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(limit)
            per_loop[key] = semaphore
        return semaphore


def _sync_pool_semaphore(pool, max_size: int) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    key = id(pool)
    with _semaphores_lock:
        per_loop = _sync_semaphores.setdefault(loop, {})
        semaphore = per_loop.get(key)
        if semaphore is None:
            semaphore = asyncio.Semaphore(1)
            per_loop[key] = semaphore
        return semaphore


@asynccontextmanager
async def claim_google_review_sync(pool, organization_id):
    """Serialize Google syncs per tenant across workers/processes."""
    max_size_getter = getattr(pool, "get_max_size", None)
    max_size = max_size_getter() if callable(max_size_getter) else 1
    # The held sync connection is accompanied by an external-review claim and
    # repository work, so leave two connections available for nested work.
    if max_size < 3:
        raise RuntimeError("Google sync claim requires a pool with three connections")
    sync_semaphore = _sync_pool_semaphore(pool, max_size)
    claim_semaphore = _pool_semaphore(pool, max_size)
    await sync_semaphore.acquire()
    connection = None
    acquired = False
    claim_slot = False
    lock_key = f"google-review-sync:{organization_id}"
    try:
        await claim_semaphore.acquire()
        claim_slot = True
        connection = await pool.acquire()
        acquired = bool(await connection.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1, 0))", lock_key
        ))
        yield acquired
    finally:
        try:
            if connection is not None:
                if acquired:
                    try:
                        await connection.fetchval(
                            "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key
                        )
                    except Exception:
                        pass
                await pool.release(connection)
        finally:
            if claim_slot:
                claim_semaphore.release()
            sync_semaphore.release()


@asynccontextmanager
async def claim_external_review(pool, organization_id, external_id):
    """Yield whether this caller owns the org+external-id claim.

    The session lock is held on one pool connection and released in `finally`.
    A small per-pool semaphore always leaves at least one connection available
    for repository/RAG/accounting work. A one-connection pool fails closed.
    """
    if not external_id:
        yield True
        return

    max_size_getter = getattr(pool, "get_max_size", None)
    max_size = max_size_getter() if callable(max_size_getter) else 1
    if max_size <= 2:
        raise RuntimeError("review claim requires a pool with at least three connections")

    semaphore = _pool_semaphore(pool, max_size)
    await semaphore.acquire()
    connection = None
    acquired = False
    try:
        connection = await pool.acquire()
        lock_key = f"review:{organization_id}:{external_id}"
        acquired = bool(await connection.fetchval(
            "SELECT pg_try_advisory_lock(hashtextextended($1, 0))", lock_key
        ))
        yield acquired
    finally:
        try:
            if connection is not None:
                if acquired:
                    try:
                        lock_key = f"review:{organization_id}:{external_id}"
                        await connection.fetchval(
                            "SELECT pg_advisory_unlock(hashtextextended($1, 0))", lock_key
                        )
                    except Exception:
                        # Releasing the PostgreSQL session when returning the
                        # connection also releases its advisory locks.
                        pass
                await pool.release(connection)
        finally:
            semaphore.release()
