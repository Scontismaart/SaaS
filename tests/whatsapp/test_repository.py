import asyncio
import uuid
from datetime import datetime

import pytest
from src.whatsapp.repository import Repository


@pytest.mark.asyncio
async def test_get_org_by_phone_number_id(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
        await conn.execute(
            "INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token) "
            "VALUES ($1, $2, '12345', 'waba_1', 'encrypted_token')",
            acc_id, org_id,
        )
    result = await repo.get_org_by_phone_number_id("12345")
    assert result is not None
    assert result["organization_id"] == org_id
    assert result["phone_number_id"] == "12345"


@pytest.mark.asyncio
async def test_get_org_by_phone_number_id_not_found(repo: Repository):
    result = await repo.get_org_by_phone_number_id("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_org_by_waba_id(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
        await conn.execute(
            "INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token) "
            "VALUES ($1, $2, '12345', 'waba_1', 'encrypted_token')",
            acc_id, org_id,
        )
    result = await repo.get_org_by_waba_id("waba_1")
    assert result is not None
    assert result["organization_id"] == org_id


@pytest.mark.asyncio
async def test_get_tenant_config(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
        await conn.execute(
            "INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token) "
            "VALUES ($1, $2, '12345', 'waba_1', 'encrypted_token')",
            acc_id, org_id,
        )
    result = await repo.get_tenant_config(org_id)
    assert result is not None
    assert result["access_token"] == "encrypted_token"
    assert result["phone_number_id"] == "12345"


@pytest.mark.asyncio
async def test_get_or_create_contact_new(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    assert contact["organization_id"] == org_id
    assert contact["phone_number"] == "391234567890"
    assert contact["marketing_opt_out"] is False


@pytest.mark.asyncio
async def test_get_or_create_contact_existing(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    c1 = await repo.get_or_create_contact(org_id, "391234567890")
    c2 = await repo.get_or_create_contact(org_id, "391234567890")
    assert c1["id"] == c2["id"]


@pytest.mark.asyncio
async def test_get_or_create_conversation(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    assert conv["organization_id"] == org_id
    assert conv["contact_id"] == contact["id"]


@pytest.mark.asyncio
async def test_get_contact_prefs(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE contacts SET marketing_opt_out = TRUE WHERE id = $1",
            contact["id"],
        )
    prefs = await repo.get_contact_prefs(org_id, "391234567890")
    assert prefs["marketing_opt_out"] is True


@pytest.mark.asyncio
async def test_upsert_message_new(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(
        id=uuid.uuid4(),
        organization_id=org_id,
        conversation_id=conv["id"],
        wam_id="wamid.test.1",
        direction="inbound",
        message_type="text",
        content={"text": {"body": "Ciao"}},
        content_text="Ciao",
        status="received_pending_ai",
    )
    assert msg["wam_id"] == "wamid.test.1"
    assert msg["status"] == "received_pending_ai"


@pytest.mark.asyncio
async def test_upsert_message_idempotent(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    mid = uuid.uuid4()
    msg1 = await repo.upsert_message(mid, org_id, conv["id"], "wamid.test.2", "inbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "received_pending_ai")
    msg2 = await repo.upsert_message(mid, org_id, conv["id"], "wamid.test.2", "inbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "received_pending_ai")
    assert msg1["id"] == msg2["id"]


@pytest.mark.asyncio
async def test_update_message_status_with_guard(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.test.3", "outbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "queued")
    updated = await repo.update_message_status(msg["id"], "delivered", wam_id="wamid.test.3")
    assert updated["status"] == "delivered"
    updated2 = await repo.update_message_status(msg["id"], "sent")
    assert updated2["status"] == "delivered"
    updated3 = await repo.update_message_status(msg["id"], "failed")
    assert updated3["status"] == "failed"


@pytest.mark.asyncio
async def test_claim_inbound_messages_skip_locked(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    for i in range(3):
        await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], f"wamid.in.{i}", "inbound", "text",
                                  {"text": {"body": f"Msg {i}"}}, f"Msg {i}", "received_pending_ai")
    claimed = await repo.claim_inbound_messages(limit=10)
    assert len(claimed) == 3
    for c in claimed:
        assert c["status"] == "processing"


@pytest.mark.asyncio
async def test_claim_inbound_messages_no_double_claim(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    for i in range(5):
        await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], f"wamid.nd.{i}", "inbound", "text",
                                  {"text": {"body": f"Msg {i}"}}, f"Msg {i}", "received_pending_ai")
    async with pg_pool.acquire() as conn_a, pg_pool.acquire() as conn_b:
        repo_a = Repository.__new__(Repository)
        repo_a.pool = pg_pool
        repo_b = Repository.__new__(Repository)
        repo_b.pool = pg_pool
        results = await asyncio.gather(
            repo_a.claim_inbound_messages(limit=5),
            repo_b.claim_inbound_messages(limit=5),
        )
        all_ids = [r["id"] for r in results[0]] + [r["id"] for r in results[1]]
        assert len(all_ids) == len(set(all_ids))


@pytest.mark.asyncio
async def test_record_consent_event(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    event = await repo.record_consent_event(
        contact_id=contact["id"],
        event_type="opt_out",
        method="keyword_match",
        matched_text="stop",
    )
    assert event["event_type"] == "opt_out"
    assert event["method"] == "keyword_match"


@pytest.mark.asyncio
async def test_insert_and_update_delivery_attempt(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.da.1", "outbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "queued")
    attempt = await repo.insert_delivery_attempt(msg["id"], next_retry_at=datetime.utcnow())
    assert attempt["status"] == "pending"
    updated = await repo.update_delivery_attempt(attempt["id"], "succeeded", error_details=None)
    assert updated["status"] == "succeeded"


@pytest.mark.asyncio
async def test_reap_stale_claims(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.reap.1", "inbound", "text",
                                      {"text": {"body": "Old"}}, "Old", "received_pending_ai")
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET status = 'processing', claimed_at = NOW() - INTERVAL '10 minutes' WHERE id = $1",
            msg["id"],
        )
    reaped = await repo.reap_stale_claims(timeout_minutes=5)
    assert len(reaped) == 1
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM messages WHERE id = $1", msg["id"])
        assert row["status"] == "received_pending_ai"


@pytest.mark.asyncio
async def test_reconstruct_payload_for_retry(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    content = {"type": "text", "text": {"body": "Retry me"}}
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.recon.1", "outbound", "text",
                                      content, "Retry me", "queued")
    payload = await repo.reconstruct_payload_for_retry(msg["id"])
    assert payload is not None
    assert payload["content"] == content


@pytest.mark.asyncio
async def test_save_tenant_config_encrypts_token(repo: Repository, pg_pool):
    import os
    from cryptography.fernet import Fernet
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        pytest.skip("ENCRYPTION_KEY not set")
    cipher = Fernet(key.encode())
    raw_token = "EAAxRealTestToken123"
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    await repo.save_tenant_config(org_id, "12345", "waba_1", raw_token)
    row = await repo.get_tenant_config(org_id)
    assert row["access_token"] != raw_token
    decrypted = cipher.decrypt(row["access_token"].encode()).decode()
    assert decrypted == raw_token


@pytest.mark.asyncio
async def test_encryption_key_rotation_handles_invalid_token(repo: Repository, pg_pool):
    from cryptography.fernet import Fernet, InvalidToken
    raw = "EAAxRotationTest"
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    await repo.save_tenant_config(org_id, "12345", "waba_2", raw)
    row = await repo.get_tenant_config(org_id)
    new_key = Fernet.generate_key().decode()
    with pytest.raises(InvalidToken):
        Fernet(new_key.encode()).decrypt(row["access_token"].encode())
