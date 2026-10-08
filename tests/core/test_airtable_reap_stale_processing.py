from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from src.integrations.airtable.repository import AirtableWebhookRepository


pytestmark = pytest.mark.usefixtures("reset_db")


async def _make_org(pool) -> uuid.UUID:
    organization_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO organizations (id, name) VALUES ($1, $2)",
        organization_id,
        f"Reaper test {organization_id}",
    )
    return organization_id


async def _make_event(pool, organization_id, *, status="processing", age=timedelta(hours=2)):
    event_id = uuid.uuid4()
    await pool.execute(
        """
        INSERT INTO airtable_webhook_events (
            id, organization_id, base_id, webhook_id, external_event_id,
            event_type, payload, status, created_at
        ) VALUES ($1, $2, 'base-test', $3, $4, 'table_data_changed', '{}'::jsonb,
                  $5, NOW() - $6::interval)
        """,
        event_id,
        organization_id,
        f"webhook-{organization_id}",
        f"event-{event_id}",
        status,
        age,
    )
    return event_id


@pytest.mark.asyncio
async def test_reaper_filters_status_and_age_applies_limit_and_repeats_idempotently(pg_pool):
    organizations = [await _make_org(pg_pool) for _ in range(3)]
    try:
        oldest = await _make_event(pg_pool, organizations[0])
        second = await _make_event(pg_pool, organizations[1])
        fresh = await _make_event(
            pg_pool, organizations[2], age=timedelta(minutes=5)
        )
        pending = await _make_event(pg_pool, organizations[2], status="pending")
        await pg_pool.execute(
            "UPDATE airtable_webhook_events SET created_at = NOW() - INTERVAL '3 hours' WHERE id = $1",
            oldest,
        )
        await pg_pool.execute(
            "UPDATE airtable_webhook_events SET created_at = NOW() - INTERVAL '2 hours' WHERE id = $1",
            second,
        )

        repo = AirtableWebhookRepository(pg_pool)
        reaped = await repo.reap_stale_processing(older_than_seconds=1800, limit=2)

        assert {row["id"] for row in reaped} == {oldest, second}
        assert {row["organization_id"] for row in reaped} == set(organizations[:2])
        assert all(row["base_id"] == "base-test" for row in reaped)
        rows = await pg_pool.fetch(
            "SELECT id, status, error_message FROM airtable_webhook_events "
            "WHERE id = ANY($1::uuid[])",
            [oldest, second, fresh, pending],
        )
        state = {row["id"]: (row["status"], row["error_message"]) for row in rows}
        assert state[oldest] == (
            "pending",
            "reaped: processing oltre soglia, rimesso in coda",
        )
        assert state[second] == state[oldest]
        assert state[fresh][0] == "processing"
        assert state[pending][0] == "pending"
        assert await repo.reap_stale_processing(older_than_seconds=1800, limit=2) == []
    finally:
        await pg_pool.execute(
            "DELETE FROM organizations WHERE id = ANY($1::uuid[])", organizations
        )


@pytest.mark.asyncio
async def test_reaper_skips_rows_locked_by_another_worker(pg_pool):
    organization_id = await _make_org(pg_pool)
    try:
        locked_event = await _make_event(pg_pool, organization_id)
        available_event = await _make_event(pg_pool, organization_id)
        async with pg_pool.acquire() as lock_conn:
            async with lock_conn.transaction():
                await lock_conn.fetchrow(
                    "SELECT id FROM airtable_webhook_events WHERE id = $1 FOR UPDATE",
                    locked_event,
                )
                reaped = await AirtableWebhookRepository(pg_pool).reap_stale_processing(
                    older_than_seconds=1800,
                    limit=1,
                )
                assert [row["id"] for row in reaped] == [available_event]

        statuses = await pg_pool.fetch(
            "SELECT id, status FROM airtable_webhook_events WHERE id = ANY($1::uuid[])",
            [locked_event, available_event],
        )
        assert {row["id"]: row["status"] for row in statuses} == {
            locked_event: "processing",
            available_event: "pending",
        }
    finally:
        await pg_pool.execute(
            "DELETE FROM organizations WHERE id = $1", organization_id
        )
