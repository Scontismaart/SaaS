"""Suite di test per il layer di autenticazione OAuth2 di Apaleo (apaleo_auth.py).

Copre tutti i requisiti specificati:
1. Initial token (client credentials e refresh token)
2. Valid cached token (zero chiamate HTTP aggiuntive)
3. Expired token (rinnovo automatico oltre soglia clock-skew)
4. Refresh token flow con eventuale token rotation
5. Invalid refresh / invalid_grant (solleva ApaleoInvalidGrantError, invalidazione stato)
6. Authentication failure (HTTP 401/403)
7. Concorrenza (N richieste parallele simultanee -> esattamente 1 sola richiesta HTTP al token endpoint)
8. Timeout ed errori server (5xx)
9. Scambio iniziale authorization code
10. Callback di persistenza cifrata on_token_refreshed
11. Zero Secret Logging (mascheramento stringa)
"""
import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from src.core.bookings.adapters.apaleo_auth import (
    ApaleoAuthError,
    ApaleoInvalidGrantError,
    ApaleoOAuthClient,
    ApaleoTokenRequestError,
)

ORG_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
TEST_CLIENT_ID = "APALEO-TEST-CLIENT-01"
TEST_CLIENT_SECRET = "super_secret_client_key_999"
TEST_REFRESH_TOKEN = "test_refresh_token_xyz_123"


# ── 1. Initial Token (Client Credentials Flow) ───────────────

@pytest.mark.asyncio
async def test_initial_token_client_credentials():
    """Se non c'è refresh_token, richiede token iniziale con grant_type=client_credentials."""
    captured_req = {}

    def handler(request: httpx.Request):
        nonlocal captured_req
        assert request.url.path == "/connect/token"
        assert request.headers["authorization"].startswith("Basic ")
        assert request.headers["content-type"] == "application/x-www-form-urlencoded"
        captured_req["content"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "token_cc_live_001",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "reservations.read reservations.manage",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        client=client,
    )

    assert auth.grant_type == "client_credentials"
    assert auth.has_refresh_token is False
    assert auth.is_token_valid() is False

    token = await auth.get_access_token()
    assert token == "token_cc_live_001"
    assert auth.is_token_valid() is True
    assert "grant_type=client_credentials" in captured_req["content"]


# ── 2. Valid Cached Token ────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_cached_token_skips_http():
    """Se il token in cache è ancora valido, non deve fare alcuna chiamata HTTP (zero latency/overhead)."""
    http_call_count = 0

    def handler(request: httpx.Request):
        nonlocal http_call_count
        http_call_count += 1
        return httpx.Response(200, json={"access_token": "token_val_001", "expires_in": 3600})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        initial_access_token="existing_valid_token",
        initial_expires_at=time.time() + 1800,  # valido per altri 30 minuti
        client=client,
    )

    assert auth.is_token_valid() is True
    token = await auth.get_access_token()
    assert token == "existing_valid_token"
    assert http_call_count == 0  # Nessuna chiamata HTTP effettuata


# ── 3. Expired Token & Clock-Skew Buffer ──────────────────────

@pytest.mark.asyncio
async def test_expired_token_triggers_automatic_refresh():
    """Se il token è scaduto o all'interno del buffer di clock skew, richiede un nuovo token."""
    http_call_count = 0

    def handler(request: httpx.Request):
        nonlocal http_call_count
        http_call_count += 1
        return httpx.Response(200, json={"access_token": "new_fresh_token", "expires_in": 3600})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    # Token che scade tra 30s, ma clock_skew è 60s -> considerato scaduto a monte!
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        initial_access_token="soon_to_expire_token",
        initial_expires_at=time.time() + 30,
        clock_skew_seconds=60.0,
        client=client,
    )

    assert auth.is_token_valid() is False
    token = await auth.get_access_token()
    assert token == "new_fresh_token"
    assert http_call_count == 1
    assert auth.is_token_valid() is True


