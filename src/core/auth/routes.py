"""Endpoint BFF di autenticazione (/api/auth/*).

Il frontend si autentica qui: il backend scambia le credenziali con Supabase
Auth e restituisce la sessione in cookie HttpOnly+Secure+SameSite=Strict.
Nessun token transita dal client (niente localStorage, niente header Bearer).
"""

import hashlib
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from src.core.auth import bff
from src.core.auth.dependencies import get_organization_context

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Anti brute-force su /api/auth/login: fallimenti consecutivi per IP.
# In-memory per processo (stessa limitazione del rate-limiter globale).
_LOGIN_FAILURES: dict[str, list[float]] = {}
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_LOCKOUT_SECONDS = 15 * 60


class LoginRequest(BaseModel):
    email: str
    password: str


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _check_login_throttle(ip: str) -> None:
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SECONDS
    failures = [t for t in _LOGIN_FAILURES.get(ip, []) if t > cutoff]
    if len(failures) >= _LOGIN_MAX_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Troppi tentativi di accesso. Riprova tra 15 minuti.",
        )
    _LOGIN_FAILURES[ip] = failures


def _record_login_failure(ip: str) -> None:
    _LOGIN_FAILURES.setdefault(ip, []).append(time.time())


def _record_login_success(ip: str) -> None:
    _LOGIN_FAILURES.pop(ip, None)


def _set_session_cookies(response: Response, data: dict) -> None:
    common = {
        "httponly": True,
        "secure": bff.cookie_secure(),
        "samesite": "strict",
        "path": "/",
    }
    response.set_cookie(bff.access_cookie_name(), data["access_token"], **common)
    response.set_cookie(bff.refresh_cookie_name(), data["refresh_token"], **common)


def _clear_session_cookies(response: Response) -> None:
    for name in (bff.access_cookie_name(), bff.refresh_cookie_name()):
        response.delete_cookie(name, path="/")


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    ip = _client_ip(request)
    _check_login_throttle(ip)
    try:
        data = await bff.login(body.email.strip(), body.password)
    except HTTPException:
        _record_login_failure(ip)
        raise
    _record_login_success(ip)
    _set_session_cookies(response, data)
    return {"ok": True, "email": body.email.strip()}


@router.post("/refresh")
async def refresh(request: Request, response: Response):
    rt = request.cookies.get(bff.refresh_cookie_name())
    if not rt:
        raise HTTPException(status_code=401, detail="Sessione scaduta")
    # user_key anonimo: digest del token, mai il token grezzo in memoria
    user_key = hashlib.sha256(rt.encode()).hexdigest()
    data = await bff.refresh(rt, user_key)
    _set_session_cookies(response, data)
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    at = request.cookies.get(bff.access_cookie_name())
    if at:
        await bff.logout(at)
    _clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
async def me(user: dict = Depends(get_organization_context)):
    return {
        "email": user.get("email"),
        "organization_id": user.get("organization_id"),
        "ruolo": user.get("ruolo"),
        "user_id": user.get("user_id"),
        "source": user.get("source"),
    }