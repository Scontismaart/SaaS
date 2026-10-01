"""BFF per Supabase Auth (Backend-for-Frontend).

Il frontend NON tocca mai i token: invia email+password a /api/auth/login, il
backend scambia le credenziali con Supabase Auth via REST e salva la sessione
in cookie HttpOnly+Secure+SameSite=Lax. I token restano inaccessibili a JS
(nessun localStorage), eliminando la superficie XSS sui token.

Conforme al design in docs/CHECKLIST-PRE-LANCIO.md (sostituzione auth
transitoria) e al piano task18/auth-bff.
"""

import asyncio
import base64
import hashlib
import os

import httpx
from fastapi import HTTPException

SUPABASE_AUTH_TIMEOUT = 10.0

# Nomi base dei cookie di sessione. In produzione (Secure) il prefisso
# __Host- li lega al dominio esatto, impedendo cookie collision su
# sottodomini diversi.
ACCESS_COOKIE = "wa_at"
REFRESH_COOKIE = "wa_rt"

# Lock per-token per il single-flight del refresh: previene race condition
# quando molte richieste asincrone falliscono 401 insieme e innescano refresh
# concorrenti. Limitazione nota: come il rate-limiter, è in-memory per
# processo — in un deploy multi-processo ogni processo ha i propri lock.
_refresh_locks: dict[str, asyncio.Lock] = {}

_HTTP: httpx.AsyncClient | None = None


def cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "true").strip().lower() in ("1", "true", "yes")


def access_cookie_name() -> str:
    return f"__Host-{ACCESS_COOKIE}" if cookie_secure() else ACCESS_COOKIE


def refresh_cookie_name() -> str:
    return f"__Host-{REFRESH_COOKIE}" if cookie_secure() else REFRESH_COOKIE


def _supabase_url() -> str:
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    if not url:
        raise HTTPException(500, "SUPABASE_URL non configurato")
    return url


def _anon_key() -> str:
    key = os.getenv("SUPABASE_ANON_KEY", "")
    if not key:
        raise HTTPException(500, "SUPABASE_ANON_KEY non configurato")
    return key


async def _client() -> httpx.AsyncClient:
    global _HTTP
    if _HTTP is None:
        _HTTP = httpx.AsyncClient(timeout=SUPABASE_AUTH_TIMEOUT)
    return _HTTP


async def _token_request(payload: dict) -> dict:
    """POST /auth/v1/token verso Supabase Auth (grant_type password/refresh)."""
    client = await _client()
    grant_type = payload.get("grant_type")
    params = {"grant_type": grant_type} if grant_type else None
    resp = await client.post(
        f"{_supabase_url()}/auth/v1/token",
        params=params,
        json=payload,
        headers={"apikey": _anon_key(), "Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        # Non rivelare dettagli (es. "user not found" vs "wrong password"):
        # un unico 401 generico evita l'enumerazione degli account.
        raise HTTPException(401, "Credenziali non valide")
    return resp.json()


async def login(email: str, password: str) -> dict:
    return await _token_request(
        {"grant_type": "password", "email": email, "password": password}
    )


def public_app_url() -> str:
    url = os.getenv("PUBLIC_APP_URL", "").rstrip("/")
    if not url:
        raise HTTPException(500, "PUBLIC_APP_URL non configurato")
    return url


def pkce_challenge(code_verifier: str) -> str:
    """S256: BASE64URL(SHA256(verifier)) senza padding (RFC 7636)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def google_authorize_url(redirect_to: str, code_challenge: str) -> str:
    """URL di avvio OAuth Google su Supabase Auth (PKCE). Il browser viene
    reindirizzato qui; Supabase gestisce il dialog Google e torna su
    `redirect_to` con ?code=...&state=...

    Nota: lo `state` OAuth è generato e validato internamente da Supabase
    Auth (uuid della flow_state): passarne uno custom rompe il flusso
    (bad_oauth_state). Il binding anti-CSRF resta garantito da PKCE: il
    verifier viaggia solo nel nostro cookie HttpOnly.
    """
    from urllib.parse import urlencode

    query = urlencode(
        {
            "provider": "google",
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{_supabase_url()}/auth/v1/authorize?{query}"


async def exchange_pkce(auth_code: str, code_verifier: str) -> dict:
    """Scambio del codice PKCE con Supabase Auth: stessa risposta della
    /token (access_token + refresh_token), che il chiamante mette in cookie."""
    client = await _client()
    resp = await client.post(
        f"{_supabase_url()}/auth/v1/token",
        params={"grant_type": "pkce"},
        json={"auth_code": auth_code, "code_verifier": code_verifier},
        headers={"apikey": _anon_key(), "Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        if resp.status_code in {408, 429} or resp.status_code >= 500:
            # Transient provider/rate-limit failures retain the caller's PKCE flow.
            raise HTTPException(503, "Autorizzazione temporaneamente non disponibile")
        # Permanent PKCE/code rejection stays generic and does not expose details.
        raise HTTPException(401, "Autorizzazione non valida")
    return resp.json()


async def refresh(refresh_token: str, user_key: str) -> dict:
    """Rotazione del refresh token con single-flight per utente/token.

    `user_key` è un digest del refresh token (anonimo, mai il token grezzo):
    se N richieste scadute arrivano insieme, una sola va su Supabase e le
    altre riusano lo stesso risultato di rotazione.
    """
    lock = _refresh_locks.get(user_key)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[user_key] = lock
    async with lock:
        try:
            return await _token_request(
                {"grant_type": "refresh_token", "refresh_token": refresh_token}
            )
        finally:
            if _refresh_locks.get(user_key) is lock:
                del _refresh_locks[user_key]


async def logout(access_token: str, *, scope: str = "local") -> None:
    """Revoca la sessione corrente su Supabase (non gli altri dispositivi)."""
    client = await _client()
    try:
        await client.post(
            f"{_supabase_url()}/auth/v1/logout",
            params={"scope": scope},
            headers={"apikey": _anon_key(), "Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError:
        pass
