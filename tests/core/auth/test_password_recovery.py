"""Test recupero password: POST /api/auth/recover e /api/auth/reset.

Contratto:
- recover: risposta sempre 200 identica (no enumerazione account),
  validazione sintattica email, rate limit 5/ora/IP;
- reset: policy password identica alla registrazione (10 char + speciale);
  usa PUT /auth/v1/user con il token recovery come Bearer;
  token scaduto (Supabase 401) mappato su 401;
- mai dettagli interni Supabase al client.
"""

import httpx
import pytest
import respx

pytestmark = pytest.mark.asyncio

SUPABASE = "https://myproj.supabase.co"

_throttle_state: dict = {}


async def _noop_throttled(key, max_events, window_seconds):
    return _throttle_state.get(key, 0) >= max_events


async def _noop_record(key, window_seconds):
    _throttle_state[key] = _throttle_state.get(key, 0) + 1


@pytest.fixture(autouse=True)
def reset_throttle(monkeypatch):
    """Azzera i contatori throttle tra i test (backend in-memory)."""
    from src.core.auth import routes

    _throttle_state.clear()
    monkeypatch.setattr(routes.throttle, "is_throttled", _noop_throttled)
    monkeypatch.setattr(routes.throttle, "record_event", _noop_record)


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", "test-api-key-12345")
    monkeypatch.setenv("SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEMO_MODE", "false")


@pytest.fixture
async def client():
    from fastapi import FastAPI

    from src.core.auth.routes import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestRecover:
    async def test_recover_email_malformata_422(self, client, respx_mock):
        route = respx_mock.post(f"{SUPABASE}/auth/v1/recover").respond(200)
        r = await client.post("/api/auth/recover", json={"email": "non-email"})
        assert r.status_code == 422
        assert not route.called

    @respx.mock
    async def test_recover_sempre_200_anche_per_email_inesistente(self, client):
        # Anche se Supabase rispondesse con un errore, il client vede
        # sempre lo stesso esito: nessuna enumerazione account.
        respx.post(f"{SUPABASE}/auth/v1/recover").respond(400, json={"error": "user not found"})
        r = await client.post("/api/auth/recover", json={"email": "inesistente@test.com"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        # Messaggio neutro: non rivela se l'email esiste o no.
        assert "riceverai" in body["message"].lower()

    async def test_recover_rate_limit_5_ora_429(self, client, respx_mock):
        respx_mock.post(f"{SUPABASE}/auth/v1/recover").respond(200)
        for _ in range(5):
            r = await client.post(
                "/api/auth/recover",
                json={"email": "utente@test.com"},
                headers={"X-Forwarded-For": "9.9.9.9"},
            )
            assert r.status_code == 200
        r = await client.post(
            "/api/auth/recover",
            json={"email": "utente@test.com"},
            headers={"X-Forwarded-For": "9.9.9.9"},
        )
        assert r.status_code == 429

    @respx.mock
    async def test_recover_email_normalizzata(self, client):
        route = respx.post(f"{SUPABASE}/auth/v1/recover").respond(200)
        r = await client.post(
            "/api/auth/recover", json={"email": "  Utente@Test.COM "}
        )
        assert r.status_code == 200
        assert route.called
        assert route.calls[0].request.read() == (
            b'{"email":"utente@test.com"}'
        )


class TestReset:
    @respx.mock
    async def test_reset_token_valido_200_e_put_supabase(self, client):
        route = respx.put(f"{SUPABASE}/auth/v1/user").respond(
            200, json={"email": "owner@test.com"}
        )
        r = await client.post(
            "/api/auth/reset",
            json={"access_token": "recovery-token-123", "password": "Nuova-Passw0rd!"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert route.called
        req = route.calls[0].request
        assert req.headers["authorization"] == "Bearer recovery-token-123"
        assert req.headers["apikey"] == "anon-test-key"
        assert b'"password"' in req.read()

    async def test_reset_policy_password_corta_o_senza_speciale_422(
        self, client, respx_mock
    ):
        route = respx_mock.put(f"{SUPABASE}/auth/v1/user").respond(200)
        for pwd in ("corta!", "SoloLettere123"):
            r = await client.post(
                "/api/auth/reset", json={"access_token": "tok", "password": pwd}
            )
            assert r.status_code == 422
        assert not route.called

    @respx.mock
    async def test_reset_token_scaduto_mappato_401(self, client):
        respx.put(f"{SUPABASE}/auth/v1/user").respond(401, json={"msg": "expired"})
        r = await client.post(
            "/api/auth/reset",
            json={"access_token": "expired-token", "password": "Nuova-Passw0rd!"},
        )
        assert r.status_code == 401
