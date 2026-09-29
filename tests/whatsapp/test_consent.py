import uuid

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def org_id(pg_pool):
    oid = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", oid)
    return oid


@pytest_asyncio.fixture
async def contact(repo, org_id):
    async def _make(phone="391234567890"):
        return await repo.get_or_create_contact(org_id, phone)
    return _make


@pytest.mark.asyncio
async def test_record_consent_opt_out_sets_contact_status(repo, contact, org_id):
    c = await contact()
    await repo.record_consent_event(c["id"], "opt_out", "keyword_match", organization_id=org_id)
    status = await repo.get_contact_consent(c["id"], org_id)
    assert status == "withdrawn"
    prefs = await repo.get_contact_prefs(org_id, "391234567890")
    assert prefs["marketing_opt_out"] is True
    async with repo.pool.acquire() as conn:
        audit_count = await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE organization_id = $1 AND target_id = $2",
            org_id, c["id"],
        )
    assert audit_count == 1


@pytest.mark.asyncio
async def test_duplicate_stop_message_has_one_event_and_audit(repo, contact, org_id):
    c = await contact()
    message_id = uuid.uuid4()
    async with repo.pool.acquire() as conn:
        conversation_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO conversations(id, organization_id, contact_id) VALUES ($1, $2, $3)",
            conversation_id, org_id, c["id"],
        )
        await conn.execute(
            "INSERT INTO messages(id, organization_id, conversation_id, direction, "
            "message_type, content, status) "
            "VALUES ($1, $2, $3, 'inbound', 'text', '{}', 'received_pending_ai')",
            message_id, org_id, conversation_id,
        )
    first = await repo.record_consent_event(
        c["id"], "opt_out", "keyword_match",
        triggering_message_id=message_id, organization_id=org_id,
    )
    second = await repo.record_consent_event(
        c["id"], "opt_out", "keyword_match",
        triggering_message_id=message_id, organization_id=org_id,
    )
    assert first["id"] == second["id"]
    async with repo.pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM contact_consent_log WHERE triggering_message_id = $1",
            message_id,
        ) == 1
        assert await conn.fetchval(
            "SELECT count(*) FROM audit_log WHERE organization_id = $1 AND target_id = $2",
            org_id, c["id"],
        ) == 1


@pytest.mark.asyncio
async def test_record_consent_opt_in_sets_contact_status(repo, contact, org_id):
    c = await contact()
    await repo.record_consent_event(c["id"], "opt_in", "manual_staff", organization_id=org_id)
    status = await repo.get_contact_consent(c["id"], org_id)
    assert status == "granted"


@pytest.mark.asyncio
async def test_contact_default_consent(repo, contact, org_id):
    c = await contact()
    status = await repo.get_contact_consent(c["id"], org_id)
    assert status == "unknown"


@pytest.mark.asyncio
async def test_consent_status_deleted_contact_returns_none(repo, contact, org_id):
    c = await contact()
    async with repo.pool.acquire() as conn:
        await conn.execute("UPDATE contacts SET deleted_at = NOW() WHERE id = $1", c["id"])
    status = await repo.get_contact_consent(c["id"], org_id)
    assert status is None


@pytest.mark.asyncio
async def test_security_audit_logger_writes_to_file(tmp_path):
    import os
    from src.core.security_logger import security_audit

    log_dir = str(tmp_path)
    import src.core.security_logger as sl
    original_dir = sl._LOG_DIR
    sl._LOG_DIR = log_dir
    sl._handler.close()
    sl._logger.removeHandler(sl._handler)
    new_handler = sl.logging.FileHandler(os.path.join(log_dir, "security-audit.log"), encoding="utf-8")
    new_handler.setFormatter(sl.logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z"))
    sl._logger.addHandler(new_handler)
    sl._handler = new_handler
    try:
        security_audit("consent_opt_out", contact_id="abc-123", organization_id="org-456")
        log_path = os.path.join(log_dir, "security-audit.log")
        assert os.path.exists(log_path)
        content = open(log_path).read()
        assert "consent_opt_out" in content
        assert "abc-123" in content
    finally:
        sl._LOG_DIR = original_dir
