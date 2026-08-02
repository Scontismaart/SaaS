import os
import uuid
import asyncio
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.usefixtures("reset_db")


class TestEmailService:
    @pytest.fixture(autouse=True)
    def _setup_env(self):
        old = {}
        for k in ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"]:
            old[k] = os.environ.get(k)
        os.environ["SMTP_HOST"] = "smtp.example.com"
        os.environ["SMTP_PORT"] = "587"
        os.environ["SMTP_USER"] = "user@example.com"
        os.environ["SMTP_PASSWORD"] = "secret"
        os.environ["SMTP_FROM"] = "noreply@example.com"
        yield
        for k, v in old.items():
            if v is None:
                del os.environ[k]
            else:
                os.environ[k] = v

    @pytest.fixture
    async def org_and_conv(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4()
            )
            auth_owner = await conn.fetchrow(
                "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                "owner@test.com"
            )
            auth_staff = await conn.fetchrow(
                "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                "staff@test.com"
            )
            owner_profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_owner["id"]
            )
            staff_profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_staff["id"]
            )
            await conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'owner')",
                org["id"], owner_profile["id"]
            )
            await conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
                org["id"], staff_profile["id"]
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234567') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
                uuid.uuid4(), org["id"], contact["id"]
            )
        return org, conv

    async def test_send_with_retry_sends_to_owners(self, pg_pool, org_and_conv):
        from src.core.notifications.email_service import _send_with_retry, EmailEvent

        org, conv = org_and_conv
        event = EmailEvent(
            org_id=str(org["id"]),
            subject="New escalation: Test Contact",
            body=f"Conversation ID: {conv['id']}\nOpen the inbox to claim this ticket.",
            pool=pg_pool,
        )

        with patch("src.core.notifications.email_service.smtplib.SMTP") as mock_smtp:
            mock_instance = mock_smtp.return_value.__enter__.return_value

            await _send_with_retry(event)

            mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
            sent_email = mock_instance.send_message.call_args[0][0]
            assert "owner@test.com" in sent_email["To"]
            assert "staff@test.com" not in sent_email["To"]

    async def test_send_with_retry_no_owners_skips(self, pg_pool):
        from src.core.notifications.email_service import _send_with_retry, EmailEvent

        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4()
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234568') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
                uuid.uuid4(), org["id"], contact["id"]
            )

        event = EmailEvent(
            org_id=str(org["id"]),
            subject="Test",
            body="Test",
            pool=pg_pool,
        )

        with patch("src.core.notifications.email_service.smtplib.SMTP") as mock_smtp:
            await _send_with_retry(event)
            mock_smtp.assert_not_called()

    async def test_enqueue_escalation_adds_to_queue(self, pg_pool):
        from src.core import notifications

        notifications.email_service.start_worker()
        q = notifications.email_service._queue
        assert q is not None
        assert q.qsize() == 0

        notifications.email_service.enqueue_escalation(
            org_id="test-org",
            conversation_id="test-conv",
            contact_name="Test",
            pool=pg_pool,
        )

        assert q.qsize() == 1

        notifications.email_service.stop_worker()
