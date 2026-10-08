"""Test sicurezza account: cambio password ed email (proxy Supabase).

Contratto:
- richiedono cookie di sessione (401 senza);
- policy password identica alla registrazione (10 char + speciale);
- email validata sintatticamente; con "Confirm email" attivo Supabase
  compila new_email → il BFF espone conferma_richiesta=True;
- rate limit 5/ora per IP su entrambi gli endpoint;
- errori Supabase mappati generici (mai dettagli interni al client).
"""

import httpx
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

pytestmark = pytest.mark.asyncio

_throttle_state: dict = {}


async def _noop_throttled(key, max_events, window_seconds):
    return _throttle_state.get(key, 0) >= max_events


async def _noop_record(key, window_seconds):
    _throttle_state[key] = _throttle_state.get(key, 0) + 1


@pytest.fixture(autouse=True)
def reset_throttle(monkeypatch):
    """Il backend in-memory del throttle è per-processo: azzera i contatori
    tra i test così l'ordine di esecuzione non influenza i risultati."""
    from src.core.auth import routes

    _throttle_state.clear()
    monkeypatch.setattr(routes.throttle, "is_throttled", _noop_throttled)
    monkeypatch.setattr(routes.throttle, "record_event", _noop_record)


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", "test-api-key-12345")
    monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEMO_MODE", "false")


@pytest.fixture
async def client(monkeypatch):
    from fastapi import FastAPI

    from src.core.auth.routes import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)
    app.state.repo = SimpleNamespace(get_auth_access_allowed=AsyncMock(return_value=True))

    async def verify(_token, **_kwargs):
        return {"sub": "test-auth-user", "email": "owner@test.com"}

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def fake_update_user(monkeypatch):
    calls = []
    _throttle_state.clear()

    async def _fake(token, payload):
        calls.append((token, payload))
        user = {"email": "owner@test.com", **payload}
        if "email" in payload:
            # Supabase con conferma email attiva: compila new_email
            user = {"email": "owner@test.com", "new_email": payload["email"]}
        return user

    from src.core.auth import routes

    async def _fake_get_user(token):
        return {"email": "owner@test.com", "id": "test-auth-user"}

    async def _fake_login(email, password):
        if password == "Password-Sbagliata!":
            raise ValueError("Credenziali errate")
        return {"access_token": "token-ok"}

    monkeypatch.setattr(routes, "_supabase_update_user", _fake)
    monkeypatch.setattr(routes, "_supabase_get_user", _fake_get_user)
    monkeypatch.setattr(routes.bff, "login", _fake_login)
    return calls


COOKIE = {"Cookie": "wa_at=valid-session-token"}


