import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.receptionist.models import OrchestrationOutput
from src.models.schemas import DatiPrenotazione


@pytest.fixture
def client():
    return TestClient(app)


def test_api_messaggio_with_orchestrator(client):
    """Verifica che l'endpoint /api/messaggio deleghi correttamente a ConversationOrchestrator."""
    fake_output = OrchestrationOutput(
        response_text="Siamo aperti tutti i giorni dalle 12 alle 23.",
        richiede_umano=False,
        motivo_richiesta_umano=None,
        intent="faq",
        source="llm",
        prenotazione=None,
        disponibilita_slot=None,
    )

    with patch("src.core.receptionist.conversation_orchestrator.ConversationOrchestrator.orchestrate", new_callable=AsyncMock) as mock_orchestrate:
        mock_orchestrate.return_value = fake_output

        payload = {
            "testo": "Quali sono i vostri orari?",
            "id_conversazione": "sim-conv-001",
        }
        resp = client.post("/api/messaggio", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["risposta"] == "Siamo aperti tutti i giorni dalle 12 alle 23."
        assert data["richiede_umano"] is False
        assert data["categoria"] == "faq"
        assert data["prenotazione"] is None

        # Verifica parametri passati all'orchestrator
        assert mock_orchestrate.await_count == 1
        call_req = mock_orchestrate.await_args[0][0]
        assert call_req.text == "Quali sono i vostri orari?"
        assert call_req.conversation_id == "sim-conv-001"
        assert call_req.is_simulation is True


def test_api_messaggio_simulation_booking(client):
    """Verifica che una prenotazione simulata ritorni i dettagli di disponibilità senza creare righe DB."""
    fake_pren = DatiPrenotazione(
        nome_cliente="Mario",
        data="2026-09-15",
        ora="20:30",
        coperti=4,
    )
    fake_output = OrchestrationOutput(
        response_text="Perfetto, ho verificato la disponibilità per 4 persone.",
        richiede_umano=False,
        motivo_richiesta_umano=None,
        intent="prenotazione",
        source="llm",
        prenotazione=fake_pren,
        disponibilita_slot={"disponibile": True, "coperti_rimasti": 12},
    )

    with patch("src.core.receptionist.conversation_orchestrator.ConversationOrchestrator.orchestrate", new_callable=AsyncMock) as mock_orchestrate:
        mock_orchestrate.return_value = fake_output

        payload = {
            "testo": "Vorrei un tavolo per 4 il 15 settembre alle 20:30",
            "id_conversazione": "sim-conv-002",
        }
        resp = client.post("/api/messaggio", json=payload)
        assert resp.status_code == 200
        data = resp.json()

        assert data["risposta"] == "Perfetto, ho verificato la disponibilità per 4 persone."
        assert data["prenotazione"]["coperti"] == 4
        assert data["prenotazione"]["ora"] == "20:30"
        assert mock_orchestrate.await_args[0][0].is_simulation is True
