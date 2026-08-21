"""CSRF protection for cookie-authenticated browser requests."""

from __future__ import annotations

import os
import secrets
from urllib.parse import urlparse

from fastapi import Request, Response

CSRF_COOKIE = "wa_csrf"
CSRF_HEADER = "X-CSRF-Token"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/health",
    "/api/billing/webhook",
    "/webhooks/whatsapp",
    "/webhooks/instagram",
}


def csrf_cookie_name() -> str:
    from src.core.auth import bff

    return f"__Host-{CSRF_COOKIE}" if bff.cookie_secure() else CSRF_COOKIE


def issue_csrf_token(response: Response) -> str:
    from src.core.auth import bff

    token = secrets.token_urlsafe(32)
    response.set_cookie(
        csrf_cookie_name(),
        token,
        httponly=False,
        secure=bff.cookie_secure(),
        samesite="strict",
        path="/",
    )
    return token


def clear_csrf_token(response: Response) -> None:
    response.delete_cookie(csrf_cookie_name(), path="/")


def _allowed_origins() -> set[str]:
    raw = os.getenv("CSRF_TRUSTED_ORIGINS") or os.getenv("CORS_ORIGINS", "")
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin:
        return origin.rstrip("/")
    referer = request.headers.get("referer")
    if not referer:
        return None
    parsed = urlparse(referer)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _same_origin(request: Request, origin: str) -> bool:
    parsed = urlparse(origin)
    host = request.headers.get("host")
    return bool(host and parsed.netloc == host and parsed.scheme in {"http", "https"})


def is_cookie_authenticated_mutation(request: Request) -> bool:
    if request.method.upper() not in MUTATING_METHODS:
        return False
    if request.url.path in CSRF_EXEMPT_PATHS:
        return False
    if request.headers.get("authorization") or request.headers.get("x-api-key"):
        return False
    from src.core.auth import bff

    return bool(
        request.cookies.get(bff.access_cookie_name())
        or request.cookies.get(bff.refresh_cookie_name())
    )


def validate_csrf_request(request: Request) -> tuple[bool, str | None]:
    if not is_cookie_authenticated_mutation(request):
        return True, None

    origin = _request_origin(request)
    allowed = _allowed_origins()
    if not origin or (origin not in allowed and not _same_origin(request, origin)):
        return False, "Origine richiesta non valida"

    cookie_token = request.cookies.get(csrf_cookie_name())
    header_token = request.headers.get(CSRF_HEADER)
    if not cookie_token or not header_token or not secrets.compare_digest(cookie_token, header_token):
        return False, "CSRF token non valido"
    return True, None
