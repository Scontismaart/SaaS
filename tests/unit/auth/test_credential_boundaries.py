"""Offline regression tests: owner+MFA and provider verification are mandatory."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.core.auth.dependencies import get_current_user, get_organization_context


@pytest.fixture(autouse=True)
def enable_google_integrations(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALENDAR_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_BUSINESS_ENABLED", "true")


@pytest.mark.parametrize("role,aal", [("manager", "aal2"), ("staff", "aal2"), ("owner", "aal1")])
@pytest.mark.parametrize("channel", ["whatsapp", "instagram"])
def test_channel_credentials_require_owner_mfa(role, aal, channel):
    from src.whatsapp.routes import router as wa
    from src.instagram.routes import router as ig
    app = FastAPI()
    app.include_router(wa)
    app.include_router(ig)
    identity = {"source": "jwt", "organization_id": "org-1", "ruolo": role, "aal": aal}
    app.dependency_overrides[get_current_user] = lambda: identity
    app.dependency_overrides[get_organization_context] = lambda: identity
    response = TestClient(app).delete(f"/api/{channel}/account")
    assert response.status_code == 403


@pytest.mark.parametrize(
    "router_name,method,path,payload",
    [
        ("whatsapp", "post", "/api/whatsapp/account", {
            "phone_number_id": "123", "waba_id": "456", "access_token": "secret",
        }),
        ("instagram", "post", "/api/instagram/account", {
            "ig_user_id": "123", "access_token": "secret",
        }),
        ("calendar", "get", "/api/calendar/auth", None),
        ("reviews", "get", "/api/reviews/google/auth", None),
        ("airtable", "post", "/api/v1/integrations/airtable/connect", {
            "token": "pat-secret", "base_id": "app123", "base_name": "Test",
        }),
        ("booking", "post", "/api/v1/integrations/booking", {
            "provider": "simplybook", "credentials": {"api_key": "secret"},
        }),
    ],
)
@pytest.mark.parametrize("role,aal", [("manager", "aal2"), ("owner", "aal1")])
def test_all_credential_writes_require_owner_and_mfa(
    router_name, method, path, payload, role, aal, monkeypatch, tmp_path,
):
    monkeypatch.setenv("CREWAI_STORAGE_DIR", str(tmp_path / "crewai"))
    from src.api.routes.airtable import router as airtable_router
    from src.api.routes.integrations import router as integrations_router
    from src.core.calendar.routes import router as calendar_router
    from src.core.reviews.google_routes import router as reviews_router
    from src.instagram.routes import router as instagram_router
    from src.whatsapp.routes import router as whatsapp_router

    routers = {
        "whatsapp": whatsapp_router,
        "instagram": instagram_router,
        "calendar": calendar_router,
        "reviews": reviews_router,
        "airtable": airtable_router,
        "booking": integrations_router,
    }
    identity = {
        "source": "jwt", "organization_id": "org-1", "ruolo": role, "aal": aal,
    }
    app = FastAPI()
    app.include_router(routers[router_name])
    app.dependency_overrides[get_current_user] = lambda: identity
    app.dependency_overrides[get_organization_context] = lambda: identity
    response = TestClient(app).request(method, path, json=payload)
    assert response.status_code == 403


def test_service_api_key_cannot_reach_user_credential_route(monkeypatch):
    from src.instagram.routes import router

    monkeypatch.setenv("API_KEY_SERVICE", "service-secret")
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).post(
        "/api/instagram/account",
        headers={"X-API-Key": "service-secret"},
        json={"ig_user_id": "123", "access_token": "credential"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("result", [503, 429, "timeout", "malformed", "wrong_account"])
async def test_whatsapp_validation_failure_never_saves(monkeypatch, result):
    import src.whatsapp.routes as routes
    repo = MagicMock()
    repo.save_tenant_config = AsyncMock()
    monkeypatch.setattr(routes, "_get_wrepo", lambda request: repo)
    client = MagicMock()
    if result == "timeout":
        client.get = AsyncMock(side_effect=httpx.TimeoutException("private-token"))
    elif result == "wrong_account":
        client.get = AsyncMock(side_effect=[httpx.Response(200, json={"id": "123"}), httpx.Response(200, json={"data": [{"id": "other"}]})])
    else:
        response = httpx.Response(200, json={}) if result == "malformed" else httpx.Response(result)
        client.get = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(routes.httpx, "AsyncClient", lambda **kwargs: context)
    with pytest.raises(HTTPException) as exc:
        await routes.connect_whatsapp_account(
            routes.WhatsAppAccountRequest(phone_number_id="123", waba_id="456", access_token="private-token"),
            SimpleNamespace(), user={"organization_id": "org-1"}, mfa={},
        )
    assert exc.value.status_code in (400, 503)
    assert "private-token" not in exc.value.detail
    repo.save_tenant_config.assert_not_awaited()


async def test_whatsapp_test_send_denies_non_allowlisted_recipient(monkeypatch):
    import src.whatsapp.routes as routes

    monkeypatch.setenv("SANDBOX_ONLY", "true")
    monkeypatch.setenv("WHATSAPP_TEST_RECIPIENTS", "39000000000")
    repo = MagicMock()
    repo.get_tenant_config = AsyncMock(return_value={
        "access_token": "encrypted-token",
        "phone_number_id": "123456",
    })
    repo.decrypt_token.return_value = "private-token"
    monkeypatch.setattr(routes, "_get_wrepo", lambda request: repo)

    class NoNetwork:
        def __init__(self, **kwargs):
            raise AssertionError("network client must not be created")

    monkeypatch.setattr(routes.httpx, "AsyncClient", NoNetwork)
    with pytest.raises(HTTPException) as exc:
        await routes.send_test_message(
            routes.WhatsAppTestMessageRequest(to_phone="+39000000001"),
            SimpleNamespace(),
            user={"organization_id": "org-1"},
        )
    assert exc.value.status_code == 403
    assert "39000000001" not in exc.value.detail


async def test_whatsapp_test_send_allows_explicit_sandbox_recipient(monkeypatch):
    import src.whatsapp.routes as routes

    monkeypatch.setenv("SANDBOX_ONLY", "true")
    monkeypatch.setenv("WHATSAPP_TEST_RECIPIENTS", "39000000000")
    repo = MagicMock()
    repo.get_tenant_config = AsyncMock(return_value={
        "access_token": "encrypted-token",
        "phone_number_id": "123456",
    })
    repo.decrypt_token.return_value = "private-token"
    monkeypatch.setattr(routes, "_get_wrepo", lambda request: repo)

    client = MagicMock()
    client.post = AsyncMock(return_value=httpx.Response(
        200,
        json={"messages": [{"id": "wamid.test"}]},
        request=httpx.Request("POST", "https://graph.facebook.test/messages"),
    ))
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(routes.httpx, "AsyncClient", lambda **kwargs: context)

    result = await routes.send_test_message(
        routes.WhatsAppTestMessageRequest(to_phone="+39000000000"),
        SimpleNamespace(),
        user={"organization_id": "org-1"},
    )
    assert result["status"] == "sent"
    assert result["message_id"] == "wamid.test"
    client.post.assert_awaited_once()


@pytest.mark.parametrize("channel", ["calendar", "reviews_google"])
async def test_oauth_failure_has_safe_redirect_and_no_secret(channel, caplog):
    from src.core.auth.oauth_callback import safe_oauth_callback
    @safe_oauth_callback(channel)
    async def fails():
        raise RuntimeError("secret-token")
    result = await fails()
    assert result.headers["location"] == f"/app/?{channel}=error&reason=server_error"
    assert "secret-token" not in caplog.text


class _OneShotNonceConnection:
    def __init__(self):
        from datetime import datetime, timezone

        self.row = {"created_at": datetime.now(timezone.utc)}
        self.calls = []

    async def fetchrow(self, query, nonce, organization_id):
        self.calls.append((query, nonce, organization_id))
        row, self.row = self.row, None
        return row


class _AcquireNonceConnection:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return None


class _OneShotNoncePool:
    def __init__(self):
        self.connection = _OneShotNonceConnection()

    def acquire(self):
        return _AcquireNonceConnection(self.connection)


@pytest.mark.parametrize(
    "callback,channel",
    [
        ("calendar", "calendar"),
        ("reviews", "reviews_google"),
    ],
)
async def test_oauth_provider_denial_consumes_nonce_once(callback, channel, caplog, monkeypatch):
    if callback == "calendar":
        from src.core.calendar.routes import calendar_oauth2callback as handler
    else:
        from src.core.reviews.google_routes import google_reviews_oauth2callback as handler

    org_id = "11111111-1111-1111-1111-111111111111"
    from src.core.auth import bff, dependencies
    from src.core.auth.oauth_state import create_bound_oauth_nonce

    # Deterministic 32-byte Fernet key for this isolated test.
    monkeypatch.setenv("ENCRYPTION_KEY", "A" * 43 + "=")
    user = {"source": "jwt", "aal": "aal2", "auth_user_id": "synthetic-user", "session_id": "synthetic-session"}
    monkeypatch.setattr(dependencies, "get_current_user", AsyncMock(return_value=user))
    nonce = create_bound_oauth_nonce(channel, org_id, user)
    pool = _OneShotNoncePool()
    request = SimpleNamespace(
        query_params={
            "state": f"{org_id}:{nonce}",
            "error": "private-provider-error",
        },
        cookies={bff.access_cookie_name(): "synthetic-cookie"},
        app=SimpleNamespace(state=SimpleNamespace(pool=pool, repo=SimpleNamespace(
            get_membership_by_auth=AsyncMock(return_value={"organization_id": org_id, "ruolo": "owner"}),
        ))),
    )

    denied = await handler(request)
    assert denied.headers["location"] == f"/app/?{channel}=error&reason=provider_denied"
    assert "private-provider-error" not in caplog.text
    query, used_nonce, used_org = pool.connection.calls[0]
    assert "DELETE FROM oauth_nonces" in query
    assert "RETURNING" in query
    assert (used_nonce, used_org) == (nonce, org_id)

    replay = await handler(request)
    assert replay.headers["location"] == f"/app/?{channel}=error&reason=invalid_nonce"


@pytest.mark.parametrize("callback", ["calendar", "reviews"])
async def test_oauth_rejects_malformed_nonce_before_database(callback):
    if callback == "calendar":
        from src.core.calendar.routes import calendar_oauth2callback as handler
    else:
        from src.core.reviews.google_routes import google_reviews_oauth2callback as handler

    request = SimpleNamespace(
        query_params={
            "state": "11111111-1111-1111-1111-111111111111:not-a-nonce",
            "code": "unused",
        },
        app=SimpleNamespace(state=SimpleNamespace(pool=None)),
    )
    result = await handler(request)
    assert result.headers["location"].endswith("reason=invalid_state")
