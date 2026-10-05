from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from run_inbound_processor import process_cycle
from src.core.workers.webhook_inbox_worker import TransactionPool, WebhookInboxWorker
from src.whatsapp.idempotency import WEBHOOK_IDEMPOTENCY_SQL


@pytest.mark.asyncio
async def test_process_cycle_drains_durable_inbox_before_ai_queue():
    calls = []
    inbox_worker = MagicMock()
    processor = MagicMock()
    inbox_worker.process_next_batch = AsyncMock(side_effect=lambda: calls.append("inbox"))
    processor.process_next_batch = AsyncMock(side_effect=lambda: calls.append("processor"))

    await process_cycle(inbox_worker, processor)

    assert calls == ["inbox", "processor"]


@pytest.mark.asyncio
async def test_batch_failure_is_released_for_retry_without_payload_logging(caplog):
    row = {
        "id": "inbox-1",
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "trace_id": "trace-1",
        "lease_token": "lease-1",
        "payload": {"messages": [{"text": "sensitive"}]},
    }
    worker = object.__new__(WebhookInboxWorker)
    worker.inbox = MagicMock()
    worker.inbox.claim = AsyncMock(return_value=[row])
    worker.inbox.fail = AsyncMock()
    worker._process_one = AsyncMock(side_effect=RuntimeError("provider payload leaked?"))

    count = await worker.process_next_batch()

    assert count == 1
    worker.inbox.fail.assert_awaited_once_with(row, "RuntimeError")
    assert "sensitive" not in caplog.text
    assert "provider payload leaked" not in caplog.text


class _Transaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self):
        self.fetchrow = AsyncMock(return_value={"id": "inbox-1"})
        self.execute = AsyncMock()

    def transaction(self):
        return _Transaction()


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


@pytest.mark.asyncio
async def test_transaction_pool_only_forwards_the_reviewed_idempotency_query():
    conn = _Connection()
    pool = TransactionPool(conn)

    await pool.fetchrow(WEBHOOK_IDEMPOTENCY_SQL, "wamid", "message", "")
    conn.fetchrow.assert_awaited_once_with(
        WEBHOOK_IDEMPOTENCY_SQL, "wamid", "message", ""
    )

    with pytest.raises(ValueError, match="only the webhook idempotency query"):
        await pool.fetchrow("SELECT * FROM messages")


@pytest.mark.asyncio
async def test_completion_is_marked_only_after_transactional_ingestion():
    conn = _Connection()
    worker = object.__new__(WebhookInboxWorker)
    worker.pool = _Pool(conn)
    worker._ingest = AsyncMock()
    row = {
        "id": "inbox-1",
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "trace_id": "trace-1",
        "lease_token": "22222222-2222-2222-2222-222222222222",
        "payload": "{}",
        "channel": "whatsapp",
    }

    await worker._process_one(row)

    worker._ingest.assert_awaited_once()
    conn.execute.assert_awaited_once()
    assert "status = 'completed'" in conn.execute.await_args.args[0]


@pytest.mark.asyncio
async def test_lost_lease_does_not_ingest_or_complete():
    conn = _Connection()
    conn.fetchrow.return_value = None
    worker = object.__new__(WebhookInboxWorker)
    worker.pool = _Pool(conn)
    worker._ingest = AsyncMock()
    row = {
        "id": "inbox-1",
        "organization_id": "11111111-1111-1111-1111-111111111111",
        "trace_id": "trace-1",
        "lease_token": "22222222-2222-2222-2222-222222222222",
        "payload": {},
        "channel": "whatsapp",
    }

    await worker._process_one(row)

    worker._ingest.assert_not_awaited()
    conn.execute.assert_not_awaited()