# ── 4. Refresh Token Flow & Rotation ─────────────────────────

@pytest.mark.asyncio
async def test_refresh_token_flow_with_rotation():
    """Se inizializzato con refresh_token, usa grant_type=refresh_token e accetta token rotation."""
    captured_data = {}

    def handler(request: httpx.Request):
        nonlocal captured_data
        captured_data["content"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "token_refreshed_002",
                "expires_in": 3600,
                "token_type": "Bearer",
                "refresh_token": "rotated_new_refresh_token_789",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        refresh_token="initial_refresh_token_123",
        client=client,
    )

    assert auth.grant_type == "refresh_token"
    assert auth.has_refresh_token is True

    token = await auth.get_access_token()
    assert token == "token_refreshed_002"
    assert "grant_type=refresh_token" in captured_data["content"]
    assert "refresh_token=initial_refresh_token_123" in captured_data["content"]
    # Verifica che il nuovo refresh token sia stato memorizzato (rotation)
    assert auth._refresh_token == "rotated_new_refresh_token_789"


# ── 5. Invalid Refresh / Invalid Grant ────────────────────────

@pytest.mark.asyncio
async def test_invalid_grant_revocation_error():
    """HTTP 400 con error='invalid_grant' solleva ApaleoInvalidGrantError e marca il client come invalidato."""
    def handler(request: httpx.Request):
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "The refresh token has expired or has been revoked",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        refresh_token="revoked_refresh_token",
        client=client,
    )

    with pytest.raises(ApaleoInvalidGrantError) as exc_info:
        await auth.get_access_token()

    assert "invalid_grant" in str(exc_info.value)
    assert auth._is_invalidated is True
    assert auth._access_token is None

    # Successive chiamate devono fallire immediatamente senza rifare HTTP request
    with pytest.raises(ApaleoInvalidGrantError):
        await auth.get_access_token()


# ── 6. Authentication Failure (HTTP 401) ──────────────────────

