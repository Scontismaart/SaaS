"""Session-bound Google integration nonces stored in the existing nonce table."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets

from cryptography.fernet import Fernet
from fastapi import HTTPException, Request

from src.core.auth import bff, dependencies

_NONCE_RE = re.compile(r"[0-9a-f]{32}\.[0-9a-f]{64}")
_PURPOSE = b"melpis/google-integration-oauth/session-binding/v1"


def is_bound_oauth_nonce(nonce: str) -> bool:
    return _NONCE_RE.fullmatch(nonce) is not None


def _binding_key() -> bytes:
    # Reuse the key already required to store Google credentials. Derive a
    # separate MAC key; neither identity nor session ID is sent to Google.
    try:
        encoded = os.environ["ENCRYPTION_KEY"].encode("ascii")
        Fernet(encoded)
        material = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (KeyError, ValueError, UnicodeError):
        raise HTTPException(503, "Collegamento Google temporaneamente non disponibile") from None
    return hmac.digest(material, _PURPOSE, hashlib.sha256)


def _has_verified_session(user: dict | None) -> bool:
    return bool(
        user
        and user.get("source") == "jwt"
        and user.get("aal") == "aal2"
        and isinstance(user.get("auth_user_id"), str) and user["auth_user_id"]
        and isinstance(user.get("session_id"), str) and user["session_id"]
    )


def _proof(channel: str, organization_id: str, user: dict, random: str) -> str:
    context = json.dumps(
        ["v1", channel, str(organization_id), user["auth_user_id"], user["session_id"], random],
        separators=(",", ":"),
    ).encode("utf-8")
    return hmac.new(_binding_key(), context, hashlib.sha256).hexdigest()


def create_bound_oauth_nonce(channel: str, organization_id: str, user: dict) -> str:
    if not _has_verified_session(user):
        raise HTTPException(403, "Sessione verificata richiesta per collegare Google")
    random = secrets.token_hex(16)
    # The exact context-bound value is persisted as the one-time DB nonce.
    return f"{random}.{_proof(channel, organization_id, user, random)}"


async def validate_oauth_callback_context(
    request: Request, channel: str, organization_id: str, nonce: str,
) -> dict | None:
    if not is_bound_oauth_nonce(nonce):
        return None
    # A top-level Google GET carries the existing SameSite=Lax BFF cookie.
    # A shared OAuth URL does not transfer that authenticated browser session.
    token = request.cookies.get(bff.access_cookie_name())
    if not token:
        return None
    try:
        user = await dependencies.get_current_user(request, token=token)
    except HTTPException:
        return None
    if not _has_verified_session(user):
        return None
    random, supplied = nonce.split(".", 1)
    if not hmac.compare_digest(supplied, _proof(channel, organization_id, user, random)):
        return None
    # Google sends no X-Organization-Id header. Authorize the exact bound org
    # through the existing membership repository, including multi-org users.
    repo = dependencies.get_repo(request)
    membership = await repo.get_membership_by_auth(user["auth_user_id"], organization_id)
    if not membership or membership.get("ruolo") != "owner":
        return None
    if str(membership.get("organization_id")) != organization_id:
        return None
    return user
