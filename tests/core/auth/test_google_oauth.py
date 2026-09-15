"""Test login Google OAuth PKCE server-side (/api/auth/google/*).

Contratto:
- start: 302 verso authorize Supabase con challenge S256 + cookie HttpOnly
  temporanei (verifier, next). Nessuno `state` custom nell'URL: lo genera
  Supabase internamente (passarne uno rompe il flusso con bad_oauth_state).
- callback: happy path scambia il codice col verifier del cookie e imposta
  i cookie di sessione BFF; lo `state` di ritorno è opaco (uuid Supabase) e
  non viene confrontato. Qualsiasi anomalia (cookie assenti, errore OAuth,
  scambio fallito, provisioning fallito) fa fail-closed con redirect a
  /accedi/?errore=google senza cookie di sessione.
- primo accesso Google: se l'utente non ha membership viene creata org +
  owner con trial (JIT provisioning); idempotente ai login successivi.
- `next` non è mai aperto a domini esterni (open redirect).
"""

import base64
import hashlib

import httpx
import pytest

import src.core.auth.bff as bff_module

API_KEY = "test-api-key-12345"

pytestmark = pytest.mark.asyncio


class FakeRepo:
    """Stub di Repository per il callback: registra le chiamate."""

    def __init__(self, memberships=None):
        self.memberships = memberships or []
        self.create_calls = []

    async def get_memberships_by_auth(self, auth_user_id):
        return self.memberships

    async def get_or_create_organization_with_owner(
        self, auth_user_id, nome_attivita, trial_days
    ):
        self.create_calls.append((auth_user_id, nome_attivita, trial_days))
        return {"organization_id": "org-1"}


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", API_KEY)
    monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.test")


@pytest.fixture
async def oauth_client():
    """Client con solo il router /api/auth e un FakeRepo su app.state."""
    from fastapi import FastAPI

    from src.core.auth.routes import router as auth_router

    app = FastAPI()
    app.include_router(auth_router)
    app.state.repo = FakeRepo()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _get_repo(app) -> FakeRepo:
    return app.state.repo


def _fake_token_response(access="at.oauth", refresh="rt.oauth", metadata=None):
    return {
        "access_token": access,
        "refresh_token": refresh,
        "expires_in": 3600,
        "token_type": "bearer",
        "user": {
            "id": "u1",
            "email": "owner@test.com",
            "user_metadata": metadata or {},
        },
    }


def _cookie_header(resp) -> str:
    parts = [f"{k}={v}" for k, v in resp.cookies.items()]
    return "; ".join(parts)


class TestGoogleStart:
    async def test_start_redirects_to_supabase_authorize(self, oauth_client):
        resp = await oauth_client.get("/api/auth/google/start")
        assert resp.status_code == 302
        loc = resp.headers["location"]
        assert loc.startswith("https://myproj.supabase.co/auth/v1/authorize?")
        assert "provider=google" in loc
        assert "redirect_to=https%3A%2F%2Fapp.test%2Fapi%2Fauth%2Fgoogle%2Fcallback" in loc
        assert "code_challenge_method=S256" in loc
        assert "code_challenge=" in loc
        # Lo state è generato da Supabase: un custom nell'URL rompe il flusso
        assert "state=" not in loc

    async def test_start_sets_httponly_cookies_with_verifier_matching_challenge(
        self, oauth_client
    ):
        resp = await oauth_client.get("/api/auth/google/start")
        assert "wa_oauth_verifier" in resp.cookies
        assert "wa_oauth_next" in resp.cookies
        verifier = resp.cookies["wa_oauth_verifier"]
        # La challenge nell'URL deve corrispondere al verifier nel cookie (S256)
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert f"code_challenge={expected}" in resp.headers["location"]
        # HttpOnly: il JS non legge mai il verifier
        for c in resp.headers.get_list("set-cookie"):
            if c.startswith("wa_oauth_"):
                assert "httponly" in c.lower()

    async def test_start_next_path_preserved(self, oauth_client):
        resp = await oauth_client.get("/api/auth/google/start?next=/app/")
        assert resp.cookies["wa_oauth_next"].strip('"') == "/app/"

    async def test_start_open_redirect_blocked(self, oauth_client):
        resp = await oauth_client.get(
            "/api/auth/google/start", params={"next": "//evil.com"}
        )
        assert resp.cookies["wa_oauth_next"].strip('"') == "/app/"

    async def test_start_without_public_app_url_500(self, oauth_client, monkeypatch):
        monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
        resp = await oauth_client.get("/api/auth/google/start")
        assert resp.status_code == 500


