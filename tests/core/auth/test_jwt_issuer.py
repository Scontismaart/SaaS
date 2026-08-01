import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

import src.core.auth.dependencies as deps


class TestVerifySupabaseJwtIssuer:
    """Audit 1.4: verify_supabase_jwt deve validare l'issuer (iss), non solo
    l'audience. Verifichiamo che il claim iss atteso sia costruito da
    SUPABASE_URL e passato correttamente a jose, e che un iss non
    corrispondente faccia fallire la verifica con 403."""

    async def test_matching_issuer_accepted(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
        monkeypatch.setenv("SUPABASE_JWT_AUD", "authenticated")
        monkeypatch.setattr(deps, "_get_supabase_jwks", AsyncMock(return_value=[{"kid": "k1"}]))

        captured = {}

        def fake_decode(token, key, algorithms, audience, issuer, options):
            captured["issuer"] = issuer
            captured["verify_iss"] = options.get("verify_iss")
            assert issuer == "https://myproj.supabase.co/auth/v1"
            return {"sub": "user-1"}

        import jose.jwt as jose_jwt_module
        monkeypatch.setattr(jose_jwt_module, "decode", fake_decode)

        payload = await deps.verify_supabase_jwt("fake.token.here")
        assert payload == {"sub": "user-1"}
        assert captured["verify_iss"] is True

    async def test_mismatched_issuer_rejected(self, monkeypatch):
        monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
        monkeypatch.setenv("SUPABASE_JWT_AUD", "authenticated")
        monkeypatch.setattr(deps, "_get_supabase_jwks", AsyncMock(return_value=[{"kid": "k1"}]))

        import jose.jwt as jose_jwt_module
        from jose import JWTError

        def fake_decode_wrong_iss(token, key, algorithms, audience, issuer, options):
            # simula jose che rifiuta perche' il token porta un iss diverso
            # da quello atteso passato come parametro issuer
            raise JWTError("Invalid issuer")

        monkeypatch.setattr(jose_jwt_module, "decode", fake_decode_wrong_iss)

        with pytest.raises(HTTPException) as exc:
            await deps.verify_supabase_jwt("token.from.other.project")
        assert exc.value.status_code == 403

    async def test_missing_supabase_url_skips_iss_verification(self, monkeypatch):
        # Se SUPABASE_URL non e' configurato non possiamo costruire l'iss
        # atteso: verify_iss deve essere False per non rompere in ambienti
        # di test/demo senza Supabase configurato, invece di crashare.
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.setenv("SUPABASE_JWT_AUD", "authenticated")
        monkeypatch.setattr(deps, "_get_supabase_jwks", AsyncMock(return_value=[{"kid": "k1"}]))

        captured = {}

        def fake_decode(token, key, algorithms, audience, issuer, options):
            captured["verify_iss"] = options.get("verify_iss")
            captured["issuer"] = issuer
            return {"sub": "user-1"}

        import jose.jwt as jose_jwt_module
        monkeypatch.setattr(jose_jwt_module, "decode", fake_decode)

        payload = await deps.verify_supabase_jwt("fake.token")
        assert payload == {"sub": "user-1"}
        assert captured["verify_iss"] is False
        assert captured["issuer"] is None
