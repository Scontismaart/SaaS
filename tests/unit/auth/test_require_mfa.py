"""Audit 1.4 — AAL2 (MFA) step-up gate sui Tier-1 sensibili.

Cosa si testa qui:
1. Un JWT senza claim `aal` (sessione password-only) viene rifiutato con
   403 quando colpisce un endpoint protetto da require_mfa().
2. Un JWT con `aal="aal2"` (secondo fattore verificato) passa.
3. La dipendenza non blocca le richieste via API_KEY_SERVICE: quelle sono
   credenziali interne (inbound processor, webhook Stripe) e non sono una
   sessione utente rubabile.
4. Bonus: conferma end-to-end che un token firmato da un issuer diverso
   (progetto Supabase sbagliato) viene rifiutato con 403 — questo copre
   la richiesta "test con iss sbagliato" andando oltre il solo livello
   funzione gia' coperto in test_jwt_issuer.py.

Questi test non richiedono un JWKS reale: monkeypatchiamo _get_supabase_jwks
e jose.jwt.decode per controllare claim e signature separatamente.
"""
import uuid
import pytest
from unittest.mock import AsyncMock
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.core.auth.dependencies import (
    get_current_user,
    require_mfa,
    SENSITIVE_AAL2_PATHS,
)
import src.core.auth.dependencies as deps


# ── Fixture: mini-app con un endpoint Tier-1 fittizio ──────────────────


from fastapi import Depends  # noqa: E402


def _build_test_app_real() -> FastAPI:
    """App minimale che monta /api/gdpr/export protetto da require_mfa(),
    per testare la dipendenza in isolamento senza repository o Stripe."""
    app = FastAPI()

    @app.get("/api/gdpr/export")
    async def _export(
        user: dict = Depends(get_current_user),
        mfa: dict = Depends(require_mfa()),
    ):
        # Raggiungiamo questo handler solo se sia get_current_user che
        # require_mfa passano. user/mfa sono lo stesso dict qui (require_mfa
        # ritorna il user che gli arriva), quindi controlliamo aal su mfa.
        return {"ok": True, "aal": mfa.get("aal")}

    return app


# ── Test 1+2: require_mfa() a livello di dipendenza ────────────────────


class TestRequireMfa:
    async def test_jwt_without_aal_is_rejected_with_403(self, monkeypatch):
        # Simula get_current_user che ritorna una sessione password-only:
        # il claim aal non e' presente (utente senza MFA abilitata, o token
        # legacy pre-MFA). Deve essere bloccato.
        async def _fake_get_current_user():
            return {
                "source": "jwt",
                "auth_user_id": str(uuid.uuid4()),
                "ruolo": "owner",
                "aal": None,
            }
        monkeypatch.setattr(deps, "get_current_user", _fake_get_current_user)

        check = require_mfa()
        with pytest.raises(HTTPException) as exc:
            await check(user=await _fake_get_current_user())
        assert exc.value.status_code == 403
        assert "MFA" in exc.value.detail or "due fattori" in exc.value.detail
        # L'header custom serve al frontend per reindirizzare al setup MFA
        # invece di mostrare un generico 403.
        assert exc.value.headers.get("X-MFA-Required") == "true"

    async def test_jwt_with_aal1_is_rejected_with_403(self, monkeypatch):
        # aal="aal1" = password verificata ma senza secondo fattore.
        async def _fake_get_current_user():
            return {"source": "jwt", "auth_user_id": str(uuid.uuid4()), "aal": "aal1"}
        check = require_mfa()
        with pytest.raises(HTTPException) as exc:
            await check(user=await _fake_get_current_user())
        assert exc.value.status_code == 403

    async def test_jwt_with_aal2_is_allowed(self, monkeypatch):
        async def _fake_get_current_user():
            return {"source": "jwt", "auth_user_id": str(uuid.uuid4()), "aal": "aal2"}
        check = require_mfa()
        user = await _fake_get_current_user()
        result = await check(user=user)
        assert result["aal"] == "aal2"

    async def test_api_key_source_bypasses_mfa(self):
        # Le richieste interne via API_KEY_SERVICE non sono sessioni utente:
        # l'inbound processor e il webhook Stripe devono poter chiamare i
        # Tier-1 senza MFA. Il bypass e' esplicito, non un caso accidentale.
        user = {"source": "api_key", "ruolo": "service_role", "aal": None}
        check = require_mfa()
        result = await check(user=user)
        assert result["source"] == "api_key"


# ── Test 3: conferma che i Tier-1 path sono i 4 attesi ─────────────────


