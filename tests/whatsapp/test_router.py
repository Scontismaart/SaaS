import hashlib
import hmac
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from src.whatsapp.router import create_router
from src.whatsapp.config import AppConfig


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test_app_secret",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="my_verify_token",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_org_by_phone_number_id = AsyncMock(return_value={
        "organization_id": uuid.uuid4(),
        "phone_number_id": "1234567890",
        "waba_id": "waba_1",
        "access_token": "encrypted_token",
        "name": "Test Org",
        "business_profile": {},
    })
    repo.get_org_by_waba_id = AsyncMock(return_value={
        "organization_id": uuid.uuid4(),
        "name": "Test Org",
    })
    repo.update_message_status = AsyncMock(return_value={"status": "delivered"})
    repo.upsert_message = AsyncMock(return_value={"id": uuid.uuid4(), "status": "received_pending_ai"})
    return repo


@pytest.fixture
def app(app_config, mock_repo):
    app = FastAPI()
    router = create_router(app_config, mock_repo)
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _sign_body(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestRouter:
    def test_get_verify_success(self, client):
        resp = client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=my_verify_token&hub.challenge=123456789")
        assert resp.status_code == 200
        assert resp.text == "123456789"

    def test_get_verify_fail(self, client):
        resp = client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=123456789")
        assert resp.status_code == 403

    def test_post_status_update(self, client, app_config):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "391234567890",
                            "phone_number_id": "1234567890",
                        },
                        "statuses": [{
                            "id": "wamid.test",
                            "status": "delivered",
                            "timestamp": "1712345678",
                            "recipient_id": "391234567890",
                        }],
                    },
                }],
            }],
        }
        body = json.dumps(payload).encode()
        sig = _sign_body(body, app_config.app_secret)
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200

    def test_post_status_update_bad_signature(self, client, app_config):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{"field": "messages", "value": {"metadata": {"phone_number_id": "1234567890"}, "statuses": [{"id": "wamid.test", "status": "delivered", "timestamp": "1712345678", "recipient_id": "391234567890"}]}}],
            }],
        }
        body = json.dumps(payload).encode()
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid",
            },
        )
        assert resp.status_code == 403

    def test_post_inbound_message(self, client, app_config):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "391234567890",
                            "phone_number_id": "1234567890",
                        },
                        "contacts": [{
                            "profile": {"name": "Mario"},
                            "wa_id": "391234567890",
                        }],
                        "messages": [{
                            "from": "391234567890",
                            "id": "wamid.inbound.test",
                            "timestamp": "1712345678",
                            "type": "text",
                            "text": {"body": "Ciao"},
                        }],
                    },
                }],
            }],
        }
        body = json.dumps(payload).encode()
        sig = _sign_body(body, app_config.app_secret)
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200

    def test_post_template_status(self, client, app_config):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "field": "message_template_status_update",
                    "value": {
                        "messaging_product": "whatsapp",
                        "message_template_id": 12345,
                        "message_template_name": "promo_welcome",
                        "message_template_language": "it",
                        "message_template_status": "APPROVED",
                        "event": "UPDATE",
                    },
                }],
            }],
        }
        body = json.dumps(payload).encode()
        sig = _sign_body(body, app_config.app_secret)
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
