"""Persistenza del refresh/token lifecycle per Apaleo e Beds24.

Verifica che dopo un refresh riuscito il nuovo token/state sia:
1. utilizzabile immediatamente (in-memory);
2. persistito cifrato via repository esistente (update_credential_fields);
3. ancora valido dopo un restart simulato (nuovo adapter dalle creds persistite);
4. mai corrotto da due refresh concorrenti (single HTTP request);
5. mai persistito in caso di refresh failure; mai loggato in chiaro.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=")

from src.core.bookings.adapters.apaleo_adapter import ApaleoAdapter
from src.core.bookings.adapters.apaleo_auth import (
    ApaleoInvalidGrantError,
    ApaleoOAuthClient,
)
from src.core.bookings.adapters.beds24_adapter import Beds24Adapter
from src.core.bookings.router import BookingAdapterRouter

ORG = uuid.UUID("44444444-4444-4444-4444-444444444444")


class FakeCredRepo:
    """Envelope store in-memory con semantica di merge di update_credential_fields."""

    def __init__(self, provider: str, envelope: dict, config: dict | None = None):
        self._envelope = dict(envelope)
        self._provider = provider
        self._config = config or {"mode": "authoritative"}
        self.persist_calls: list[dict] = []

    async def get_credentials(self, organization_id):
        flat = dict(self._envelope)
        return {
            "organization_id": organization_id,
            "provider": self._provider,
            "is_active": True,
            "config": dict(self._config),
            "credentials": dict(self._envelope),
            **flat,
        }

    async def update_credential_fields(self, organization_id, fields: dict):
        assert str(organization_id) == str(ORG)
        self._envelope.update({k: v for k, v in fields.items() if v is not None})
        self.persist_calls.append(dict(fields))
        return {"organization_id": organization_id}


def _apaleo_token_handler(calls: list, access="tok_new_access_001", refresh="tok_new_refresh_002"):
    def handler(request: httpx.Request):
        calls.append(request)
        return httpx.Response(200, json={
            "access_token": access, "expires_in": 3600,
            "refresh_token": refresh, "token_type": "Bearer",
        })
    return handler


class TestApaleoRefreshPersistence:
    @pytest.mark.asyncio
    async def test_valid_token_no_http_no_persist(self):
        calls: list = []
        persisted: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(_apaleo_token_handler(calls)))
        auth = ApaleoOAuthClient(
            organization_id=ORG, client_id="cid", client_secret="csec",
            refresh_token="tok_old_refresh",
            initial_access_token="tok_valid_cached", initial_expires_at=time.time() + 1800,
            client=client, on_token_refreshed=lambda u: persisted.append(u),
        )
        assert await auth.get_access_token() == "tok_valid_cached"
        assert calls == [] and persisted == []

    @pytest.mark.asyncio
    async def test_expired_refresh_persists_and_immediate_use(self):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _apaleo_token_handler(calls)))
        repo = FakeCredRepo("apaleo", {
            "client_id": "cid", "client_secret": "csec",
            "refresh_token": "tok_old_refresh", "property_id": "P1",
        })
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        assert isinstance(adapter, ApaleoAdapter)
        adapter._client = client
        adapter.auth._client = client

        token = await adapter.auth.get_access_token()
        assert token == "tok_new_access_001"
        assert len(calls) == 1
        # Callback persistita con refresh ruotato
        assert len(repo.persist_calls) == 1
        assert repo._envelope["refresh_token"] == "tok_new_refresh_002"
        assert repo._envelope["access_token"] == "tok_new_access_001"
        # Uso immediato: seconda chiamata senza HTTP
        assert await adapter.auth.get_access_token() == "tok_new_access_001"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_restart_uses_persisted_credentials(self):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _apaleo_token_handler(calls)))
        repo = FakeCredRepo("apaleo", {
            "client_id": "cid", "client_secret": "csec",
            "refresh_token": "tok_old_refresh", "property_id": "P1",
        })
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        adapter._client = client
        adapter.auth._client = client
        await adapter.auth.get_access_token()
        assert len(calls) == 1

        # Restart simulato: nuovo router/adapter dalle creds persistite, HTTP vietato
        def _no_http(request: httpx.Request):  # pragma: no cover
            raise AssertionError("nessuna chiamata HTTP attesa dopo restart")
        router2 = BookingAdapterRouter(repo=repo)
        adapter2, _, _ = await router2.resolve_adapter(ORG)
        adapter2._client = httpx.AsyncClient(transport=httpx.MockTransport(_no_http))
        adapter2.auth._client = adapter2._client
        assert await adapter2.auth.get_access_token() == "tok_new_access_001"

    @pytest.mark.asyncio
    async def test_concurrent_refresh_single_http_single_persist(self):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _apaleo_token_handler(calls)))
        repo = FakeCredRepo("apaleo", {
            "client_id": "cid", "client_secret": "csec",
            "refresh_token": "tok_old_refresh", "property_id": "P1",
        })
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        adapter._client = client
        adapter.auth._client = client

        tokens = await asyncio.gather(*[adapter.auth.get_access_token() for _ in range(5)])
        assert set(tokens) == {"tok_new_access_001"}
        assert len(calls) == 1
        assert len(repo.persist_calls) == 1

    @pytest.mark.asyncio
    async def test_invalid_grant_no_persist_invalidated(self):
        def handler(request: httpx.Request):
            return httpx.Response(400, json={
                "error": "invalid_grant", "error_description": "revoked"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        persisted: list = []
        auth = ApaleoOAuthClient(
            organization_id=ORG, client_id="cid", client_secret="csec",
            refresh_token="tok_revoked", client=client,
            on_token_refreshed=lambda u: persisted.append(u),
        )
        with pytest.raises(ApaleoInvalidGrantError):
            await auth.get_access_token()
        assert persisted == []

    @pytest.mark.asyncio
    async def test_router_wires_callback(self):
        repo = FakeCredRepo("apaleo", {
            "client_id": "cid", "client_secret": "csec",
            "refresh_token": "tok_old_refresh",
        })
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        assert adapter.auth._on_token_refreshed is not None


def _beds24_token_handler(calls: list, token="tok_beds_new_001"):
    def handler(request: httpx.Request):
        calls.append(request)
        assert request.url.path == "/v2/authentication/token"
        return httpx.Response(200, json={
            "token": token, "expiresIn": 7200, "tokenType": "Bearer"})
    return handler


class TestBeds24RefreshPersistence:
    @pytest.mark.asyncio
    async def test_valid_token_no_http_no_persist(self):
        calls: list = []
        persisted: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(_beds24_token_handler(calls)))
        adapter = Beds24Adapter(
            organization_id=ORG, token="tok_static_valid", client=client,
            on_token_refreshed=lambda u: persisted.append(u),
        )
        assert await adapter._get_access_token() == "tok_static_valid"
        assert calls == [] and persisted == []

    @pytest.mark.asyncio
    async def test_expired_refresh_persists_and_immediate_use(self):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _beds24_token_handler(calls)))
        repo = FakeCredRepo("beds24", {
            "refresh_token": "tok_beds_refresh_old", "property_id": "7",
        })
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        assert isinstance(adapter, Beds24Adapter)
        adapter._client = client

        token = await adapter._get_access_token()
        assert token == "tok_beds_new_001"
        assert len(calls) == 1
        assert len(repo.persist_calls) == 1
        assert repo._envelope["token"] == "tok_beds_new_001"
        assert repo._envelope["refresh_token"] == "tok_beds_refresh_old"
        assert await adapter._get_access_token() == "tok_beds_new_001"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_restart_uses_persisted_token(self):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _beds24_token_handler(calls)))
        repo = FakeCredRepo("beds24", {"refresh_token": "tok_beds_refresh_old"})
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        adapter._client = client
        await adapter._get_access_token()

        def _no_http(request: httpx.Request):  # pragma: no cover
            raise AssertionError("nessuna chiamata HTTP attesa dopo restart")
        router2 = BookingAdapterRouter(repo=repo)
        adapter2, _, _ = await router2.resolve_adapter(ORG)
        adapter2._client = httpx.AsyncClient(transport=httpx.MockTransport(_no_http))
        assert await adapter2._get_access_token() == "tok_beds_new_001"

    @pytest.mark.asyncio
    async def test_invite_code_setup_persists(self):
        def handler(request: httpx.Request):
            assert request.url.path == "/v2/authentication/setup"
            return httpx.Response(200, json={
                "token": "tok_beds_setup_001", "refreshToken": "tok_beds_setup_ref",
                "expiresIn": 3600})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        repo = FakeCredRepo("beds24", {"invite_code": "INV-123"})
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        adapter._client = client

        assert await adapter._get_access_token() == "tok_beds_setup_001"
        assert repo._envelope["token"] == "tok_beds_setup_001"
        assert repo._envelope["refresh_token"] == "tok_beds_setup_ref"

    @pytest.mark.asyncio
    async def test_refresh_failure_no_persist(self):
        def handler(request: httpx.Request):
            return httpx.Response(401, json={"error": "unauthorized"})
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        persisted: list = []
        adapter = Beds24Adapter(
            organization_id=ORG, refresh_token="tok_beds_bad", client=client,
            on_token_refreshed=lambda u: persisted.append(u),
        )
        from src.core.bookings.adapters.beds24_adapter import Beds24AuthError
        with pytest.raises(Beds24AuthError):
            await adapter._get_access_token()
        assert persisted == []

    @pytest.mark.asyncio
    async def test_concurrent_refresh_single_http(self):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _beds24_token_handler(calls)))
        adapter = Beds24Adapter(
            organization_id=ORG, refresh_token="tok_beds_refresh_old", client=client,
            on_token_refreshed=AsyncMock(),
        )
        tokens = await asyncio.gather(*[adapter._get_access_token() for _ in range(5)])
        assert set(tokens) == {"tok_beds_new_001"}
        assert len(calls) == 1
        adapter._on_token_refreshed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_router_wires_callback(self):
        repo = FakeCredRepo("beds24", {"refresh_token": "tok_beds_refresh_old"})
        router = BookingAdapterRouter(repo=repo)
        adapter, _, _ = await router.resolve_adapter(ORG)
        assert adapter._on_token_refreshed is not None


class TestRepoUpdateCredentialFields:
    @pytest.mark.asyncio
    async def test_merge_encrypts_and_scopes_by_org(self, monkeypatch):
        from cryptography.fernet import Fernet

        from src.core.db.repositories.external_booking_repo import ExternalBookingRepository

        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

        captured: dict = {}
        stored = {
            "organization_id": ORG, "provider": "apaleo",
            "credentials_encrypted": ExternalBookingRepository.encrypt_credentials({
                "client_id": "cid", "client_secret": "csec",
                "refresh_token": "tok_old", "property_id": "P1",
            }),
            "config": {"mode": "authoritative"}, "is_active": True,
        }

        async def _fetchrow(query, *args):
            captured["query"] = query
            captured["args"] = args
            if query.lstrip().startswith("SELECT"):
                return dict(stored)
            assert "WHERE organization_id = $1" in query
            stored["credentials_encrypted"] = args[1]
            return dict(stored)

        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(side_effect=_fetchrow)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = ExternalBookingRepository(pool=mock_pool)
        out = await repo.update_credential_fields(ORG, {
            "access_token": "tok_AT_REST", "refresh_token": "tok_ROTATED",
        })

        assert "WHERE organization_id = $1" in captured["query"]
        blob = stored["credentials_encrypted"]
        assert "tok_AT_REST" not in blob and "tok_ROTATED" not in blob
        merged = ExternalBookingRepository.decrypt_credentials(blob)
        assert merged["access_token"] == "tok_AT_REST"
        assert merged["refresh_token"] == "tok_ROTATED"
        assert merged["client_secret"] == "csec"  # preservato
        assert merged["property_id"] == "P1"  # preservato
        assert out["refresh_token"] == "tok_ROTATED"

    @pytest.mark.asyncio
    async def test_no_row_returns_none(self, monkeypatch):
        from cryptography.fernet import Fernet

        from src.core.db.repositories.external_booking_repo import ExternalBookingRepository

        monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        repo = ExternalBookingRepository(pool=mock_pool)
        assert await repo.update_credential_fields(ORG, {"token": "x"}) is None


class TestNoSecretLogging:
    @pytest.mark.asyncio
    async def test_refresh_logs_contain_no_secrets(self, caplog):
        calls: list = []
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            _apaleo_token_handler(calls, access="tok_secret_AAA", refresh="tok_secret_BBB")))
        auth = ApaleoOAuthClient(
            organization_id=ORG, client_id="cid", client_secret="csec_topsecret",
            refresh_token="tok_secret_OLD", client=client,
            on_token_refreshed=AsyncMock(),
        )
        with caplog.at_level(logging.INFO, logger="src.core.bookings.adapters.apaleo_auth"):
            await auth.get_access_token()
        text = caplog.text
        for secret in ("tok_secret_AAA", "tok_secret_BBB", "tok_secret_OLD", "csec_topsecret"):
            assert secret not in text
