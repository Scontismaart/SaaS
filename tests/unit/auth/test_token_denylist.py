"""Unit tests per la token denylist, revoca server-side dei token di sessione,
scenario end-to-end (login -> copia token -> logout -> riuso bloccato),
e comportamento fail-closed in caso di Redis non raggiungibile.
"""

import base64
import json
import time
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from src.core.auth.denylist import (
    clear_memory_denylist,
    is_token_revoked,
    revoke_token,
    _estimate_ttl_from_jwt,
)
from src.core.auth.dependencies import get_current_user
import src.core.auth.dependencies as deps
import src.core.auth.bff as bff
from src.core.auth.routes import router as auth_router


@pytest.fixture(autouse=True)
def reset_denylist(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    clear_memory_denylist()
    yield
    clear_memory_denylist()


def _make_fake_jwt(user_id: str = "user-123", email: str = "test@example.com", exp_offset: int = 3600) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "email": email, "exp": now + exp_offset, "aal": "aal1"}
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{encoded_payload}.fake_signature"


class TestTokenDenylistFunctions:
    async def test_token_revocation_and_check(self):
        token = "test-token-xyz-123"
        assert not await is_token_revoked(token)

        await revoke_token(token, ttl_seconds=60)
        assert await is_token_revoked(token)

        # Token diverso non risulta revocato
        assert not await is_token_revoked("another-token")

    async def test_token_expiration_in_denylist(self):
        token = "short-lived-token"
        # Revoca con TTL 1 secondo
        await revoke_token(token, ttl_seconds=1)
        assert await is_token_revoked(token)

        # Simula il passare del tempo
        time.sleep(1.1)
        assert not await is_token_revoked(token)

    def test_estimate_ttl_from_jwt(self):
        now = int(time.time())
        fake_jwt = _make_fake_jwt(exp_offset=1200)
        ttl = _estimate_ttl_from_jwt(fake_jwt)
        assert 1100 <= ttl <= 1200


class TestGetCurrentUserWithRevokedToken:
    async def test_get_current_user_raises_401_on_revoked_token(self, monkeypatch):
        token = "revoked-jwt-token"
        await revoke_token(token)

        mock_request = MagicMock()
        mock_request.cookies = {}

        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=mock_request, token=token)
        assert exc.value.status_code == 401
        assert "revocata" in exc.value.detail.lower()


class TestLogoutAndRefreshRevocationEndToEnd:
    def test_logout_revokes_token(self, monkeypatch):
        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app)

        access_token = "valid-session-at-123"
        refresh_token = "valid-session-rt-456"

        monkeypatch.setattr("src.core.auth.bff.logout", AsyncMock(return_value=None))

        # Logout con cookie di sessione
        client.cookies.set(bff.access_cookie_name(), access_token)
        client.cookies.set(bff.refresh_cookie_name(), refresh_token)
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200

        import asyncio
        assert asyncio.run(is_token_revoked(access_token))
        assert asyncio.run(is_token_revoked(refresh_token))

    def test_refresh_rejects_revoked_token(self, monkeypatch):
        app = FastAPI()
        app.include_router(auth_router)
        client = TestClient(app)

        refresh_token = "stolen-or-revoked-rt"
        import asyncio
        asyncio.run(revoke_token(refresh_token))

        client.cookies.set(bff.refresh_cookie_name(), refresh_token)
        resp = client.post("/api/auth/refresh")
        assert resp.status_code == 401
        assert "scaduta" in resp.json()["detail"].lower()


class TestEndToEndLoginAccessLogoutReplayBlocked:
    """Scenario completo richiesto:
    1. Utente ottiene un JWT valido e accede a un endpoint protetto -> 200 OK
    2. Il token viene copiato/memorizzato
    3. L'utente esegue /logout (revocando il token server-side)
    4. Il token copiato viene riusato su endpoint protetto -> bloccato rigorosamente con 401.
    """

    def test_stolen_or_copied_token_rejected_after_logout(self, monkeypatch):
        app = FastAPI()
        app.include_router(auth_router)

        @app.get("/api/dashboard/secret-data")
        async def protected_endpoint(user: dict = Depends(get_current_user)):
            return {"ok": True, "user_id": user["auth_user_id"]}

        client = TestClient(app)

        # Genera token e mock decodifica JWT valida
        fake_token = _make_fake_jwt(user_id="usr-abc-999")

        async def _mock_verify(token: str):
            return {"sub": "usr-abc-999", "email": "test@example.com", "aal": "aal1"}

        monkeypatch.setattr(deps, "verify_supabase_jwt", _mock_verify)
        monkeypatch.setattr("src.core.auth.bff.logout", AsyncMock(return_value=None))

        # 1. Accesso legittimo con il token: restituisce 200 OK
        resp1 = client.get("/api/dashboard/secret-data", headers={"Authorization": f"Bearer {fake_token}"})
        assert resp1.status_code == 200
        assert resp1.json()["user_id"] == "usr-abc-999"

        # 2. Utente esegue il logout inviando il cookie di sessione
        client.cookies.set(bff.access_cookie_name(), fake_token)
        resp_logout = client.post("/api/auth/logout")
        assert resp_logout.status_code == 200

        # 3. L'attaccante riusa il token copiato via Bearer header
        resp_replay_header = client.get("/api/dashboard/secret-data", headers={"Authorization": f"Bearer {fake_token}"})
        assert resp_replay_header.status_code == 401
        assert "revocata" in resp_replay_header.json()["detail"].lower()

        # 4. L'attaccante riusa il token copiato via Cookie
        client.cookies.set(bff.access_cookie_name(), fake_token)
        resp_replay_cookie = client.get("/api/dashboard/secret-data")
        assert resp_replay_cookie.status_code == 401
        assert "revocata" in resp_replay_cookie.json()["detail"].lower()


class TestRedisFailClosedBehavior:
    """Verifica che quando RATE_LIMIT_BACKEND=redis e Redis è down,
    il sistema fallisca in modo esplicito (fail-closed) senza degradare
    silenziosamente in memoria isolata per container.
    """

    async def test_redis_down_revoke_raises_runtime_error(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://invalid-host-never-exists:6379/0")

        with pytest.raises(RuntimeError) as exc:
            await revoke_token("some-token")
        assert "non disponibile" in str(exc.value)

    async def test_redis_down_is_token_revoked_raises_503_fail_closed(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", "redis://invalid-host-never-exists:6379/0")

        with pytest.raises(HTTPException) as exc:
            await is_token_revoked("some-token")
        assert exc.value.status_code == 503
        assert "temporaneamente non disponibile" in exc.value.detail
