import uuid
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from src.whatsapp.retry_worker import RetryWorker
from src.whatsapp.config import AppConfig
from uuid import UUID


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test",
        encryption_key="key",
        postgres_dsn="",
        verify_token="test",
        max_retry_attempts=5,
    )


@pytest.fixture
def mock_tenant():
    from src.whatsapp.config import TenantConfig
    return TenantConfig(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        phone_number_id="12345",
        waba_id="waba_1",
        access_token="test_token",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.claim_delivery_attempts = AsyncMock(return_value=[
        {"id": uuid.uuid4(), "message_id": uuid.uuid4(), "attempt_number": 1, "status": "processing"},
        {"id": uuid.uuid4(), "message_id": uuid.uuid4(), "attempt_number": 3, "status": "processing"},
    ])
    repo.reap_stale_claims = AsyncMock(return_value=[])
    repo.reconstruct_payload_for_retry = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "content": {},
    })
    repo.update_message_status = AsyncMock()
    repo.update_delivery_attempt = AsyncMock()
    repo.insert_delivery_attempt = AsyncMock()
    return repo


@pytest.fixture
def mock_service():
    service = AsyncMock()
    service.attempt_delivery = AsyncMock(side_effect=Exception("Meta unavailable"))
    return service


patching = "src.whatsapp.config.load_tenant_config"


class TestRetryWorker:
    async def test_process_batch(self, app_config, mock_repo, mock_service, mock_tenant):
        with patch(patching, AsyncMock(return_value=mock_tenant)):
            worker = RetryWorker(app_config, mock_repo, mock_service)
            await worker.process_next_batch()
            mock_repo.claim_delivery_attempts.assert_called_once()

    async def test_reaper_called(self, app_config, mock_repo, mock_service, mock_tenant):
        with patch(patching, AsyncMock(return_value=mock_tenant)):
            worker = RetryWorker(app_config, mock_repo, mock_service)
            await worker.process_next_batch()
            mock_repo.reap_stale_claims.assert_called_once()

    async def test_failed_attempt_increments(self, app_config, mock_repo, mock_service, mock_tenant):
        with patch(patching, AsyncMock(return_value=mock_tenant)):
            worker = RetryWorker(app_config, mock_repo, mock_service)
            await worker.process_next_batch()
            assert mock_repo.update_delivery_attempt.call_count == 2

    async def test_attempt_success(self, app_config, mock_repo, mock_tenant):
        mock_service = AsyncMock()
        mock_service.attempt_delivery = AsyncMock(return_value={"status": "sent", "wam_id": "wamid.test"})
        with patch(patching, AsyncMock(return_value=mock_tenant)):
            worker = RetryWorker(app_config, mock_repo, mock_service)
            await worker.process_next_batch()
            assert mock_repo.update_delivery_attempt.call_count == 2

    async def test_dead_letter_after_max_retries(self, app_config, mock_repo, mock_tenant):
        mock_repo.claim_delivery_attempts = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "message_id": uuid.uuid4(),
             "attempt_number": 5, "status": "processing"},
        ])
        mock_service = AsyncMock()
        mock_service.attempt_delivery = AsyncMock(side_effect=Exception("Still failing"))
        with patch(patching, AsyncMock(return_value=mock_tenant)):
            worker = RetryWorker(app_config, mock_repo, mock_service)
            await worker.process_next_batch()
            mock_repo.update_message_status.assert_called_once()
