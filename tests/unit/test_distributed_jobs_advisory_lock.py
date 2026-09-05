from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.core.jobs.base import compute_advisory_lock_id, execute_with_advisory_lock
from src.whatsapp.idempotency import purge_webhook_idempotency
from src.core.retention_job import run_retention


def test_compute_advisory_lock_id_deterministic_and_bigint_range():
    key1 = "job_retention"
    key2 = "job_reminders"
    id1 = compute_advisory_lock_id(key1)
    id2 = compute_advisory_lock_id(key2)
    id1_again = compute_advisory_lock_id(key1)

    assert id1 == id1_again
    assert id1 != id2
    # Postgres bigint range
    assert -9223372036854775808 <= id1 <= 9223372036854775807
    assert -9223372036854775808 <= id2 <= 9223372036854775807


@pytest.mark.asyncio
async def test_execute_with_advisory_lock_acquired():
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=True)  # Lock acquired
    mock_conn.execute = AsyncMock()  # Unlock call
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    job_called = False

    async def fake_job(pool):
        nonlocal job_called
        job_called = True

    result = await execute_with_advisory_lock(mock_pool, "test_job", fake_job)

    assert result is True
    assert job_called is True
    mock_conn.fetchval.assert_called_once()
    mock_conn.execute.assert_called_once()
    assert "pg_advisory_unlock" in mock_conn.execute.call_args[0][0]


@pytest.mark.asyncio
async def test_execute_with_advisory_lock_skipped_when_held():
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=False)  # Another instance holds lock
    mock_conn.execute = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    job_called = False

    async def fake_job(pool):
        nonlocal job_called
        job_called = True

    result = await execute_with_advisory_lock(mock_pool, "test_job", fake_job)

    assert result is False
    assert job_called is False
    mock_conn.fetchval.assert_called_once()
    # Unlock should not be called because lock was never acquired
    mock_conn.execute.assert_not_called()


@pytest.mark.asyncio
async def test_execute_with_advisory_lock_unlocks_on_job_exception():
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_conn.execute = AsyncMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    async def failing_job(pool):
        raise RuntimeError("Job crashed")

    with pytest.raises(RuntimeError, match="Job crashed"):
        await execute_with_advisory_lock(mock_pool, "test_job", failing_job)

    # Unlock MUST be called in finally despite exception
    mock_conn.execute.assert_called_once()
    assert "pg_advisory_unlock" in mock_conn.execute.call_args[0][0]


@pytest.mark.asyncio
async def test_purge_webhook_idempotency():
    mock_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock(return_value="DELETE 15")
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    deleted = await purge_webhook_idempotency(mock_pool, days=7)
    assert deleted == 15
    mock_conn.execute.assert_called_once()
    assert "DELETE FROM webhook_idempotency" in mock_conn.execute.call_args[0][0]


@pytest.mark.asyncio
async def test_run_retention_includes_webhook_purge():
    mock_pool = MagicMock()
    with patch("src.whatsapp.repository.Repository") as mock_repo_cls, \
         patch("src.whatsapp.idempotency.purge_webhook_idempotency", new_callable=AsyncMock) as mock_purge:
        mock_repo = MagicMock()
        mock_repo.delete_expired_messages = AsyncMock(return_value=5)
        mock_repo.purge_soft_deleted_messages = AsyncMock(return_value=2)
        mock_repo.cleanup_empty_conversations = AsyncMock(return_value=1)
        mock_repo_cls.return_value = mock_repo
        mock_purge.return_value = 10

        await run_retention(mock_pool)

        mock_purge.assert_called_once_with(mock_pool, days=7)
        mock_repo.delete_expired_messages.assert_called_once()
        mock_repo.purge_soft_deleted_messages.assert_called_once()
        mock_repo.cleanup_empty_conversations.assert_called_once()
