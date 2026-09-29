"""Policy registrazione senza dipendenze DB: validazione password lato
endpoint (422 prima di ogni chiamata esterna) e throttle signup distribuito.
"""

import uuid

import httpx
import pytest
from fastapi import HTTPException

from src.core.auth.register import (
    _EMAIL_RE,
    _SPECIAL_RE,
    PASSWORD_MIN,
    _check_signup_throttle,
)
from src.core.rate_limit import reset_memory_rate_limiter

def test_email_regex_accepts_valid():
    assert _EMAIL_RE.match("titolare@attivita.it")
    assert _EMAIL_RE.match("a.b+tag@sub.domain.com")


def test_email_regex_rejects_invalid():
    assert not _EMAIL_RE.match("no-at-sign")
    assert not _EMAIL_RE.match("a@b")
    assert not _EMAIL_RE.match("a b@c.it")


def test_password_policy_constants():
    # Policy robusta: lunghezza minima 10 + almeno un carattere speciale
    assert PASSWORD_MIN >= 10
    assert _SPECIAL_RE.search("abcde!fghi")
    assert not _SPECIAL_RE.search("abcdefghij")


@pytest.mark.asyncio
async def test_signup_throttle_blocks_after_max():
    from src.core.auth import throttle

    reset_memory_rate_limiter()
    ip = f"10.0.0.{uuid.uuid4().int % 250 + 1}"
    key = f"auth:signup:{ip}"
    for _ in range(5):
        await throttle.record_event(key, 60 * 60)
    with pytest.raises(HTTPException) as exc:
        await _check_signup_throttle(ip)
    assert exc.value.status_code == 429


@pytest.fixture
async def register_client():
    from fastapi import FastAPI

    from src.core.auth.register import router as register_router

    app = FastAPI()
    app.include_router(register_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_register_rejects_short_password(register_client):
    resp = await register_client.post(
        "/api/auth/register",
        json={"email": "a@b.it", "password": "Ab1!x", "nome_attivita": "T"},
    )
    assert resp.status_code == 422
    assert "10 caratteri" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_rejects_password_without_special_char(register_client):
    resp = await register_client.post(
        "/api/auth/register",
        json={"email": "a@b.it", "password": "Abcdefghij", "nome_attivita": "T"},
    )
    assert resp.status_code == 422
    assert "speciale" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_register_accepts_policy_compliant_password_shape(
    register_client, monkeypatch
):
    """Password conforme supera la validazione locale (il flusso poi
    continua verso Supabase, mockato qui): il 422 di policy non scatta."""
    from src.core.auth import register as reg

    async def fake_signup(email, password):
        return {"user": {"id": "u1"}}

    class FakeRepo:
        async def create_organization_with_owner(self, *a, **k):
            return {"organization_id": str(uuid.uuid4())}

    monkeypatch.setattr(reg, "supabase_signup", fake_signup)
    monkeypatch.setattr(reg, "get_repo", lambda request: FakeRepo())

    resp = await register_client.post(
        "/api/auth/register",
        json={
            "email": f"u{uuid.uuid4().hex[:6]}@test.com",
            "password": "Passw0rd! Lunga",
            "nome_attivita": "Trattoria",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
