import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from src.whatsapp.service import WhatsAppService
from src.whatsapp.config import AppConfig, TenantConfig


OPT_OUT_KEYWORDS = {
    "it": ["stop", "annulla", "basta", "non scrivermi più", "cancellami", "disiscrivi"],
    "en": ["stop", "unsubscribe", "cancel", "opt out", "remove me"],
}


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test_secret",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="test_token",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_or_create_contact = AsyncMock(return_value={"id": uuid.uuid4(), "marketing_opt_out": False})
    repo.get_or_create_conversation = AsyncMock(return_value={"id": uuid.uuid4()})
    repo.get_contact_prefs = AsyncMock(return_value={"id": uuid.uuid4(), "marketing_opt_out": False})
    repo.upsert_message = AsyncMock(return_value={"id": uuid.uuid4(), "status": "queued"})
    repo.update_message_status = AsyncMock(return_value={"id": uuid.uuid4(), "status": "sent"})
    return repo


@pytest.fixture
def mock_meta_client():
    client = AsyncMock()
    client.send_message = AsyncMock()
    client.send_message.return_value.messages = [MagicMock(id="wamid.outbound.test")]
    client.send_message.return_value.contacts = [MagicMock(wa_id="391234567890")]
    client.send_message.return_value.messaging_product = "whatsapp"
    return client


class TestWhatsAppService:
    async def test_send_whatsapp_message_creates_message(self, app_config, mock_repo, mock_meta_client):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.send_whatsapp_message(
            org_id=uuid.uuid4(),
            to_number="391234567890",
            payload={"type": "text", "text": {"body": "Ciao!"}},
            category="utility",
            meta_client=mock_meta_client,
            tenant_config=MagicMock(),
        )
        assert result["status"] == "sent"
        mock_repo.upsert_message.assert_called_once()

    async def test_opt_out_gate_blocks_marketing(self, app_config, mock_repo, mock_meta_client):
        mock_repo.get_contact_prefs = AsyncMock(return_value={"marketing_opt_out": True, "id": uuid.uuid4()})
        service = WhatsAppService(app_config, mock_repo)
        with pytest.raises(service.MessageBlockedByOptOut):
            await service.send_whatsapp_message(
                org_id=uuid.uuid4(),
                to_number="391234567890",
                payload={"type": "text", "text": {"body": "Offerta speciale!"}},
                category="marketing",
                meta_client=mock_meta_client,
                tenant_config=MagicMock(),
            )

    async def test_opt_out_gate_allows_utility(self, app_config, mock_repo, mock_meta_client):
        mock_repo.get_contact_prefs = AsyncMock(return_value={"marketing_opt_out": True, "id": uuid.uuid4()})
        service = WhatsAppService(app_config, mock_repo)
        result = await service.send_whatsapp_message(
            org_id=uuid.uuid4(),
            to_number="391234567890",
            payload={"type": "text", "text": {"body": "Conferma prenotazione #123"}},
            category="utility",
            meta_client=mock_meta_client,
            tenant_config=MagicMock(),
        )
        assert result["status"] == "sent"

    async def test_attempt_delivery_updates_existing_message(self, app_config, mock_repo, mock_meta_client):
        mock_repo.upsert_message.reset_mock()
        service = WhatsAppService(app_config, mock_repo)
        await service.attempt_delivery(
            message_id=uuid.uuid4(),
            phone_number_id="12345",
            access_token="tok",
            payload={"type": "text", "text": {"body": "Test"}},
            meta_client=mock_meta_client,
        )
        mock_repo.upsert_message.assert_not_called()
        mock_repo.update_message_status.assert_called()

    async def test_check_opt_out_keyword_match_it(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.check_opt_out("STOP!", "it")
        assert result["is_opt_out"] is True
        assert result["confidence"] == "high"

    async def test_check_opt_out_keyword_match_en(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.check_opt_out("unsubscribe please", "en")
        assert result["is_opt_out"] is True

    async def test_check_opt_out_normal_message(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.check_opt_out("Grazie, arrivederci!", "it")
        assert result["is_opt_out"] is False

    async def test_fast_path_greeting(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        bp = {"name": "Trattoria Da Mario"}
        result = await service.fast_path_match("Ciao", bp)
        assert result is not None
        assert "Trattoria Da Mario" in result

    async def test_fast_path_hours(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        bp = {"orari": "Lun-Sab 12:00-22:30"}
        result = await service.fast_path_match("Che orari fate?", bp)
        assert result is not None
        assert "Lun-Sab" in result

    async def test_fast_path_no_match(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        bp = {"name": "Test"}
        result = await service.fast_path_match("Quanto costa la pizza?", bp)
        assert result is None
