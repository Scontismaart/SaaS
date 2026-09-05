async def dedup_check(pool, wam_id: str, resource_type: str, status_value: str) -> bool:
    """Atomic idempotency check via INSERT ON CONFLICT DO NOTHING.
    Returns True if this is a new event (lock acquired), False if duplicate."""
    row = await pool.fetchrow("""
        INSERT INTO webhook_idempotency (wam_id, resource_type, status_value)
        VALUES ($1, $2, $3)
        ON CONFLICT (wam_id, resource_type, status_value) DO NOTHING
        RETURNING wam_id
    """, wam_id, resource_type, status_value)
    return row is not None


async def purge_webhook_idempotency(pool, days: int = 7) -> int:
    """Purge webhook idempotency records older than retention window (default 7 days)."""
    async with pool.acquire() as conn:
        result = await conn.execute("""
            DELETE FROM webhook_idempotency
            WHERE created_at < NOW() - ($1 || ' days')::INTERVAL
        """, str(days))
        try:
            return int(result.split(" ")[1])
        except Exception:
            return 0
