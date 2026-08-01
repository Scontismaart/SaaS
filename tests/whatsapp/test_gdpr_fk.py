import uuid
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime


pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("reset_db")]


async def _create_org_with_contact_and_booking(pg_pool):
    """Helper: crea organizzazione + contatto + booking + conversation."""
    org_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test')", org_id)
        await conn.execute(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, $3)",
            contact_id, org_id, "+391234567890",
        )
        await conn.execute(
            "INSERT INTO bookings (organization_id, contact_id, nome_cliente, telefono, data, ora, coperti)"
            " VALUES ($1, $2, 'Mario Rossi', '+391234567890', '2026-08-15', '20:00', 4)",
            org_id, contact_id,
        )
        await conn.execute(
            "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3)",
            uuid.uuid4(), org_id, contact_id,
        )
    return org_id, contact_id


async def test_soft_delete_preserves_booking_data(pg_pool):
    """Soft-delete contatto: booking rimane intatto, conversation deleted_at settato."""
    org_id, contact_id = await _create_org_with_contact_and_booking(pg_pool)

    async with pg_pool.acquire() as conn:
        await conn.execute("UPDATE contacts SET deleted_at = NOW() WHERE id = $1", contact_id)

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT contact_id, nome_cliente, telefono FROM bookings WHERE contact_id = $1", contact_id)
        assert row is not None
        assert row["contact_id"] == contact_id
        assert row["nome_cliente"] == "Mario Rossi"
        assert row["telefono"] == "+391234567890"

        conv_row = await conn.fetchrow(
            "SELECT deleted_at FROM conversations WHERE contact_id = $1", contact_id,
        )
        assert conv_row is not None
        assert conv_row["deleted_at"] is not None


async def test_hard_delete_masks_pii(pg_pool):
    """Hard-delete contatto: booking.contact_id = NULL, nome/telefono = 'REDACTED'."""
    org_id, contact_id = await _create_org_with_contact_and_booking(pg_pool)

    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM contacts WHERE id = $1", contact_id)

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT contact_id, nome_cliente, telefono FROM bookings WHERE organization_id = $1",
            org_id,
        )
        assert row is not None
        assert row["contact_id"] is None
        assert row["nome_cliente"] == "REDACTED"
        assert row["telefono"] == "REDACTED"


async def test_hard_delete_propagates_cascade(pg_pool):
    """Hard-delete contatto: CASCADE elimina conversation e contact_consent_log."""
    org_id, contact_id = await _create_org_with_contact_and_booking(pg_pool)

    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO contact_consent_log (id, contact_id, event_type, method)"
            " VALUES ($1, $2, 'opt_in', 'manual_staff')",
            uuid.uuid4(), contact_id,
        )

    async with pg_pool.acquire() as conn:
        await conn.execute("DELETE FROM contacts WHERE id = $1", contact_id)

    async with pg_pool.acquire() as conn:
        conv_row = await conn.fetchrow(
            "SELECT id FROM conversations WHERE contact_id = $1", contact_id,
        )
        assert conv_row is None

        log_row = await conn.fetchrow(
            "SELECT id FROM contact_consent_log WHERE contact_id = $1", contact_id,
        )
        assert log_row is None


async def test_hard_delete_org_cascade_masks_pii(pg_pool):
    """delete_organization attiva il trigger BEFORE DELETE su contacts
    che anonimizza PII in bookings prima della cascata."""
    org_id, contact_id = await _create_org_with_contact_and_booking(pg_pool)

    from src.core.db.repository import CoreRepository
    repo = CoreRepository(pool=pg_pool)
    await repo.delete_organization(org_id)

    async with pg_pool.acquire() as conn:
        remaining = await conn.fetchval("SELECT COUNT(*) FROM bookings WHERE organization_id = $1", org_id)
        assert remaining == 0

        org_row = await conn.fetchval("SELECT id FROM organizations WHERE id = $1", org_id)
        assert org_row is None


async def test_transaction_rollback_on_usage_failure(pg_pool):
    """Se increment_message_usage fallisce, il messaggio NON viene salvato."""
    from src.whatsapp.router import _handle_inbound_message
    from src.whatsapp.repository import Repository

    repo = Repository(pool=pg_pool)
    org_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test')", org_id)
        await conn.execute(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, $3)",
            contact_id, org_id, "+391234567890",
        )
        await conn.execute(
            "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3)",
            conv_id, org_id, contact_id,
        )

    wam_id = "wamid.rollback.test"

    mock_msg = MagicMock()
    mock_msg.id = wam_id
    mock_msg.from_ = "+391234567890"
    mock_msg.type = "text"
    mock_msg.text.body = "Test rollback"
    mock_msg.model_dump.return_value = {"body": "Test rollback"}

    original_increment = repo.increment_message_usage

    async def failing_increment(org_id, conn=None):
        raise RuntimeError("Simulated DB failure during usage increment")

    repo.increment_message_usage = failing_increment

    with pytest.raises(RuntimeError):
        await _handle_inbound_message(repo, org_id, mock_msg, [])

    repo.increment_message_usage = original_increment

    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM messages WHERE wam_id = $1", wam_id)
        assert row is None, "Message was saved despite usage increment failure — rollback failed"