@pytest.mark.asyncio
async def test_client_credentials_auth_failure_401():
    """HTTP 401 (client_id o client_secret errati) solleva ApaleoAuthError."""
    def handler(request: httpx.Request):
        return httpx.Response(
            401,
            json={"error": "invalid_client", "error_description": "Bad client credentials"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id="BAD_CLIENT",
        client_secret="BAD_SECRET",
        client=client,
    )

    with pytest.raises(ApaleoAuthError) as exc_info:
        await auth.get_access_token()
    assert "401" in str(exc_info.value) or "invalid_client" in str(exc_info.value)


# ── 7. Concorrenza: Double-Checked Locking (Zero Token Storm) ─

@pytest.mark.asyncio
async def test_concurrent_access_single_http_request():
    """Quando 10 coroutine richiedono contemporaneamente il token con cache vuota, viene eseguita 1 SOLA chiamata HTTP."""
    http_call_count = 0

    async def handler(request: httpx.Request):
        nonlocal http_call_count
        http_call_count += 1
        # Simula una leggera latenza di rete (50ms) per favorire l'accodamento delle coroutine sul lock
        await asyncio.sleep(0.05)
        return httpx.Response(
            200,
            json={
                "access_token": "token_concurrent_winner",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        client=client,
    )

    # Lancia 10 chiamate contemporanee identiche
    results = await asyncio.gather(*(auth.get_access_token() for _ in range(10)))

    # Tutte e 10 le coroutine ricevono lo stesso identico token
    assert all(r == "token_concurrent_winner" for r in results)
    # Ma al server token è partita ESATTAMENTE 1 sola richiesta HTTP!
    assert http_call_count == 1


# ── 8. Timeout ed Errori Server (5xx) ────────────────────────

@pytest.mark.asyncio
async def test_server_error_500():
    """HTTP 500 del server identity solleva ApaleoTokenRequestError."""
    def handler(request: httpx.Request):
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        client=client,
    )

    with pytest.raises(ApaleoTokenRequestError):
        await auth.get_access_token()


@pytest.mark.asyncio
async def test_timeout_network_error():
    """Timeout HTTP solleva ApaleoTokenRequestError."""
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("Connection timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        client=client,
    )

    with pytest.raises(ApaleoTokenRequestError, match="Timeout"):
        await auth.get_access_token()


# ── 9. Scambio Iniziale Authorization Code ───────────────────

@pytest.mark.asyncio
async def test_exchange_authorization_code_success():
    """exchange_authorization_code scambia il code ricevuto dal redirect con access_token e refresh_token."""
    captured_data = {}

    def handler(request: httpx.Request):
        nonlocal captured_data
        captured_data["content"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "access_token": "token_from_auth_code",
                "refresh_token": "refresh_from_auth_code",
                "expires_in": 3600,
                "token_type": "Bearer",
                "scope": "reservations.manage",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        client=client,
    )

    res = await auth.exchange_authorization_code(code="auth_code_xyz", redirect_uri="https://saas.it/oauth/callback")
    assert res["access_token"] == "token_from_auth_code"
    assert res["refresh_token"] == "refresh_from_auth_code"
    assert auth._access_token == "token_from_auth_code"
    assert auth._refresh_token == "refresh_from_auth_code"
    assert "grant_type=authorization_code" in captured_data["content"]
    assert "code=auth_code_xyz" in captured_data["content"]
    assert "redirect_uri=https%3A%2F%2Fsaas.it%2Foauth%2Fcallback" in captured_data["content"]


# ── 10. Callback di Persistenza Cifrata ───────────────────────

@pytest.mark.asyncio
async def test_on_token_refreshed_callback_invoked():
    """Quando un token viene aggiornato o ruotato, la callback on_token_refreshed viene invocata per persistenza DB."""
    persisted_tokens = None

    async def mock_callback(tokens: dict):
        nonlocal persisted_tokens
        persisted_tokens = tokens

    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "access_token": "persisted_token_abc",
                "expires_in": 3600,
                "refresh_token": "persisted_refresh_xyz",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id=TEST_CLIENT_ID,
        client_secret=TEST_CLIENT_SECRET,
        refresh_token="old_refresh",
        on_token_refreshed=mock_callback,
        client=client,
    )

    await auth.get_access_token()
    assert persisted_tokens is not None
    assert persisted_tokens["access_token"] == "persisted_token_abc"
    assert persisted_tokens["refresh_token"] == "persisted_refresh_xyz"
    assert "expires_at" in persisted_tokens


# ── 11. Zero Secret Leak (Rappresentazione Stringa) ───────────

def test_zero_secret_leak_in_repr():
    """__repr__ e __str__ non devono mai rivelare client_secret, access_token o refresh_token."""
    auth = ApaleoOAuthClient(
        organization_id=ORG_ID,
        client_id="CLIENT_PUB_123",
        client_secret="TOP_SECRET_PLAINTEXT_SECRET",
        refresh_token="PLAINTEXT_REFRESH_TOKEN",
        initial_access_token="PLAINTEXT_ACCESS_TOKEN",
        initial_expires_at=time.time() + 1000,
    )

    r_repr = repr(auth)
    r_str = str(auth)

    # I segreti non devono essere presenti
    assert "TOP_SECRET_PLAINTEXT_SECRET" not in r_repr
    assert "PLAINTEXT_REFRESH_TOKEN" not in r_repr
    assert "PLAINTEXT_ACCESS_TOKEN" not in r_repr

    assert "TOP_SECRET_PLAINTEXT_SECRET" not in r_str
    assert "PLAINTEXT_REFRESH_TOKEN" not in r_str
    assert "PLAINTEXT_ACCESS_TOKEN" not in r_str

    # I metadati non sensibili sono presenti
    assert "CLIENT_PUB_123" in r_repr
    assert "has_refresh_token=True" in r_repr
    assert "is_valid=True" in r_repr
