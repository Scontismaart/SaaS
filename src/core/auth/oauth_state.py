"""Session-bound Google integration nonces stored in the existing nonce table."""

import base64
import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi import Depends, Header, HTTPException, Query, Request

from src.core.auth import bff, dependencies

_NONCE_RE = re.compile(r"[0-9a-f]{32}\.[0-9a-f]{64}")
_PURPOSE = b"melpis/google-integration-oauth/session-binding/v1"


async def oauth_start_owner(
    request: Request,
    user: dict = Depends(dependencies.get_current_user),
    organization_id: UUID | None = Query(None),
    x_organization_id: str | None = Header(None),
) -> dict:
    """A navigation cannot send custom headers; selectors never grant access."""
    selected = str(organization_id) if organization_id else None
    if x_organization_id:
        try:
            header_org = str(UUID(x_organization_id))
        except ValueError:
            raise HTTPException(400, "Organizzazione non valida") from None
        if selected and selected != header_org:
            raise HTTPException(403, "Organizzazione non coerente")
        selected = header_org
    if selected:
        membership = await dependencies.get_repo(request).get_membership_by_auth(
            user["auth_user_id"], selected,
        )
        if not membership or str(membership.get("organization_id")) != selected:
            raise HTTPException(403, "Non sei membro di questa organizzazione")
        context = {**user, "organization_id": selected, "ruolo": membership.get("ruolo"),
                   "user_id": str(membership["user_id"])}
    else:
        context = await dependencies.get_organization_context(request, current_user=user, x_organization_id=None)
    return await dependencies.require_ruolo("owner")(context)


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


def oauth_pkce_verifier(channel: str, organization_id: str, nonce: str) -> str:
    """Recover PKCE across SDK instances without exposing/storing the verifier."""
    if not is_bound_oauth_nonce(nonce):
        raise HTTPException(400, "Stato OAuth non valido")
    context = json.dumps(["melpis/google-integration-oauth/pkce/v1", channel,
                          str(organization_id), nonce], separators=(",", ":")).encode()
    digest = hmac.digest(_binding_key(), context, hashlib.sha256)
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


async def exchange_google_oauth_token(flow, code: str, required_scopes: list[str]) -> None:
    """Accept an already-validated SDK token only if required grants remain."""
    try:
        await asyncio.to_thread(flow.fetch_token, code=code)
    except Warning as scope_change:
        # OAuthlib validates the token before raising this specific scope-change
        # warning. Do not relax token-scope validation globally or catch other
        # provider errors. Additional grants never confer application privileges.
        token = getattr(scope_change, "token", None)
        old = getattr(scope_change, "old_scope", None)
        granted = getattr(scope_change, "new_scope", None)
        expected = set(required_scopes)
        if (
            type(scope_change) is not Warning or not isinstance(token, dict)
            or not isinstance(old, (list, tuple, set))
            or not isinstance(granted, (list, tuple, set))
            or not all(isinstance(item, str) for item in [*old, *granted])
            or set(old) != expected or not expected.issubset(set(granted))
        ):
            raise
        flow.oauth2session.token = token
    # Runtime SDK flags must not weaken the application's required grants.
    token = flow.oauth2session.token
    if not isinstance(token, dict):
        raise ValueError("Invalid Google OAuth token response")
    # RFC 6749 permits omitting scope only when identical to the request.
    granted = token.get("scope", required_scopes)
    if isinstance(granted, str):
        granted = granted.split()
    if (
        not isinstance(granted, (list, tuple, set))
        or not all(isinstance(item, str) for item in granted)
        or not set(required_scopes).issubset(set(granted))
    ):
        raise ValueError("Required Google OAuth grant missing")


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
