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
