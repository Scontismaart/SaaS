"""Test verifica JWT Supabase (verify_supabase_jwt).

Contratto:
- token firmati ES256 (chiavi asimmetriche, default Supabase 2025+) e RS256
  (progetti legacy) sono entrambi accettati;
- l'algoritmo è pinnato al campo "alg" del JWKS: un token firmato con una
  chiave estranea o con alg non supportato è rifiutato fail-closed (403);
- iss e aud restano verificati.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives import serialization
from jose import jwk as jose_jwk
from jose import jwt

from src.core.auth import dependencies as deps

SUPABASE_URL = "https://myproj.supabase.co"
ISS = f"{SUPABASE_URL}/auth/v1"
AUD = "authenticated"

pytestmark = pytest.mark.asyncio


def _make_jwk(private_key, alg: str) -> dict:
    jwk = jose_jwk.construct(private_key, algorithm=alg).to_dict()
    # Un JWKS pubblico non contiene mai la componente privata ("d"): senza
    # questa rimozione construct() di python-jose fallisce la verifica.
    jwk.pop("d", None)
    jwk["kid"] = str(uuid.uuid4())
    jwk["alg"] = alg
    return jwk


def _make_token(private_key, alg: str, *, iss=ISS, aud=AUD, sub="user-1", exp_offset=600) -> str:
    now = int(time.time())
    claims = {
        "sub": sub,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + exp_offset,
        "role": "authenticated",
    }
    return jwt.encode(claims, private_key, algorithm=alg)


def _ec_key():
    return ec.generate_private_key(ec.SECP256R1())


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setenv("SUPABASE_JWT_AUD", AUD)
    monkeypatch.setattr(deps, "JWKS_CACHE", {"keys": None, "expires_at": 0})


@pytest.fixture
def patch_jwks(monkeypatch):
    async def _install(keys):
        async def fake():
            return keys

        monkeypatch.setattr(deps, "_get_supabase_jwks", fake)

    return _install


async def test_token_es256_accettato(patch_jwks):
    key = _ec_key()
    await patch_jwks([_make_jwk(key, "ES256")])
    payload = await deps.verify_supabase_jwt(_make_token(key, "ES256"))
    assert payload["sub"] == "user-1"


async def test_token_rs256_legacy_accettato(patch_jwks):
    key = _rsa_key()
    await patch_jwks([_make_jwk(key, "RS256")])
    payload = await deps.verify_supabase_jwt(_make_token(key, "RS256"))
    assert payload["sub"] == "user-1"


@pytest.mark.parametrize("alg,key_factory", [("ES256", _ec_key), ("RS256", _rsa_key)])
async def test_token_scaduto_valido_richiede_refresh(patch_jwks, alg, key_factory):
    key = key_factory()
    await patch_jwks([_make_jwk(key, alg)])
    with pytest.raises(deps.HTTPException) as exc:
        await deps.verify_supabase_jwt(_make_token(key, alg, exp_offset=-60))
    assert exc.value.status_code == 401


async def test_token_scaduto_valido_conserva_l_identita_per_refresh(patch_jwks):
    key = _ec_key()
    await patch_jwks([_make_jwk(key, "ES256")])
    payload = await deps.verify_supabase_jwt(
        _make_token(key, "ES256", sub="user-refresh", exp_offset=-60),
        allow_expired=True,
    )
    assert payload["sub"] == "user-refresh"


async def test_token_scaduto_con_issuer_estraneo_resta_rifiutato(patch_jwks):
    key = _ec_key()
    await patch_jwks([_make_jwk(key, "ES256")])
    with pytest.raises(deps.HTTPException) as exc:
        await deps.verify_supabase_jwt(
            _make_token(key, "ES256", iss="https://other.supabase.co/auth/v1", exp_offset=-60)
        )
    assert exc.value.status_code == 403


async def test_chiave_senza_camp_alg_prova_entrambe(monkeypatch, patch_jwks):
    key = _ec_key()
    jwk = _make_jwk(key, "ES256")
    jwk.pop("alg")
    await patch_jwks([jwk])
    payload = await deps.verify_supabase_jwt(_make_token(key, "ES256"))
    assert payload["sub"] == "user-1"


async def test_token_firmato_da_chiave_esterna_rifiutato(patch_jwks):
    good = _ec_key()
    evil = _ec_key()
    await patch_jwks([_make_jwk(good, "ES256")])
    with pytest.raises(Exception) as exc:
        await deps.verify_supabase_jwt(_make_token(evil, "ES256"))
    assert getattr(exc.value, "status_code", None) in (403, None)


async def test_issuer_diverso_rifiutato(patch_jwks):
    key = _ec_key()
    await patch_jwks([_make_jwk(key, "ES256")])
    with pytest.raises(Exception):
        await deps.verify_supabase_jwt(
            _make_token(key, "ES256", iss="https://evil.supabase.co/auth/v1")
        )


async def test_audience_diversa_rifiutata(patch_jwks):
    key = _ec_key()
    await patch_jwks([_make_jwk(key, "ES256")])
    with pytest.raises(Exception):
        await deps.verify_supabase_jwt(_make_token(key, "ES256", aud="other"))


async def test_alg_non_supportato_saltato(patch_jwks):
    """Una chiave HS256 nel JWKS non deve mai essere usata per RS/ES token."""
    key = _ec_key()
    hs_jwk = {
        "kty": "oct",
        "k": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "alg": "HS256",
    }
    await patch_jwks([hs_jwk, _make_jwk(key, "ES256")])
    payload = await deps.verify_supabase_jwt(_make_token(key, "ES256"))
    assert payload["sub"] == "user-1"


async def test_nessuna_chiave_valida_fail_closed(patch_jwks):
    await patch_jwks([])
    with pytest.raises(deps.HTTPException) as exc:
        await deps.verify_supabase_jwt("qualsiasi.token.qui")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("alg,key_factory", [("RS256", _rsa_key), ("ES256", _ec_key)])
@pytest.mark.parametrize("missing_alg", [False, True])
@pytest.mark.parametrize("allow_expired", [False, True])
@pytest.mark.parametrize("exp_offset", [-600, 600])
async def test_der_public_key_hmac_forgery_rejected(
    monkeypatch, patch_jwks, alg, key_factory, missing_alg, allow_expired, exp_offset
):
    """CVE-2026-85394: public DER bytes must never authorize HS256 JWTs."""
    key = key_factory()
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    def encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    header = encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = encode(json.dumps({"sub": "forged-test-user", "aud": AUD, "iss": ISS,
                                 "exp": int(time.time()) + exp_offset}).encode())
    signed = header + b"." + payload
    token = (signed + b"." + encode(hmac.new(der, signed, hashlib.sha256).digest())).decode()

    # Positive control: this is a real library exploit, not an invalid token.
    assert jwt.decode(token, der, algorithms=[alg, "HS256"], audience=AUD, issuer=ISS,
                      options={"verify_exp": False})["sub"] == "forged-test-user"
    jwk = _make_jwk(key, alg)
    if missing_alg:
        jwk.pop("alg")
    await patch_jwks([jwk])
    decoder = Mock(wraps=jwt.decode)
    monkeypatch.setattr(jwt, "decode", decoder)
    with pytest.raises(deps.HTTPException) as exc:
        await deps.verify_supabase_jwt(token, allow_expired=allow_expired)
    assert exc.value.status_code == 403
    assert decoder.called
    for call in decoder.call_args_list:
        assert call.kwargs["algorithms"]
        assert set(call.kwargs["algorithms"]) <= {"RS256", "ES256"}
