import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth.dependencies import get_organization_context


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_unauthorized(client):
    res = client.get("/api/dashboard")
    assert res.status_code == 401


def test_dashboard_prioritari_unauthorized(client):
    res = client.get("/api/dashboard/prioritari")
    assert res.status_code == 401


def test_report_stato_unauthorized(client):
    res = client.get("/api/report/stato")
    assert res.status_code == 401


def test_report_settimanale_role_restriction(client):
    # 'staff' role is not allowed on /api/report/settimanale (only owner, manager)
    mock_user = {
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "ruolo": "staff",
        "email": "staff@example.com",
    }
    app.dependency_overrides[get_organization_context] = lambda: mock_user
    try:
        res = client.get("/api/report/settimanale")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_organization_context, None)


def test_report_csv_role_restriction(client):
    # 'staff' role is not allowed on /api/report/csv (only owner, manager)
    mock_user = {
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "ruolo": "staff",
        "email": "staff@example.com",
    }
    app.dependency_overrides[get_organization_context] = lambda: mock_user
    try:
        res = client.get("/api/report/csv")
        assert res.status_code == 403
    finally:
        app.dependency_overrides.pop(get_organization_context, None)


def test_dashboard_authorized_fallback_empty(client):
    mock_user = {
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "ruolo": "owner",
        "email": "owner@example.com",
    }
    app.dependency_overrides[get_organization_context] = lambda: mock_user
    try:
        res = client.get("/api/dashboard")
        assert res.status_code == 200
        assert isinstance(res.json(), list)
    finally:
        app.dependency_overrides.pop(get_organization_context, None)


def test_dashboard_prioritari_authorized(client):
    mock_user = {
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "ruolo": "manager",
        "email": "manager@example.com",
    }
    app.dependency_overrides[get_organization_context] = lambda: mock_user
    try:
        res = client.get("/api/dashboard/prioritari?limite=3")
        assert res.status_code == 200
        assert isinstance(res.json(), list)
    finally:
        app.dependency_overrides.pop(get_organization_context, None)


def test_report_stato_authorized(client):
    mock_user = {
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "ruolo": "staff",
        "email": "staff@example.com",
    }
    app.dependency_overrides[get_organization_context] = lambda: mock_user
    try:
        res = client.get("/api/report/stato")
        assert res.status_code == 200
        data = res.json()
        assert "disponibile" in data
    finally:
        app.dependency_overrides.pop(get_organization_context, None)
