import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import respx
import httpx
from src.whatsapp.templates import TemplateSyncer
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
    repo.get_tenant_config = AsyncMock(return_value={
        "access_token": "encrypted_token",
        "phone_number_id": "12345",
        "waba_id": "waba_1",
        "business_profile": {},
    })
    repo.upsert_template = AsyncMock(return_value={"id": uuid.uuid4()})
    repo.update_template_status = AsyncMock(return_value={"id": uuid.uuid4()})
    return repo


class TestTemplateSyncer:
    @respx.mock
    async def test_pull_sync(self, app_config, mock_repo):
        waba_id = "waba_1"
        url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
        respx.get(url).respond(
            200,
            json={
                "data": [
                    {
                        "id": "123",
                        "name": "promo_welcome",
                        "language": "it",
                        "category": "MARKETING",
                        "status": "APPROVED",
                        "components": [{"type": "BODY", "text": "Ciao {{1}}!"}],
                    }
                ],
            },
        )
        syncer = TemplateSyncer(app_config, mock_repo)
        syncer._get_access_token = AsyncMock(return_value="test_token")
        await syncer.pull_sync("waba_1", "org-uuid")
        mock_repo.upsert_template.assert_called_once()

    async def test_process_push_update(self, app_config, mock_repo):
        syncer = TemplateSyncer(app_config, mock_repo)
        org_id = uuid.uuid4()
        await syncer.process_push_update({
            "message_template_name": "promo_welcome",
            "message_template_language": "it",
            "message_template_status": "REJECTED",
            "reason": "INVALID_FORMAT",
        }, org_id)
        mock_repo.update_template_status.assert_called_once()
        args = mock_repo.update_template_status.call_args[1]
        assert args["organization_id"] == org_id
        assert args["status"] == "REJECTED"
        assert args["rejected_reason"] == "INVALID_FORMAT"