class TestGoogleCallback:
    async def _do_start(self, oauth_client, next_path=None):
        url = "/api/auth/google/start"
        if next_path:
            url += f"?next={next_path}"
        return await oauth_client.get(url)

    async def test_callback_happy_path_sets_session_cookies(
        self, oauth_client, monkeypatch
    ):
        exchanged = []

        async def fake_exchange(code, verifier):
            exchanged.append((code, verifier))
            return _fake_token_response()

        monkeypatch.setattr(bff_module, "exchange_pkce", fake_exchange)

        start = await self._do_start(oauth_client)

        # Lo state di ritorno è l'uuid interno Supabase: opaco, non confrontato
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "the-code", "state": "9c98eab7-9df1-4ce9-8b15-90d50a712cb8"},
            headers={"Cookie": _cookie_header(start)},
        )
        assert resp.status_code == 302
        # BFF callbacks and frontend are same-origin; keep redirects local.
        assert resp.headers["location"] == "/app/"
        # Il codice è stato scambiato col verifier del cookie
        assert exchanged[0][0] == "the-code"
        assert exchanged[0][1] == start.cookies["wa_oauth_verifier"]
        # Cookie di sessione BFF impostati, token MAI nel body
        set_cookies = resp.headers.get_list("set-cookie")
        assert any(c.startswith("wa_at=") for c in set_cookies)
        assert any(c.startswith("wa_rt=") for c in set_cookies)
        assert any(c.startswith("wa_csrf=") for c in set_cookies)
        # I cookie temporanei OAuth vengono consumati (Max-Age=0)
        assert any(c.startswith("wa_oauth_verifier=") and "Max-Age=0" in c for c in set_cookies)
        assert any(c.startswith("wa_oauth_next=") and "Max-Age=0" in c for c in set_cookies)

    async def test_callback_honors_safe_next_cookie(self, oauth_client, monkeypatch):
        async def fake_exchange(code, verifier):
            return _fake_token_response()

        monkeypatch.setattr(bff_module, "exchange_pkce", fake_exchange)

        start = await self._do_start(oauth_client, next_path="/app/?view=inbox")
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": "opaque-supabase-uuid"},
            headers={"Cookie": _cookie_header(start)},
        )
        assert resp.headers["location"] == "/app/?view=inbox"

    async def test_callback_without_state_still_exchanges(self, oauth_client, monkeypatch):
        called = []

        async def fake_exchange(code, verifier):
            called.append(1)
            return _fake_token_response()

        monkeypatch.setattr(bff_module, "exchange_pkce", fake_exchange)

        start = await self._do_start(oauth_client)
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "c"},
            headers={"Cookie": _cookie_header(start)},
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/app/"
        assert called

    async def test_callback_missing_code_fails_closed(self, oauth_client):
        start = await self._do_start(oauth_client)
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"state": "whatever"},
            headers={"Cookie": _cookie_header(start)},
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/accedi/?errore=google"

    async def test_callback_missing_cookies_fails_closed(self, oauth_client):
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": "whatever"},
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/accedi/?errore=google"

    async def test_callback_provider_error_fails_closed(self, oauth_client):
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"error": "access_denied", "error_description": "nope"},
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/accedi/?errore=google"

    async def test_callback_exchange_failure_fails_closed(
        self, oauth_client, monkeypatch
    ):
        from fastapi import HTTPException

        async def failing_exchange(code, verifier):
            raise HTTPException(401, "Autorizzazione non valida")

        monkeypatch.setattr(bff_module, "exchange_pkce", failing_exchange)

        start = await self._do_start(oauth_client)
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": "opaque-supabase-uuid"},
            headers={"Cookie": _cookie_header(start)},
        )
        assert resp.status_code == 302
        assert resp.headers["location"] == "/accedi/?errore=google"

    async def test_callback_next_cookie_never_external(self, oauth_client, monkeypatch):
        async def fake_exchange(code, verifier):
            return _fake_token_response()

        monkeypatch.setattr(bff_module, "exchange_pkce", fake_exchange)

        start = await self._do_start(oauth_client)
        # Simula un cookie `next` manomesso verso un dominio esterno
        cookie = _cookie_header(start) + "; wa_oauth_next=https://evil.com"
        resp = await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": "opaque-supabase-uuid"},
            headers={"Cookie": cookie},
        )
        assert resp.headers["location"] == "/app/"


