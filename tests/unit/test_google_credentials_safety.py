"""Provider transport is simulated; never contact real Google accounts."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials

from src.core.calendar.service import GoogleCalendarService
from src.core.reviews.google_service import GoogleBusinessService


@pytest.fixture(params=[GoogleCalendarService, GoogleBusinessService])
def credentials_env(request, monkeypatch):
    monkeypatch.setenv("GOOGLE_CALENDAR_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_BUSINESS_ENABLED", "true")
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    service = request.param(SimpleNamespace(pool=pool), Fernet.generate_key())
    service._get_client_config = lambda: {
        "client_id": "synthetic-client", "client_secret": "synthetic-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    rows = {
        org: {
            "access_token": service.encrypt_secret(f"access-{org}"),
            "refresh_token": service.encrypt_secret(f"refresh-{org}"),
            "token_expiry": datetime.now(timezone.utc) - timedelta(hours=1),
        } for org in ("org-a", "org-b")
    }

    async def fetch(query, org):
        assert "WHERE organization_id = $1" in query
        return rows.get(org)

    conn.fetchrow.side_effect = fetch
    return service, conn


@pytest.mark.asyncio
async def test_refresh_is_encrypted_and_updates_only_requested_tenant(credentials_env, monkeypatch):
    service, conn = credentials_env

    def refresh(creds, transport):
        assert creds.refresh_token == "refresh-org-a"
        creds.token = "refreshed-org-a"
        creds.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)

    monkeypatch.setattr(Credentials, "refresh", refresh)
    credentials = await service._get_credentials("org-a")
    assert credentials.token == "refreshed-org-a"
    query, org, encrypted, _expiry = conn.execute.await_args.args
    assert "WHERE organization_id = $1" in query
    assert org == "org-a"
    assert encrypted != "refreshed-org-a"
    assert service._decrypt(encrypted) == "refreshed-org-a"
    assert await service._get_credentials("unowned-org") is None
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_revoked_refresh_fails_closed_without_secret_logs(credentials_env, monkeypatch, caplog):
    service, conn = credentials_env

    def refresh(creds, transport):
        raise RefreshError("synthetic-sensitive-token")

    monkeypatch.setattr(Credentials, "refresh", refresh)
    assert await service._get_credentials("org-a") is None
    assert "synthetic-sensitive-token" not in caplog.text
    query, org = conn.execute.await_args.args
    assert "WHERE organization_id = $1" in query
    assert org == "org-a"
    if isinstance(service, GoogleCalendarService):
        assert "sync_enabled = false" in query


@pytest.mark.asyncio
async def test_cross_tenant_ciphertext_key_is_not_accepted(credentials_env):
    service, conn = credentials_env
    from cryptography.fernet import InvalidToken

    conn.fetchrow.side_effect = None
    conn.fetchrow.return_value = {
        "access_token": Fernet(Fernet.generate_key()).encrypt(b"other-key-token").decode(),
        "refresh_token": service.encrypt_secret("synthetic-refresh"),
        "token_expiry": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    with pytest.raises(InvalidToken):
        await service._get_credentials("org-a")
    conn.execute.assert_not_awaited()
