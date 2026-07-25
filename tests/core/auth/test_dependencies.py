import uuid
import pytest
from unittest.mock import AsyncMock
from fastapi import HTTPException

from src.core.auth.dependencies import (
    get_token,
    get_current_user,
    get_organization_context,
    require_ruolo,
    get_repo,
)


class TestGetToken:
    async def test_no_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_token(authorization=None, x_api_key=None)
        assert exc.value.status_code == 401

    async def test_bearer_token_extracted(self):
        result = await get_token(authorization="Bearer my.jwt.token", x_api_key=None)
        assert result == "my.jwt.token"

    async def test_api_key_prefixed(self):
        result = await get_token(authorization=None, x_api_key="sk-test-123")
        assert result == "apikey:sk-test-123"


class TestGetCurrentUser:
    async def test_valid_api_key_returns_service_role(self, monkeypatch):
        monkeypatch.setenv("API_KEY_SERVICE", "sk-test-key")
        result = await get_current_user(token="apikey:sk-test-key")
        assert result["ruolo"] == "service_role"
        assert result["source"] == "api_key"

    async def test_invalid_api_key_raises_403(self, monkeypatch):
        monkeypatch.setenv("API_KEY_SERVICE", "sk-real-key")
        with pytest.raises(HTTPException) as exc:
            await get_current_user(token="apikey:sk-wrong-key")
        assert exc.value.status_code == 403


def _fake_request(repo=None):
    class FakeRequest:
        app = type("App", (), {"state": type("State", (), {"repo": repo})()})()
    return FakeRequest()


class TestGetOrganizationContext:
    async def test_api_key_returns_as_is(self):
        user = {"source": "api_key", "ruolo": "service_role"}
        result = await get_organization_context(
            request=_fake_request(),
            current_user=user,
            x_organization_id="org-123",
        )
        assert result["organization_id"] == "org-123"
        assert result["source"] == "api_key"

    async def test_no_org_id_returns_unchanged(self):
        user = {"source": "jwt", "auth_user_id": str(uuid.uuid4()), "ruolo": None}
        result = await get_organization_context(
            request=_fake_request(),
            current_user=user,
            x_organization_id=None,
        )
        assert result == user

    async def test_valid_membership_returns_role(self):
        org_id = str(uuid.uuid4())
        auth_user_id = str(uuid.uuid4())
        mock_repo = AsyncMock()
        mock_repo.get_membership_by_auth.return_value = {"ruolo": "manager", "organization_id": org_id, "user_id": str(uuid.uuid4())}
        user = {"source": "jwt", "auth_user_id": auth_user_id, "ruolo": None}
        result = await get_organization_context(
            request=_fake_request(repo=mock_repo),
            current_user=user,
            x_organization_id=org_id,
        )
        assert result["ruolo"] == "manager"
        assert result["organization_id"] == org_id
        mock_repo.get_membership_by_auth.assert_awaited_once_with(auth_user_id, org_id)

    async def test_no_membership_raises_403(self):
        mock_repo = AsyncMock()
        mock_repo.get_membership_by_auth.return_value = None
        user = {"source": "jwt", "auth_user_id": str(uuid.uuid4()), "ruolo": None}
        with pytest.raises(HTTPException) as exc:
            await get_organization_context(
                request=_fake_request(repo=mock_repo),
                current_user=user,
                x_organization_id=str(uuid.uuid4()),
            )
        assert exc.value.status_code == 403


class TestGetRepo:
    def test_missing_repo_raises_500(self):
        class FakeRequest:
            app = type("App", (), {"state": type("State", (), {"repo": None})()})()
        with pytest.raises(HTTPException) as exc:
            get_repo(FakeRequest())
        assert exc.value.status_code == 500


class TestRequireRuolo:
    async def test_owner_allowed_when_admin(self):
        async def dummy_dep():
            return {"ruolo": "owner", "organization_id": str(uuid.uuid4())}
        check = require_ruolo("owner", "manager")
        result = await check(user=await dummy_dep())
        assert result["ruolo"] == "owner"

    async def test_staff_blocked_from_admin(self):
        async def dummy_dep():
            return {"ruolo": "staff", "organization_id": str(uuid.uuid4())}
        check = require_ruolo("owner", "manager")
        with pytest.raises(HTTPException) as exc:
            await check(user=await dummy_dep())
        assert exc.value.status_code == 403

    async def test_service_role_bypasses_check(self):
        async def dummy_dep():
            return {"ruolo": None, "source": "api_key"}
        check = require_ruolo("owner")
        result = await check(user=await dummy_dep())
        assert result["source"] == "api_key"
