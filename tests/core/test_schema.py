import pytest


@pytest.mark.asyncio
async def test_schema_creates_all_tables(pg_pool):
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [r["table_name"] for r in rows]
    required = [
        "bookings", "booking_settings", "reviews", "documents",
        "document_chunks", "email_configs", "usage_events", "event_log",
    ]
    for t in required:
        assert t in tables, f"Missing table: {t}"
