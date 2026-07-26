import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.whatsapp.inbound_processor import InboundProcessor
from src.whatsapp.config import AppConfig, TenantConfig


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
    repo.pool = MagicMock()
    return repo


@pytest.fixture
def mock_service():
    service = AsyncMock()
    service.check_opt_out = AsyncMock(return_value={"is_opt_out": False})
    service.fast_path_match = AsyncMock(return_value=None)
    service.MessageUsageExceeded = Exception
    return service


@pytest.fixture
def mock_booking_service():
    svc = AsyncMock()
    svc.handle_reminder_reply = AsyncMock(return_value=None)
    return svc


@pytest.fixture
def processor(app_config, mock_repo, mock_service, mock_booking_service):
    return InboundProcessor(app_config, mock_repo, mock_service, booking_service=mock_booking_service)


@pytest.fixture
def sample_msg():
    return {
        "id": uuid.uuid4(),
        "organization_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "content": {"from": "+393331234567"},
        "content_text": "Si confermo",
        "message_type": "text",
    }


@pytest.fixture
def fake_tenant_config():
    return TenantConfig(
        organization_id=uuid.uuid4(),
        phone_number_id="123456",
        waba_id="waba1",
        access_token="decrypted-token",
        business_profile={"nome": "Trattoria Test", "orari": "12-15"},
    )


@pytest.mark.asyncio
async def test_reminder_hook_called_after_opt_out(processor, mock_booking_service, sample_msg):
    """Reminder hook called after opt-out, before AI."""
    mock_booking_service.handle_reminder_reply.return_value = "confirmed"
    await processor._process_one(sample_msg)
    mock_booking_service.handle_reminder_reply.assert_called_once()


@pytest.mark.asyncio
async def test_opt_out_wins_over_reminder(processor, mock_booking_service, sample_msg):
    """Opt-out check comes BEFORE reminder hook."""
    processor.service.check_opt_out = AsyncMock(return_value={"is_opt_out": True, "confidence": "high"})
    await processor._process_one(sample_msg)
    mock_booking_service.handle_reminder_reply.assert_not_called()


@pytest.mark.asyncio
async def test_reminder_returns_none_continues_to_ai(processor, mock_booking_service, sample_msg, fake_tenant_config):
    """When handle_reminder_reply returns None, processing continues to fast_path/AI."""
    mock_booking_service.handle_reminder_reply.return_value = None
    with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
         patch("src.whatsapp.inbound_processor.genera_risposta_async", AsyncMock(return_value=MagicMock(
             richiede_umano=False, risposta="OK",
         ))):
        await processor._process_one(sample_msg)
    mock_booking_service.handle_reminder_reply.assert_called_once()
    processor.service.fast_path_match.assert_called_once()


@pytest.mark.asyncio
async def test_reminder_no_booking_service(app_config, mock_repo, mock_service, sample_msg, fake_tenant_config):
    """Without booking_service, no reminder hook is called."""
    processor = InboundProcessor(app_config, mock_repo, mock_service)
    with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
         patch("src.whatsapp.inbound_processor.genera_risposta_async", AsyncMock(return_value=MagicMock(
             richiede_umano=False, risposta="OK",
         ))):
        await processor._process_one(sample_msg)
    mock_service.fast_path_match.assert_called_once()
