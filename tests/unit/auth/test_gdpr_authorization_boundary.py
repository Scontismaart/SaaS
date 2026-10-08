"""Exercise the real GDPR dependency chain, without auth dependency overrides."""
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.core.auth import dependencies
from src.core.gdpr import routes


@pytest.fixture
def gdpr_app(monkeypatch):
    monkeypatch.setenv("API_KEY_SERVICE", "internal-service-secret")
    monkeypatch.setenv("DEMO_MODE", "false")
    app = FastAPI()
    app.include_router(routes.router)
    app.state.repo = AsyncMock()
    app.state.repo.get_auth_access_allowed.return_value = True
    app.state.repo.get_memberships_by_auth.return_value = [
        {"organization_id": "tenant-owned", "user_id": "owner-1", "ruolo": "owner"},
    ]
    export = AsyncMock(return_value={"organization": "tenant-owned"})
    monkeypatch.setattr(routes, "_export_tenant_data", export)
    monkeypatch.setattr(routes.token_store, "save_token", AsyncMock())
    monkeypatch.setattr(routes, "audit_log", AsyncMock())
    monkeypatch.setattr(dependencies, "is_token_revoked", AsyncMock(return_value=False))
    verify = AsyncMock(return_value={"sub": "auth-owner-1", "aal": "aal2"})
    monkeypatch.setattr(dependencies, "verify_supabase_jwt", verify)
    return app, export, verify


@pytest.mark.parametrize("org_header", [None, "tenant-owned", "tenant-victim"])
async def test_service_key_cannot_export_any_tenant(gdpr_app, org_header):
    app, export, verify = gdpr_app
    headers = {"X-API-Key": "internal-service-secret"}
    if org_header:
        headers["X-Organization-Id"] = org_header
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/gdpr/export", headers=headers)
    assert response.status_code == 403
    verify.assert_not_awaited()
    export.assert_not_awaited()
    app.state.repo.get_memberships_by_auth.assert_not_awaited()


@pytest.mark.parametrize("role,aal", [("owner", "aal1"), ("manager", "aal2"), ("staff", "aal2")])
async def test_export_requires_both_owner_membership_and_mfa(gdpr_app, role, aal):
    app, export, verify = gdpr_app
    verify.return_value = {"sub": "auth-owner-1", "aal": aal}
    app.state.repo.get_memberships_by_auth.return_value[0]["ruolo"] = role
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/gdpr/export", headers={"Authorization": "Bearer signed-user-token"})
    assert response.status_code == 403
    export.assert_not_awaited()
    if aal == "aal1":
        assert response.headers["x-mfa-required"] == "true"


async def test_export_ignores_unowned_tenant_header_for_single_membership(gdpr_app):
    app, export, _ = gdpr_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get("/api/gdpr/export", headers={
            "Authorization": "Bearer signed-user-token", "X-Organization-Id": "tenant-victim",
        })
    assert response.status_code == 200
    export.assert_awaited_once_with(app.state.repo, "tenant-owned")
    app.state.repo.get_memberships_by_auth.assert_awaited_once_with("auth-owner-1")
