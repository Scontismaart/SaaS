import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth.dependencies import get_organization_context


class MockTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockConnection:
    def __init__(self, fetchrow_data=None, fetch_data=None, fetchval_data=None):
        self.fetchrow_data = fetchrow_data or {}
        self.fetch_data = fetch_data or []
        self.fetchval_data = fetchval_data
        self.executed = []

    def transaction(self):
        return MockTransaction()

    async def fetchrow(self, query, *args):
        for q_sub, result in self.fetchrow_data.items():
            if q_sub in query:
                if callable(result):
                    return await result(*args) if hasattr(result, "__await__") else result(*args)
                return result
        return None

    async def fetch(self, query, *args):
        return self.fetch_data

    async def fetchval(self, query, *args):
        return self.fetchval_data

    async def execute(self, query, *args):
        self.executed.append((query, args))
        return "EXECUTE 1"


class MockPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        class _AcquireContext:
            def __init__(self, conn):
                self.conn = conn
            async def __aenter__(self):
                return self.conn
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
        return _AcquireContext(self._conn)


@pytest.fixture
def client():
    return TestClient(app)


def test_get_team_members_unauthorized(client):
    resp = client.get("/api/team/members")
    assert resp.status_code == 401


def test_get_team_members_trial_pro_limits(client):
    test_org_id = str(uuid.uuid4())
    test_user_id = str(uuid.uuid4())

    mock_conn = MockConnection(
        fetchrow_data={
            "SELECT plan, users_limit, subscription_status FROM organizations": {
                "plan": None,
                "users_limit": None,
                "subscription_status": "trialing",
            }
        },
        fetch_data=[
            {
                "id": uuid.uuid4(),
                "user_id": uuid.UUID(test_user_id),
                "nome": "Owner Test",
                "email": "owner@azienda.it",
                "ruolo": "owner",
                "joined_at": None,
            }
        ],
    )
    app.state.pool = MockPool(mock_conn)

    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": test_org_id,
        "ruolo": "owner",
        "source": "jwt",
        "user_id": test_user_id,
    }

    try:
        resp = client.get("/api/team/members")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["users_limit"] == 3  # In trial defaults to Pro = 3!
        assert data["can_add_more"] is True
        assert len(data["members"]) == 1
        assert data["members"][0]["email"] == "owner@azienda.it"
    finally:
        app.dependency_overrides.clear()


def test_post_team_member_invalid_email(client):
    test_org_id = str(uuid.uuid4())
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": test_org_id,
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.post("/api/team/members", json={"email": "invalid-email", "ruolo": "staff"})
        assert resp.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_post_team_member_manager_cannot_invite_manager(client):
    test_org_id = str(uuid.uuid4())
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": test_org_id,
        "ruolo": "manager",
        "source": "jwt",
    }
    try:
        resp = client.post("/api/team/members", json={"email": "collega@azienda.it", "ruolo": "manager"})
        assert resp.status_code == 403
        assert "ruolo 'staff'" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_post_team_member_starter_limit_exceeded(client):
    test_org_id = str(uuid.uuid4())
    mock_conn = MockConnection(
        fetchrow_data={
            "SELECT plan, users_limit, subscription_status FROM organizations": {
                "plan": "starter",
                "users_limit": 1,
                "subscription_status": "active",
            }
        },
        fetchval_data=1,
    )
    app.state.pool = MockPool(mock_conn)

    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": test_org_id,
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.post("/api/team/members", json={"email": "collega@azienda.it", "ruolo": "staff"})
        assert resp.status_code == 403
        assert "Limite utenti raggiunto per il piano Essenziale" in resp.json()["detail"]
        assert "Crescita (fino a 3 utenti)" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_delete_team_member_owner_protected(client):
    test_org_id = str(uuid.uuid4())
    owner_user_id = str(uuid.uuid4())

    mock_conn = MockConnection(
        fetchrow_data={
            "SELECT om.id, om.ruolo, up.email": {
                "id": uuid.uuid4(),
                "ruolo": "owner",
                "email": "owner@azienda.it",
            }
        }
    )
    app.state.pool = MockPool(mock_conn)

    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": test_org_id,
        "ruolo": "owner",
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
    }
    try:
        resp = client.delete(f"/api/team/members/{owner_user_id}")
        assert resp.status_code == 400
        assert "proprietario" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