class TestCambioPassword:
    async def test_disabled_account_cannot_change_password(self, client, fake_update_user):
        client._transport.app.state.repo.get_auth_access_allowed.return_value = False
        response = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert response.status_code == 403
        assert fake_update_user == []

    async def test_ok(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert fake_update_user[0][1] == {"password": "Nuova-Passw0rd!"}
        assert fake_update_user[0][0] == "valid-session-token"

    async def test_current_password_mancante_422(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 422
        assert not fake_update_user

    async def test_401_senza_sessione(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
        )
        assert r.status_code == 401
        assert not fake_update_user

    async def test_password_corta_422(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/password",
            json={"password": "corta!", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 422
        assert not fake_update_user

    async def test_password_senza_speciale_422(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/password",
            json={"password": "SoloLettere123", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 422
        assert not fake_update_user

    async def test_rate_limit_5_ora(self, client, fake_update_user):
        for _ in range(5):
            r = await client.post(
                "/api/auth/password",
                json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
                headers={"Cookie": "wa_at=valid-session-token", "X-Forwarded-For": "1.2.3.4"},
            )
            assert r.status_code == 200
        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
            headers={"Cookie": "wa_at=valid-session-token", "X-Forwarded-For": "1.2.3.4"},
        )
        assert r.status_code == 429


class TestCambioEmail:
    async def test_disabled_account_cannot_change_email(self, client, fake_update_user):
        client._transport.app.state.repo.get_auth_access_allowed.return_value = False
        response = await client.post(
            "/api/auth/email", json={"email": "nuova@test.com"}, headers=COOKIE
        )
        assert response.status_code == 403
        assert fake_update_user == []

    async def test_ok_con_conferma_richiesta(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/email",
            json={"email": "nuova@test.com"},
            headers=COOKIE,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["conferma_richiesta"] is True
        assert fake_update_user[0][1] == {"email": "nuova@test.com"}

    async def test_email_non_valida_422(self, client, fake_update_user):
        r = await client.post("/api/auth/email", json={"email": "non-email"}, headers=COOKIE)
        assert r.status_code == 422
        assert not fake_update_user

    async def test_401_senza_sessione(self, client, fake_update_user):
        r = await client.post("/api/auth/email", json={"email": "nuova@test.com"})
        assert r.status_code == 401

    async def test_email_normalizzata_minuscolo(self, client, fake_update_user):
        r = await client.post(
            "/api/auth/email", json={"email": "  Nuova@Test.COM "}, headers=COOKIE
        )
        assert r.status_code == 200
        assert fake_update_user[0][1] == {"email": "nuova@test.com"}


class TestErroriSupabase:
    async def test_sessione_scaduta_mappata_401(self, client, monkeypatch):
        from fastapi import HTTPException

        from src.core.auth import routes

        async def expired(token, payload):
            raise HTTPException(401, "Sessione scaduta: effettua di nuovo il login")

        monkeypatch.setattr(routes, "_supabase_update_user", expired)

        async def _fake_user(token):
            return {"email": "owner@test.com", "id": "test-auth-user"}

        async def _fake_login(email, password):
            return {"access_token": "token-ok"}

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_user)
        monkeypatch.setattr(routes.bff, "login", _fake_login)

        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 401

    async def test_supabase_giu_mappata_502(self, client, monkeypatch):
        from fastapi import HTTPException

        from src.core.auth import routes

        async def down(token, payload):
            raise HTTPException(502, "Servizio autenticazione non raggiungibile")

        monkeypatch.setattr(routes, "_supabase_update_user", down)

        async def _fake_user(token):
            return {"email": "owner@test.com", "id": "test-auth-user"}

        async def _fake_login(email, password):
            return {"access_token": "token-ok"}

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_user)
        monkeypatch.setattr(routes.bff, "login", _fake_login)

        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 502


class TestVerificaPasswordAttuale:
    async def test_con_password_attuale_corretta(self, client, fake_update_user, monkeypatch):
        from src.core.auth import routes

        async def _fake_user(token):
            return {"email": "owner@test.com", "id": "auth-user-123"}

        async def _fake_login(email, password):
            if password != "Vecchia-Passw0rd!":
                raise ValueError("Credenziali errate")
            return {"access_token": "token-ok"}

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_user)
        monkeypatch.setattr(routes.bff, "login", _fake_login)

        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Vecchia-Passw0rd!"},
            headers=COOKIE,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    async def test_con_password_attuale_errata_403(self, client, fake_update_user, monkeypatch):
        from src.core.auth import routes

        async def _fake_user(token):
            return {"email": "owner@test.com", "id": "auth-user-123"}

        async def _fake_login(email, password):
            raise ValueError("Credenziali errate")

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_user)
        monkeypatch.setattr(routes.bff, "login", _fake_login)

        r = await client.post(
            "/api/auth/password",
            json={"password": "Nuova-Passw0rd!", "current_password": "Password-Sbagliata!"},
            headers=COOKIE,
        )
        assert r.status_code == 403
        assert "non è corretta" in r.json()["detail"]


class TestSendPasswordReset:
    async def test_send_reset_ok(self, client, monkeypatch):
        from src.core.auth import routes

        async def _fake_user(token):
            return {"email": "marco.rossi@example.com"}

        class FakeClient:
            async def post(self, *args, **kwargs):
                return httpx.Response(200, request=httpx.Request("POST", "http://test"))

        async def _fake_client():
            return FakeClient()

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_user)
        monkeypatch.setattr(routes.bff, "_client", _fake_client)

        r = await client.post("/api/auth/send-password-reset", headers=COOKIE)
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["email_masked"] == "ma•••@example.com"
        assert "link" in data["message"].lower()

    async def test_send_reset_401_senza_sessione(self, client):
        r = await client.post("/api/auth/send-password-reset")
        assert r.status_code == 401

    async def test_send_reset_supabase_429(self, client, monkeypatch):
        from src.core.auth import routes

        async def _fake_user(token):
            return {"email": "marco.rossi@example.com"}

        class FakeClient:
            async def post(self, *args, **kwargs):
                return httpx.Response(429, request=httpx.Request("POST", "http://test"))

        async def _fake_client():
            return FakeClient()

        monkeypatch.setattr(routes, "_supabase_get_user", _fake_user)
        monkeypatch.setattr(routes.bff, "_client", _fake_client)

        r = await client.post("/api/auth/send-password-reset", headers=COOKIE)
        assert r.status_code == 429