class TestProvisioningPrimoAccesso:
    """Primo accesso Google: JIT provisioning org + owner (trial 7 giorni)."""

    async def _do_callback(self, oauth_client, monkeypatch, token=None):
        async def fake_exchange(code, verifier):
            return token or _fake_token_response()

        monkeypatch.setattr(bff_module, "exchange_pkce", fake_exchange)
        start = await oauth_client.get("/api/auth/google/start")
        return await oauth_client.get(
            "/api/auth/google/callback",
            params={"code": "c", "state": "opaque-supabase-uuid"},
            headers={"Cookie": _cookie_header(start)},
        )

    async def test_primo_accesso_provisiona_org_con_trial_7(self, oauth_client, monkeypatch):
        resp = await self._do_callback(oauth_client, monkeypatch)
        assert resp.status_code == 302
        repo = _get_repo(oauth_client._transport.app)
        assert len(repo.create_calls) == 1
        auth_user_id, nome, trial = repo.create_calls[0]
        assert auth_user_id == "u1"
        # Nessun full_name nei metadata: fallback sul prefisso email
        assert nome == "owner"
        assert trial == 7

    async def test_nome_da_full_name_google(self, oauth_client, monkeypatch):
        token = _fake_token_response(metadata={"full_name": "Mario Rossi & Figli"})
        await self._do_callback(oauth_client, monkeypatch, token)
        repo = _get_repo(oauth_client._transport.app)
        assert repo.create_calls[0][1] == "Mario Rossi & Figli"

    async def test_full_name_solo_spazi_cade_su_email(self, oauth_client, monkeypatch):
        token = _fake_token_response(metadata={"full_name": "   ", "name": "  "})
        await self._do_callback(oauth_client, monkeypatch, token)
        repo = _get_repo(oauth_client._transport.app)
        assert repo.create_calls[0][1] == "owner"

    async def test_utente_gia_membro_non_riprovisiona(self, oauth_client, monkeypatch):
        app = oauth_client._transport.app
        app.state.repo = FakeRepo(memberships=[{"organization_id": "org-1"}])
        resp = await self._do_callback(oauth_client, monkeypatch)
        assert resp.headers["location"] == "/app/"
        assert _get_repo(app).create_calls == []

    async def test_provisioning_failure_fail_closed(self, oauth_client, monkeypatch):
        app = oauth_client._transport.app
        repo = FakeRepo()

        async def boom(*a, **k):
            raise RuntimeError("db non raggiungibile")

        repo.get_or_create_organization_with_owner = boom
        app.state.repo = repo

        resp = await self._do_callback(oauth_client, monkeypatch)
        # Fail-closed: niente sessione, l'utente non entra in uno stato
        # mezzo-provisionato.
        assert resp.headers["location"] == "/accedi/?errore=google"
        set_cookies = resp.headers.get_list("set-cookie")
        assert not any(c.startswith("wa_at=") for c in set_cookies)
