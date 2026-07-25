import os
import uuid
import pytest
from unittest.mock import patch


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

    async def test_send_escalation_notification_sends_to_owners(self, pg_pool):
        from src.core.notifications.email_service import send_escalation_notification

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

        with patch("src.core.notifications.email_service.smtplib.SMTP") as mock_smtp:
            mock_instance = mock_smtp.return_value.__enter__.return_value

            await send_escalation_notification(
                org_id=str(org["id"]),
                conversation_id=str(conv["id"]),
                contact_name="Test Contact",
                pool=pg_pool
            )

            mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
            sent_email = mock_instance.send_message.call_args[0][0]
            assert "owner@test.com" in sent_email["To"]
            assert "staff@test.com" not in sent_email["To"]

    async def test_send_escalation_notification_no_owners(self, pg_pool):
        from src.core.notifications.email_service import send_escalation_notification

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

        with patch("src.core.notifications.email_service.smtplib.SMTP") as mock_smtp:
            await send_escalation_notification(
                org_id=str(org["id"]),
                conversation_id=str(conv["id"]),
                contact_name="Test",
                pool=pg_pool
            )
            mock_smtp.assert_not_called()
