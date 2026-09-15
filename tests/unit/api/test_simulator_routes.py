import uuid
from datetime import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth.dependencies import get_organization_context


@pytest.fixture
def client():
    return TestClient(app)


def test_recensione_unauthorized(client):
    res = client.post("/api/recensione", json={
        "testo": "Cibo ottimo e personale gentile",
        "valutazione_stelle": 5,
        "fonte": "Google",
        "autore": "Mario Rossi",
    })
    assert res.status_code == 401


def test_messaggio_invalid_profile_404(client):
    res = client.post("/api/messaggio?profilo_id=non_existing_xyz", json={
        "testo": "Ciao, vorrei info",
        "id_conversazione": "conv-test",
    })
    assert res.status_code == 404
    assert "non trovato" in res.json()["detail"].lower()


def test_messaggio_demo_simulation(client):
    mock_orchestrator = AsyncMock()
    mock_out = MagicMock()
    mock_out.response_text = "Benvenuto alla Trattoria Da Mario!"
    mock_out.richiede_umano = False
    mock_out.motivo_richiesta_umano = None
    mock_out.intent = "saluto"
    mock_out.prenotazione = None
    mock_out.disponibilita_slot = None
    mock_out.guardrail_action = None
    mock_orchestrator.orchestrate.return_value = mock_out

    with patch.object(app.state, "orchestrator", mock_orchestrator, create=True):
        res = client.post("/api/messaggio", json={
            "testo": "Buongiorno",
            "id_conversazione": f"conv-{uuid.uuid4().hex[:8]}",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["risposta"] == "Benvenuto alla Trattoria Da Mario!"
        assert data["categoria"] == "saluto"
        assert data["richiede_umano"] is False


def test_recensione_feature_blocked_by_plan(client):
    mock_org_id = str(uuid.uuid4())
    mock_user = {
        "source": "jwt",
        "user_id": str(uuid.uuid4()),
        "organization_id": mock_org_id,
        "ruolo": "owner",
        "email": "owner@example.com",
    }
    mock_repo = AsyncMock()
    # Assume plan 'starter' does not have review feature
    mock_repo.get_organization_billing.return_value = {
        "plan": "starter", "subscription_status": "active"
    }

    app.dependency_overrides[get_organization_context] = lambda: mock_user
    with patch.object(app.state, "repo", mock_repo, create=True):
        res = client.post("/api/recensione", json={
            "testo": "Ottima cena",
            "valutazione_stelle": 5,
            "fonte": "Google",
            "autore": "Luigi",
        })
        assert res.status_code == 403
        assert "non include la gestione delle recensioni" in res.json()["detail"]
    app.dependency_overrides.pop(get_organization_context, None)


def test_messaggio_authenticated_organization(client):
    mock_org_id = str(uuid.uuid4())
    mock_user = {
        "user_id": str(uuid.uuid4()),
        "organization_id": mock_org_id,
        "ruolo": "owner",
        "email": "owner@example.com",
        "source": "jwt",
    }
    mock_repo = AsyncMock()
    mock_repo.get_organization.return_value = {
        "id": mock_org_id,
        "name": "Pizzeria Napoli",
        "business_profile": {
            "nome_attivita": "Pizzeria Napoli",
            "tipo_attivita": "ristorante",
            "citta": "Napoli",
            "indirizzo": "Via Roma 1",
            "telefono": "+39081000000",
            "orari_apertura": "Tutti i giorni 19:00 - 23:30",
        },
    }
    mock_repo.get_organization_billing.return_value = {"plan": "pro"}

    mock_orchestrator = AsyncMock()
    mock_out = MagicMock()
    mock_out.response_text = "Benvenuto a Pizzeria Napoli!"
    mock_out.richiede_umano = False
    mock_out.motivo_richiesta_umano = None
    mock_out.intent = "saluto"
    mock_out.prenotazione = None
    mock_out.disponibilita_slot = None
    mock_out.guardrail_action = None
    mock_orchestrator.orchestrate.return_value = mock_out

    app.dependency_overrides[get_organization_context] = lambda: mock_user
    with patch.object(app.state, "repo", mock_repo, create=True), \
         patch.object(app.state, "orchestrator", mock_orchestrator, create=True):
        res = client.post("/api/messaggio", json={
            "testo": "Siete aperti stasera?",
            "id_conversazione": f"conv-{uuid.uuid4().hex[:8]}",
        })
        assert res.status_code == 200
        assert res.json()["risposta"] == "Benvenuto a Pizzeria Napoli!"
        call_args = mock_orchestrator.orchestrate.call_args[0][0]
        assert call_args.organization_id == mock_org_id
        assert call_args.business_profile.nome == "Pizzeria Napoli"
        assert call_args.record_billing_usage is True
    app.dependency_overrides.pop(get_organization_context, None)
