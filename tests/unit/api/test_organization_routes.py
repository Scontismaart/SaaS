import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth.dependencies import get_organization_context


@pytest.fixture
def client():
    mock_repo = MagicMock()
    app.state.repo = mock_repo
    return TestClient(app)


def test_onboarding_verticali_unauthorized(client):
    resp = client.get("/api/onboarding/verticali")
    assert resp.status_code == 401


def test_onboarding_verticali_authorized(client):
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": "org-test-123",
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.get("/api/onboarding/verticali")
        assert resp.status_code == 200
        data = resp.json()
        assert "verticali" in data
        assert "lingue_disponibili" in data
        assert "ristorazione" in data["verticali"] or len(data["verticali"]) > 0
    finally:
        app.dependency_overrides.clear()


def test_put_impostazioni_organizzazione_invalid_timezone(client):
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": "00000000-0000-0000-0000-000000000001",
        "ruolo": "owner",
        "source": "jwt",
    }
    try:
        resp = client.put(
            "/api/impostazioni/organizzazione",
            json={"timezone": "Invalid/Timezone_Not_Existing"},
        )
        assert resp.status_code == 422
        assert "fuso orario non valido" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()
