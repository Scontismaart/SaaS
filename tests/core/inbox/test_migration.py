import uuid
import pytest


pytestmark = pytest.mark.usefixtures("reset_db")


class TestHITLMigration:
    async def test_conversation_columns_exist(self, pg_pool):
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'conversations' AND column_name = 'ticket_status'"
            )
            assert row is not None
            assert row["data_type"] == "text"

            row = await conn.fetchrow(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'conversations' AND column_name = 'version'"
            )
            assert row is not None
            assert row["data_type"] == "integer"

            row = await conn.fetchrow(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = 'messages' AND column_name = 'idempotency_key'"
            )
            assert row is not None
            assert row["data_type"] == "text"

    async def test_ticket_status_default(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4()
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234567') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING ticket_status, version",
                uuid.uuid4(), org["id"], contact["id"]
            )
            assert conv["ticket_status"] == "AI_ACTIVE"
            assert conv["version"] == 1

    async def test_ticket_status_check(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4()
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234568') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            with pytest.raises(Exception, match="ticket_status"):
                await conn.execute(
                    "INSERT INTO conversations (id, organization_id, contact_id, ticket_status) VALUES ($1, $2, $3, 'INVALID')",
                    uuid.uuid4(), org["id"], contact["id"]
                )

    async def test_idempotency_key_unique_partial(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
                uuid.uuid4()
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234569') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
                uuid.uuid4(), org["id"], contact["id"]
            )
            msg1 = await conn.fetchrow(
                """INSERT INTO messages (id, organization_id, conversation_id, direction, message_type, content, status, idempotency_key)
                   VALUES ($1, $2, $3, 'outbound', 'text', '{}'::jsonb, 'sent', 'key-abc-123') RETURNING id""",
                uuid.uuid4(), org["id"], conv["id"]
            )
            assert msg1 is not None
            with pytest.raises(Exception):
                await conn.execute(
                    """INSERT INTO messages (id, organization_id, conversation_id, direction, message_type, content, status, idempotency_key)
                       VALUES ($1, $2, $3, 'outbound', 'text', '{}'::jsonb, 'sent', 'key-abc-123')""",
                    uuid.uuid4(), org["id"], conv["id"]
                )
            # Different org should allow same key
            org2 = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Test2') RETURNING id",
                uuid.uuid4()
            )
            contact2 = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234570') RETURNING id",
                uuid.uuid4(), org2["id"]
            )
            conv2 = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
                uuid.uuid4(), org2["id"], contact2["id"]
            )
            msg2 = await conn.fetchrow(
                """INSERT INTO messages (id, organization_id, conversation_id, direction, message_type, content, status, idempotency_key)
                   VALUES ($1, $2, $3, 'outbound', 'text', '{}'::jsonb, 'sent', 'key-abc-123') RETURNING id""",
                uuid.uuid4(), org2["id"], conv2["id"]
            )
            assert msg2 is not None
