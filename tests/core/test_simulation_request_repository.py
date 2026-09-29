from contextlib import asynccontextmanager
from datetime import datetime, timezone
import uuid

import pytest

from src.core.db.repositories.message_repo import MessageRepository
from src.core.db.scoping import TENANT_SCOPED_TABLES


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Connection:
    def __init__(self, *, inserted=None, quota=None, existing=None, completed=None,
                 existing_record=None):
        self.inserted = inserted
        self.quota = quota
        self.existing = existing
        self.completed = completed
        self.existing_record = existing_record
        self.calls = []

    def transaction(self):
        return _Transaction()

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "INSERT INTO simulation_requests" in sql:
            return self.inserted
        if "UPDATE organizations" in sql:
            return self.quota
        if "SELECT payload_hash, status, response" in sql:
            return self.existing
        if "SELECT status, payload_hash, claim_token FROM simulation_requests" in sql:
            return self.existing_record
        if "UPDATE simulation_requests" in sql:
            return self.completed
        return None

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "DELETE 1"


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.mark.asyncio
async def test_new_simulation_request_atomically_reserves_quota():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim_token = uuid.uuid4()
    conn = _Connection(inserted={"status": "reserved", "claim_token": claim_token}, quota={"id": org_id})
    result = await MessageRepository(_Pool(conn)).reserve_simulation_request(
        org_id, user_id, request_id, "a" * 64,
    )
    assert result == {"status": "reserved", "claim_token": claim_token}
    assert len(conn.calls) == 2
    assert "INSERT INTO simulation_requests" in conn.calls[0][0]
    assert "messages_used_this_period < messages_limit" in conn.calls[1][0]
    assert conn.calls[0][1][:3] == (org_id, user_id, request_id)


@pytest.mark.asyncio
async def test_quota_exhaustion_rolls_back_new_idempotency_row():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _Connection(inserted={"status": "reserved", "claim_token": uuid.uuid4()}, quota=None)
    result = await MessageRepository(_Pool(conn)).reserve_simulation_request(
        org_id, user_id, request_id, "b" * 64,
    )
    assert result == {"status": "quota_exceeded"}
    assert "DELETE FROM simulation_requests" in conn.calls[-1][0]
    assert conn.calls[-1][1][:3] == (org_id, user_id, request_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_hash,status,expected",
    [
        ("c" * 64, "completed", {"status": "replay", "response": {"risposta": "ok"}}),
        ("different", "completed", {"status": "payload_conflict"}),
        ("c" * 64, "reserved", {"status": "in_progress"}),
    ],
)
async def test_existing_simulation_request_resolves_replay_conflict_or_in_progress(
    payload_hash, status, expected,
):
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _Connection(
        existing={
            "payload_hash": "c" * 64,
            "status": status,
            "response": {"risposta": "ok"},
            "reserved_at": datetime.now(timezone.utc),
        },
    )
    result = await MessageRepository(_Pool(conn)).reserve_simulation_request(
        org_id, user_id, request_id, payload_hash,
    )
    assert result == expected
    assert len(conn.calls) == (3 if status == "reserved" else 2)


@pytest.mark.asyncio
async def test_completion_persists_cached_response_and_table_is_tenant_scoped():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim_token = uuid.uuid4()
    conn = _Connection(completed={"request_id": request_id})
    result = await MessageRepository(_Pool(conn)).complete_simulation_request(
        org_id, user_id, request_id, "d" * 64, claim_token, {"risposta": "ok"},
    )
    assert result is True
    sql, args = conn.calls[0]
    assert "status = 'completed'" in sql
    assert args[:5] == (org_id, user_id, request_id, "d" * 64, claim_token)
    assert "claim_token = $5::uuid" in sql
    assert "simulation_requests" in TENANT_SCOPED_TABLES


@pytest.mark.asyncio
async def test_failed_simulation_can_retry_under_same_idempotency_key():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim_token = uuid.uuid4()
    conn = _Connection(
        completed={"claim_token": claim_token},
        existing={
            "payload_hash": "e" * 64,
            "status": "failed",
            "response": None,
            "reserved_at": datetime.now(timezone.utc),
        },
    )
    result = await MessageRepository(_Pool(conn)).reserve_simulation_request(
        org_id, user_id, request_id, "e" * 64,
    )
    assert result == {"status": "reserved", "claim_token": claim_token}
    assert not any("UPDATE organizations" in sql for sql, _ in conn.calls)
    assert any("SET status = 'reserved', reserved_at = NOW()" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
async def test_failed_simulation_marks_failure_and_keeps_quota_reservation():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim_token = uuid.uuid4()
    conn = _Connection(completed={"request_id": request_id})
    result = await MessageRepository(_Pool(conn)).fail_simulation_request(
        org_id, user_id, request_id, "f" * 64, claim_token,
    )
    assert result is True
    assert "status = 'failed'" in conn.calls[0][0]
    assert "claim_token = $5::uuid" in conn.calls[0][0]


@pytest.mark.asyncio
async def test_stale_reservation_is_reclaimed_without_double_charging_quota():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    claim_token = uuid.uuid4()
    conn = _Connection(
        existing={
            "payload_hash": "a" * 64,
            "status": "reserved",
            "response": None,
            "reserved_at": datetime(2000, 1, 1, tzinfo=timezone.utc),
        },
        completed={"claim_token": claim_token},
    )
    result = await MessageRepository(_Pool(conn)).reserve_simulation_request(
        org_id, user_id, request_id, "a" * 64,
    )
    assert result == {"status": "reserved", "claim_token": claim_token}
    assert not any("UPDATE organizations" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
async def test_previous_claim_cannot_complete_after_stale_reservation_reclaim():
    org_id, user_id, request_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    previous_claim, current_claim = uuid.uuid4(), uuid.uuid4()
    conn = _Connection(
        existing_record={
            "status": "reserved",
            "payload_hash": "b" * 64,
            "claim_token": current_claim,
        },
    )
    result = await MessageRepository(_Pool(conn)).complete_simulation_request(
        org_id, user_id, request_id, "b" * 64, previous_claim, {"risposta": "vecchia"},
    )
    assert result is False
    assert "claim_token = $5::uuid" in conn.calls[0][0]