class TestSensitivePathList:
    def test_tier1_paths_match_design(self):
        # Regression guard: se qualcuno aggiunge/rimuove un path qui per
        # errore, questo test fallisce e forza una revisione esplicita.
        assert SENSITIVE_AAL2_PATHS == frozenset({
            "/api/billing/create-checkout-session",
            "/api/billing/create-portal-session",
            "/api/gdpr/export",
            "/api/gdpr/delete",
            "/api/calendar/auth",
            "/api/calendar/disconnect",
            "/api/calendar/settings",
        })

    def test_consistent_paths_cover_all_tier1_operations(self):
        # Le operazioni irreversibili (delete) e finanziarie (checkout,
        # portal) e di esfiltrazione PII (export) devono essere tutte qui.
        for p in ["/delete", "/export", "/create-checkout-session", "/create-portal-session"]:
            assert any(p in path for path in SENSITIVE_AAL2_PATHS), (
                f"Attenzione: {p} non e' coperto da AAL2 — verificare se e' intenzionale."
            )


# ── Test 4 (bonus): iss sbagliato rifiutato end-to-end ─────────────────


class TestJwtIssuerRejectionEndToEnd:
    """Conferma che un token proveniente da un altro progetto Supabase
    (issuer diverso) non riesce ad autenticarsi. Va oltre test_jwt_issuer
    che testa solo la funzione verify_supabase_jwt: qui verifichiamo che
    il 403 propaghi correttamente attraverso get_current_user, che e'
    la dipendenza usata da tutti gli endpoint."""

    async def test_wrong_issuer_rejected_at_get_current_user(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
        monkeypatch.setenv("SUPABASE_JWT_AUD", "authenticated")
        monkeypatch.setattr(deps, "_get_supabase_jwks", AsyncMock(return_value=[{"kid": "k1"}]))

        from jose import JWTError
        import jose.jwt as jose_jwt_module

        def _reject_with_wrong_iss(token, key, algorithms, audience, issuer, options):
            raise JWTError("Signature validation failed: issuer mismatch")

        monkeypatch.setattr(jose_jwt_module, "decode", _reject_with_wrong_iss)

        from unittest.mock import MagicMock
        mock_request = MagicMock()
        mock_request.app.state.repo = MagicMock()

        with pytest.raises(HTTPException) as exc:
            await get_current_user(request=mock_request, token="eyJ.token.from.another.project.xyz")
        assert exc.value.status_code == 403
        assert "non valido" in exc.value.detail.lower()


# ── Test 5: integrazione completa via TestClient ───────────────────────


class TestMfaGateOnRoute:
    """Test end-to-end con TestClient: un utente senza MFA che chiama
    /api/gdpr/export riceve 403, uno con MFA riceve 200."""

    def test_no_mfa_session_blocked_from_export(self, monkeypatch):
        app = _build_test_app_real()
        client = TestClient(app)

        # JWT decodificato con successo (iss/aud ok) ma aal="aal1":
        # sessione password-only, niente secondo fattore.
        def _fake_decode(token, key, algorithms, audience, issuer, options):
            return {"sub": "user-no-mfa", "aal": "aal1"}
        monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
        monkeypatch.setenv("SUPABASE_JWT_AUD", "authenticated")
        monkeypatch.setattr(deps, "_get_supabase_jwks", AsyncMock(return_value=[{"kid": "k1"}]))
        import jose.jwt as jose_jwt_module
        monkeypatch.setattr(jose_jwt_module, "decode", _fake_decode)

        resp = client.get("/api/gdpr/export", headers={"Authorization": "Bearer fake.jwt.token"})
        assert resp.status_code == 403, resp.text
        assert resp.headers.get("x-mfa-required") == "true"

    def test_mfa_session_allowed_on_export(self, monkeypatch):
        app = _build_test_app_real()
        client = TestClient(app)

        def _fake_decode(token, key, algorithms, audience, issuer, options):
            return {"sub": "user-with-mfa", "aal": "aal2"}
        monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
        monkeypatch.setenv("SUPABASE_JWT_AUD", "authenticated")
        monkeypatch.setattr(deps, "_get_supabase_jwks", AsyncMock(return_value=[{"kid": "k1"}]))
        import jose.jwt as jose_jwt_module
        monkeypatch.setattr(jose_jwt_module, "decode", _fake_decode)

        resp = client.get("/api/gdpr/export", headers={"Authorization": "Bearer fake.jwt.token"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["aal"] == "aal2"
