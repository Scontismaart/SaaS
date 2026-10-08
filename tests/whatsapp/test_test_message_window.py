"""Real PostgreSQL regression for the tenant-scoped test-message window."""
import uuid

import pytest


@pytest.mark.parametrize("variant", ["valid", "foreign", "old", "future", "instagram", "deleted"])
async def test_only_recent_same_tenant_whatsapp_inbound_opens_window(repo, pg_pool, variant):
    org = uuid.uuid4()
    other_org = uuid.uuid4()
    phone = "39000000000"
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id,name) VALUES ($1,'Synthetic window QA'),($2,'Synthetic foreign QA')", org, other_org)
    contact = await repo.get_or_create_contact(org, phone)
    conversation = await repo.get_or_create_conversation(org, contact["id"], canale="instagram" if variant == "instagram" else "whatsapp")
    message = await repo.upsert_message(
        id=uuid.uuid4(), organization_id=org, conversation_id=conversation["id"],
        wam_id="wamid.window." + uuid.uuid4().hex, direction="inbound",
        message_type="text", content={"text": {"body": "Synthetic test"}},
        content_text="Synthetic test", status="received_pending_ai",
    )
    async with pg_pool.acquire() as conn:
        if variant == "old":
            await conn.execute("UPDATE messages SET created_at=NOW()-INTERVAL '25 hours' WHERE id=$1", message["id"])
        elif variant == "future":
            await conn.execute("UPDATE messages SET created_at=NOW()+INTERVAL '1 hour' WHERE id=$1", message["id"])
        elif variant == "deleted":
            await conn.execute("UPDATE messages SET deleted_at=NOW() WHERE id=$1", message["id"])
    checked_org = other_org if variant == "foreign" else org
    assert await repo.has_recent_whatsapp_inbound(checked_org, phone) is (variant == "valid")
