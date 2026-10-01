"""Signup validation, browser-supplied password rejection, and throttling."""

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from src.core.auth.register import (
    _EMAIL_RE,
    _SPECIAL_RE,
    PASSWORD_MIN,
    _check_signup_throttle,
    _valid_password,
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
    assert _valid_password("Strong-pass-2026!")
    assert not _valid_password("lowercase-2026!")
    assert not _valid_password("Uppercase-only!")
    assert not _valid_password("Uppercase-Only!")


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
async def test_register_accepts_password_only_for_encrypted_bff_capsule(register_client, monkeypatch):
    from src.core.auth import bff
    from src.core.auth import register as reg

    captured = {}

    async def fake_signup(email, password, redirect_to, challenge, business_name):
        captured.update(password=password, challenge=challenge)

    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:4174")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setattr(reg, "supabase_signup", fake_signup)
    monkeypatch.setattr(reg.throttle, "is_throttled", AsyncMock(return_value=False))
    monkeypatch.setattr(reg.throttle, "record_event", AsyncMock())
    resp = await register_client.post(
        "/api/auth/register",
        json={"email": "a@example.test", "password": "Synthetic-pass-2026!", "nome_attivita": "T"},
        headers={"Origin": "http://localhost:4174"},
    )
    assert resp.status_code == 202
    assert "Synthetic-pass-2026!" not in resp.text
    assert captured["password"] != "Synthetic-pass-2026!"
    verifier = register_client.cookies.get("wa_signup_verifier")
    assert captured["challenge"] == bff.pkce_challenge(verifier)


@pytest.mark.asyncio
async def test_register_generates_temporary_password_and_pkce(
    register_client, monkeypatch
):
    """Signup sends only backend-generated credentials and browser-bound PKCE."""
    from src.core.auth import bff
    from src.core.auth import register as reg

    captured = {}

    async def fake_signup(email, password, redirect_to, challenge, business_name):
        captured.update(
            email=email,
            password=password,
            redirect_to=redirect_to,
            challenge=challenge,
            business_name=business_name,
        )

    monkeypatch.setattr(reg, "supabase_signup", fake_signup)
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:4174")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setattr(reg.throttle, "is_throttled", lambda *args: _async_value(False))
    monkeypatch.setattr(reg.throttle, "record_event", lambda *args: _async_value(None))

    resp = await register_client.post(
        "/api/auth/register",
        json={
            "email": "new@example.test",
            "nome_attivita": "Trattoria",
            "password": "Trattoria-pass-2026!",
        },
        headers={"Origin": "http://localhost:4174"},
    )
    assert resp.status_code == 202
    assert resp.json()["ok"] is True
    assert captured["email"] == "new@example.test"
    assert len(captured["password"]) >= 43
    assert reg._SPECIAL_RE.search(captured["password"])
    assert captured["password"] not in resp.text
    assert captured["redirect_to"] == "http://localhost:4174/api/auth/signup/callback"
    assert captured["business_name"] == "Trattoria"
    assert captured["password"] != "Trattoria-pass-2026!"
    verifier = register_client.cookies.get("wa_signup_verifier")
    assert verifier
    assert captured["challenge"] == bff.pkce_challenge(verifier)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "password",
    [None, "", "short", "lowercase-only-2026!", "Uppercase-only!", "Uppercase-Only!"],
)
async def test_invalid_signup_password_is_rejected_before_supabase_signup(
    register_client, monkeypatch, password
):
    from src.core.auth import register as reg

    signup = AsyncMock()
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:4174")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setattr(reg, "supabase_signup", signup)
    monkeypatch.setattr(reg.throttle, "is_throttled", AsyncMock(return_value=False))
    monkeypatch.setattr(reg.throttle, "record_event", AsyncMock())
    body = {"email": "new@example.test", "nome_attivita": "Studio"}
    if password is not None:
        body["password"] = password

    response = await register_client.post(
        "/api/auth/register",
        json=body,
        headers={"Origin": "http://localhost:4174"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Password non valida"}
    signup.assert_not_awaited()


@pytest.mark.asyncio
async def test_signup_rejects_nonmatching_origin_before_supabase_signup(register_client, monkeypatch):
    from src.core.auth import register as reg

    signup = AsyncMock()
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:4174")
    monkeypatch.setattr(reg, "supabase_signup", signup)
    response = await register_client.post(
        "/api/auth/register",
        json={
            "email": "new@example.test",
            "nome_attivita": "Studio",
            "password": "Strong-pass-2026!",
        },
        headers={"Origin": "https://attacker.test"},
    )

    assert response.status_code == 403
    signup.assert_not_awaited()


async def _async_value(value):
    return value
