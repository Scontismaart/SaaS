import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from src.whatsapp.inbound_processor import InboundProcessor
from src.whatsapp.config import AppConfig, TenantConfig
from src.models.schemas import RispostaOutput


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="test",
    )


@pytest.fixture
def sample_msg():
    return {
        "id": uuid.uuid4(), "organization_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(), "content": {"from": "391234567890"},
        "content_text": "Ciao", "message_type": "text",
    }


@pytest.fixture
def mock_repo(sample_msg):
    repo = AsyncMock()
    repo.claim_inbound_messages = AsyncMock(return_value=[sample_msg])
    repo.reap_stale_claims = AsyncMock(return_value=[])
    repo.pool = MagicMock()
    return repo


@pytest.fixture
def mock_service():
    service = AsyncMock()
    service.check_opt_out = AsyncMock(return_value={"is_opt_out": False, "confidence": "low"})
    service.fast_path_match = AsyncMock(return_value=None)
    service.MessageUsageExceeded = Exception
    return service


@pytest.fixture
def fake_tenant_config():
    return TenantConfig(
        organization_id=uuid.uuid4(),
        phone_number_id="123456",
        waba_id="waba1",
        access_token="decrypted-token",
        business_profile={"nome": "Trattoria Test", "orari": "12-15"},
    )


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

    async def test_ai_reply_sent_when_no_escalation(
        self, app_config, mock_repo, mock_service, fake_tenant_config, sample_msg
    ):
        """Fix task 5: l'AI risponde e non richiede umano -> invio via
        WhatsAppService, nessuna chiamata di rete reale (tutto mockato)."""
        with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
             patch("src.whatsapp.inbound_processor.genera_risposta_async", AsyncMock(return_value=RispostaOutput(
                 risposta="Siamo aperti dalle 12 alle 15.", richiede_umano=False, motivo="orari", categoria="info",
             ))):
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()

        mock_service.send_whatsapp_message.assert_awaited_once()
        call_kwargs = mock_service.send_whatsapp_message.call_args.kwargs
        assert call_kwargs["to_number"] == "391234567890"
        assert call_kwargs["payload"]["text"]["body"] == "Siamo aperti dalle 12 alle 15."
        mock_repo.escalate_to_human.assert_not_called()
        mock_repo.update_message_status.assert_awaited_with(sample_msg["id"], "handled")

    async def test_escalation_when_ai_requires_human(
        self, app_config, mock_repo, mock_service, fake_tenant_config, sample_msg
    ):
        """Fix task 5: l'AI richiede un umano -> escalate_to_human chiamato
        e notifica email inviata (mockata, niente SMTP reale)."""
        mock_repo.escalate_to_human = AsyncMock(return_value={"id": sample_msg["conversation_id"], "ticket_status": "PENDING_STAFF"})

        with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
             patch("src.whatsapp.inbound_processor.genera_risposta_async", AsyncMock(return_value=RispostaOutput(
                 risposta="", richiede_umano=True, motivo="allergie", categoria="reclamo",
             ))), \
             patch("src.whatsapp.inbound_processor.send_escalation_notification", AsyncMock()) as mock_email:
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()

        mock_repo.escalate_to_human.assert_awaited_once_with(str(sample_msg["conversation_id"]))
        mock_email.assert_awaited_once()
        mock_service.send_whatsapp_message.assert_not_called()
        mock_repo.update_message_status.assert_awaited_with(sample_msg["id"], "escalated")

    async def test_escalation_survives_email_failure(
        self, app_config, mock_repo, mock_service, fake_tenant_config, sample_msg
    ):
        """L'escalation (stato ticket) non deve saltare se l'invio email fallisce
        (es. SMTP non configurato)."""
        mock_repo.escalate_to_human = AsyncMock(return_value={"id": sample_msg["conversation_id"], "ticket_status": "PENDING_STAFF"})

        with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
             patch("src.whatsapp.inbound_processor.genera_risposta_async", AsyncMock(return_value=RispostaOutput(
                 risposta="", richiede_umano=True, motivo="reclamo", categoria="reclamo",
             ))), \
             patch("src.whatsapp.inbound_processor.send_escalation_notification", AsyncMock(side_effect=Exception("SMTP down"))):
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()

        mock_repo.escalate_to_human.assert_awaited_once()
        mock_repo.update_message_status.assert_awaited_with(sample_msg["id"], "escalated")

    async def test_fast_path_reply_also_sent_via_whatsapp(
        self, app_config, mock_repo, mock_service, fake_tenant_config, sample_msg
    ):
        mock_service.fast_path_match = AsyncMock(return_value="Ciao! Benvenuto.")
        with patch("src.whatsapp.inbound_processor.load_tenant_config", AsyncMock(return_value=fake_tenant_config)):
            processor = InboundProcessor(app_config, mock_repo, mock_service)
            await processor.process_next_batch()
        mock_service.send_whatsapp_message.assert_awaited_once()
        assert mock_service.send_whatsapp_message.call_args.kwargs["payload"]["text"]["body"] == "Ciao! Benvenuto."
