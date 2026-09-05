import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth.dependencies import get_organization_context


@pytest.fixture
def client():
    mock_repo = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    
    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acquire
    mock_repo.pool = mock_pool
    
    app.state.repo = mock_repo
    app.state.pool = mock_pool
    return TestClient(app)


def test_stato_integrazioni_unauthorized(client):
    resp = client.get("/api/integrazioni/stato")
    assert resp.status_code == 401


def test_stato_integrazioni_authorized(client):
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": "00000000-0000-0000-0000-000000000001",
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.get("/api/integrazioni/stato")
        assert resp.status_code == 200
        data = resp.json()
        assert "whatsapp" in data
        assert "instagram" in data
        assert "webhook_meta" in data
        assert data["whatsapp"]["connesso"] is False
    finally:
        app.dependency_overrides.clear()


def test_test_integrazione_unsupported_channel(client):
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": "00000000-0000-0000-0000-000000000001",
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.post("/api/integrazioni/test/telegram")
        assert resp.status_code == 400
        assert "non supportato" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_audit_list_pagination(client):
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": "00000000-0000-0000-0000-000000000001",
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.get("/api/audit?limit=10&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert "eventi" in data
        assert "has_more" in data
        assert isinstance(data["eventi"], list)
    finally:
        app.dependency_overrides.clear()
