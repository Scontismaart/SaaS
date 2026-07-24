import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from src.whatsapp.inbound_processor import InboundProcessor
from src.whatsapp.config import AppConfig


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="test",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.claim_inbound_messages = AsyncMock(return_value=[
        {"id": uuid.uuid4(), "organization_id": uuid.uuid4(), "content": {},
         "content_text": "Ciao", "message_type": "text", "from_": "391234567890"}
    ])
    repo.reap_stale_claims = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_service():
    service = AsyncMock()
    service.check_opt_out = AsyncMock(return_value={"is_opt_out": False, "confidence": "low"})
    service.fast_path_match = AsyncMock(return_value=None)
    return service


class TestInboundProcessor:
    async def test_process_one_message(self, app_config, mock_repo, mock_service):
        processor = InboundProcessor(app_config, mock_repo, mock_service)
        await processor.process_next_batch()
        mock_repo.claim_inbound_messages.assert_called_once()

    async def test_reaper_called(self, app_config, mock_repo, mock_service):
        processor = InboundProcessor(app_config, mock_repo, mock_service)
        await processor.process_next_batch()
        mock_repo.reap_stale_claims.assert_called_once()

    async def test_opt_out_skips_fast_path(self, app_config, mock_repo, mock_service):
        mock_service.check_opt_out = AsyncMock(return_value={"is_opt_out": True, "confidence": "high"})
        processor = InboundProcessor(app_config, mock_repo, mock_service)
        await processor.process_next_batch()
        mock_service.fast_path_match.assert_not_called()
