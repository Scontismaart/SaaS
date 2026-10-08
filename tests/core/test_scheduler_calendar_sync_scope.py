from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


pytestmark = pytest.mark.usefixtures("reset_db")


@pytest.mark.asyncio
async def test_calendar_sync_uses_scoped_bookings_for_enabled_orgs(
    pg_pool, sample_org, other_org, monkeypatch
):
    from src.core import scheduler

    monkeypatch.setenv("ENCRYPTION_KEY", "test-key")
    monkeypatch.setattr(scheduler, "google_calendar_enabled", lambda: True)

    enabled_org = sample_org["id"]
    disabled_org = other_org["id"]
    async with pg_pool.acquire() as conn:
        for org_id, enabled in ((enabled_org, True), (disabled_org, False)):
            await conn.execute(
                """
                INSERT INTO google_calendar_credentials (
                    organization_id, access_token, refresh_token, token_expiry,
                    sync_enabled
                ) VALUES ($1, 'encrypted-access', 'encrypted-refresh', $2, $3)
                """,
                org_id,
                datetime.now(timezone.utc) + timedelta(days=1),
                enabled,
            )
        booking_ids = []
        for org_id in (enabled_org, disabled_org):
            booking_ids.append(await conn.fetchval(
                """
                INSERT INTO bookings (
                    organization_id, nome_cliente, telefono, data, ora, coperti,
                    stato
                ) VALUES ($1, 'Test', '', CURRENT_DATE + 1, '12:00', 2, 'confermata')
                RETURNING id
                """,
                org_id,
            ))

    service = MagicMock()
    service.sync_booking_state = AsyncMock()
    monkeypatch.setattr(
        "src.core.db.repositories.organization_repo.OrganizationRepository",
        MagicMock(return_value=MagicMock()),
    )
    monkeypatch.setattr("src.core.calendar.GoogleCalendarService", MagicMock(return_value=service))

    await scheduler._calendar_sync_job(pg_pool)

    service.sync_booking_state.assert_awaited_once()
    synced_booking, synced_org = service.sync_booking_state.await_args.args
    assert synced_booking["id"] == booking_ids[0]
    assert synced_org == enabled_org
    credentials = await pg_pool.fetch(
        "SELECT organization_id, last_sync_at FROM google_calendar_credentials"
    )
    last_sync = {row["organization_id"]: row["last_sync_at"] for row in credentials}
    assert last_sync[enabled_org] is not None
    assert last_sync[disabled_org] is None
