import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock
from fastapi import HTTPException
import pytest

from src.core.channels.inbound.meta_security import MetaWebhookSecurity


def test_verify_challenge_success():
    sec = MetaWebhookSecurity(verify_token="my_token")
    resp = sec.verify_challenge("subscribe", "my_token", "challenge_12345")
    assert resp.status_code == 200
    assert resp.body.decode() == "challenge_12345"


def test_verify_challenge_mismatch():
    sec = MetaWebhookSecurity(verify_token="my_token")
    with pytest.raises(HTTPException) as exc_info:
        sec.verify_challenge("subscribe", "wrong_token", "challenge_12345")
    assert exc_info.value.status_code == 403


def test_verify_challenge_wrong_mode():
    sec = MetaWebhookSecurity(verify_token="my_token")
    with pytest.raises(HTTPException) as exc_info:
        sec.verify_challenge("unsubscribe", "my_token", "challenge_12345")
    assert exc_info.value.status_code == 403


def test_verify_timestamp_within_tolerance():
    sec = MetaWebhookSecurity(timestamp_tolerance=300)
    req = MagicMock()
    req.headers = {"X-Timestamp": str(int(time.time()))}
    # Non deve sollevare eccezioni
    sec.verify_timestamp(req)


def test_verify_timestamp_out_of_tolerance():
    sec = MetaWebhookSecurity(timestamp_tolerance=300)
    req = MagicMock()
    req.headers = {"X-Timestamp": str(int(time.time()) - 600)}
    with pytest.raises(HTTPException) as exc:
        sec.verify_timestamp(req)
    assert exc.value.status_code == 403
    assert "Timestamp out of tolerance" in exc.value.detail


def test_verify_timestamp_invalid_format():
    sec = MetaWebhookSecurity()
    req = MagicMock()
    req.headers = {"X-Timestamp": "not-a-timestamp"}
    with pytest.raises(HTTPException) as exc:
        sec.verify_timestamp(req)
    assert exc.value.status_code == 400
    assert "Invalid X-Timestamp" in exc.value.detail


def test_verify_hmac_valid_and_invalid():
    secret = "meta_test_secret_123"
    body = b'{"object": "whatsapp_business_account"}'
    valid_sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    sec = MetaWebhookSecurity(app_secret=secret)
    assert sec.verify_hmac(body, valid_sig) is True
    assert sec.verify_hmac(body, "sha256=invalid_hash") is False
    assert sec.verify_hmac(body, "") is False


@pytest.mark.asyncio
async def test_read_limited_body_oversize():
    sec = MetaWebhookSecurity(max_body_size=10)
    req = MagicMock()
    req.headers = {"content-length": "15"}
    with pytest.raises(HTTPException) as exc:
        await sec.read_limited_body(req)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_authenticate_and_read_success():
    secret = "super_secret"
    body = b'{"entry": []}'
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    sec = MetaWebhookSecurity(app_secret=secret)
    req = MagicMock()
    req.headers = {
        "X-Hub-Signature-256": sig,
        "content-length": str(len(body)),
    }

    async def fake_stream():
        yield body

    req.stream = fake_stream

    result = await sec.authenticate_and_read(req)
    assert result == body
