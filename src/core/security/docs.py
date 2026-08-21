"""Protected API documentation endpoints for production."""

from __future__ import annotations

import ipaddress
import os
import secrets

from fastapi import HTTPException, Request, status
from fastapi.security.utils import get_authorization_scheme_param

from src.core.auth.trusted_network import get_client_ip, is_ip_in_allowed_cidrs


def is_production() -> bool:
    return os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).lower() == "production"


def docs_allowed_by_ip(request: Request) -> bool:
    if request.client is None:
        return False
    ip = get_client_ip(request)
    if not ip:
        return False
    return is_ip_in_allowed_cidrs(ip, "DOCS_ALLOWED_CIDRS", ())


def docs_basic_auth_ok(request: Request) -> bool:
    expected_user = os.getenv("DOCS_BASIC_AUTH_USER", "")
    expected_password = os.getenv("DOCS_BASIC_AUTH_PASSWORD", "")
    if not expected_user or not expected_password:
        return False
    scheme, param = get_authorization_scheme_param(request.headers.get("authorization"))
    if scheme.lower() != "basic" or not param:
        return False
    import base64

    try:
        decoded = base64.b64decode(param).decode("utf-8")
    except Exception:
        return False
    username, _, password = decoded.partition(":")
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(password, expected_password)


def require_docs_access(request: Request) -> None:
    if not is_production():
        return
    if docs_allowed_by_ip(request) or docs_basic_auth_ok(request):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Documentazione API protetta",
        headers={"WWW-Authenticate": "Basic"},
    )
