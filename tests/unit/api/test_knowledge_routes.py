import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth.dependencies import get_organization_context


@pytest.fixture
def client():
    return TestClient(app)


def test_conteggio_documenti_unauthorized(client):
    res = client.get("/api/documenti/conteggio")
    assert res.status_code == 401


def test_ui_summary_unauthorized(client):
    res = client.get("/api/ui/summary")
    assert res.status_code == 401


def test_conoscenza_summary_unauthorized(client):
    res = client.get("/api/conoscenza/summary")
    assert res.status_code == 401


def test_ui_summary_authorized(client):
    mock_org_id = str(uuid.uuid4())
    mock_user = {
        "user_id": str(uuid.uuid4()),
        "organization_id": mock_org_id,
        "ruolo": "staff",
        "email": "staff@example.com",
    }
    mock_repo = AsyncMock()
    mock_repo.get_ui_summary.return_value = {
        "richieste_pendenti": 2,
        "documenti_attivi": 5,
        "recensioni_da_gestire": 1,
    }

    app.dependency_overrides[get_organization_context] = lambda: mock_user
    with patch.object(app.state, "repo", mock_repo, create=True):
        res = client.get("/api/ui/summary")
        assert res.status_code == 200
        data = res.json()
        assert data["richieste_pendenti"] == 2
        mock_repo.get_ui_summary.assert_awaited_once_with(mock_org_id)
    app.dependency_overrides.pop(get_organization_context, None)


def test_chiedi_documenti_rag_blocked_by_plan(client):
    mock_org_id = str(uuid.uuid4())
    mock_user = {
        "user_id": str(uuid.uuid4()),
        "organization_id": mock_org_id,
        "ruolo": "owner",
        "email": "owner@example.com",
    }
    mock_repo = AsyncMock()
    # Plan 'starter' does not have RAG
    mock_repo.get_organization_billing.return_value = {"plan": "starter"}

    app.dependency_overrides[get_organization_context] = lambda: mock_user
    with patch.object(app.state, "repo", mock_repo, create=True):
        res = client.post("/api/documenti/chiedi", json={"domanda": "Quali sono i vostri orari?", "k": 3})
        assert res.status_code == 403
        assert "non include la Knowledge Base AI" in res.json()["detail"]
    app.dependency_overrides.pop(get_organization_context, None)


def test_carica_documento_empty_text_400(client):
    mock_user = {
        "user_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "ruolo": "owner",
        "email": "owner@example.com",
    }
    app.dependency_overrides[get_organization_context] = lambda: mock_user
    res = client.post("/api/documenti/carica", json={"nome": "Menu", "testo": "   "})
    assert res.status_code == 400
    assert "vuoto" in res.json()["detail"].lower()
    app.dependency_overrides.pop(get_organization_context, None)
