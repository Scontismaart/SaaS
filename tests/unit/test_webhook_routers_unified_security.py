import ast
import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.whatsapp.config import AppConfig
from src.whatsapp.router import create_router as create_whatsapp_router, _read_limited_body, _verify_hmac
from src.instagram.router import create_router as create_instagram_router


@pytest.fixture
def test_config():
    return AppConfig(
        app_secret="test_secret_meta_123",
        verify_token="test_verify_token_xyz",
        postgres_dsn="",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
    )


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_no_cross_import_between_instagram_and_whatsapp():
    """Verifica tramite AST che instagram/router.py non importi da whatsapp.router."""
    with open("src/instagram/router.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="src/instagram/router.py")

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "src.whatsapp.router", (
                "Accoppiamento anomalo rilevato: src/instagram/router.py importa da src.whatsapp.router"
            )


def test_whatsapp_shims_backwards_compatibility():
    """Verifica che gli shim _read_limited_body e _verify_hmac continuino a funzionare delegando."""
    body = b"hello world"
    secret = "my_secret"
    sig = _sign(body, secret)
    assert _verify_hmac(body, sig, secret) is True
    assert _verify_hmac(body, "sha256=wrong", secret) is False


def test_whatsapp_router_verify_challenge(test_config):
    app = FastAPI()
    router = create_whatsapp_router(test_config, repo=MagicMock())
    app.include_router(router)
    client = TestClient(app)

    # Success
    resp = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token_xyz",
            "hub.challenge": "wh_challenge_123",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "wh_challenge_123"

    # Token mismatch -> 403
    resp_bad = client.get(
        "/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "wh_challenge_123",
        },
    )
    assert resp_bad.status_code == 403


def test_whatsapp_router_hmac_and_replay_security(test_config):
    app = FastAPI()
    mock_repo = MagicMock()
    mock_repo.get_org_by_phone_number_id = AsyncMock(return_value=None)
    router = create_whatsapp_router(test_config, repo=mock_repo)
    app.include_router(router)
    client = TestClient(app)

    body = b'{"object": "whatsapp_business_account", "entry": []}'
    valid_sig = _sign(body, test_config.app_secret)

    # 1. Valid signature
    resp = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # 2. Invalid signature -> 403
    resp_bad = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=invalid", "Content-Type": "application/json"},
    )
    assert resp_bad.status_code == 403

    # 3. Replay attack timestamp out of tolerance -> 403
    stale_ts = str(int(time.time()) - 1000)
    resp_replay = client.post(
        "/webhooks/whatsapp",
        content=body,
        headers={
            "X-Hub-Signature-256": valid_sig,
            "X-Timestamp": stale_ts,
            "Content-Type": "application/json",
        },
    )
    assert resp_replay.status_code == 403


def test_instagram_router_verify_challenge(test_config):
    app = FastAPI()
    router = create_instagram_router(test_config, wrepo=MagicMock(), igrepo=MagicMock())
    app.include_router(router)
    client = TestClient(app)

    # Success
    resp = client.get(
        "/webhooks/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "test_verify_token_xyz",
            "hub.challenge": "ig_challenge_999",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "ig_challenge_999"

    # Token mismatch -> 403
    resp_bad = client.get(
        "/webhooks/instagram",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "ig_challenge_999",
        },
    )
    assert resp_bad.status_code == 403


def test_instagram_router_hmac_and_replay_security(test_config):
    app = FastAPI()
    router = create_instagram_router(test_config, wrepo=MagicMock(), igrepo=MagicMock())
    app.include_router(router)
    client = TestClient(app)

    body = b'{"object": "instagram", "entry": []}'
    valid_sig = _sign(body, test_config.app_secret)

    # 1. Valid signature
    resp = client.post(
        "/webhooks/instagram",
        content=body,
        headers={"X-Hub-Signature-256": valid_sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    # 2. Invalid signature -> 403
    resp_bad = client.post(
        "/webhooks/instagram",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=invalid", "Content-Type": "application/json"},
    )
    assert resp_bad.status_code == 403

    # 3. Replay attack timestamp out of tolerance -> 403
    stale_ts = str(int(time.time()) - 1000)
    resp_replay = client.post(
        "/webhooks/instagram",
        content=body,
        headers={
            "X-Hub-Signature-256": valid_sig,
            "X-Timestamp": stale_ts,
            "Content-Type": "application/json",
        },
    )
    assert resp_replay.status_code == 403
