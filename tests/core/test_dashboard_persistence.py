import uuid
from datetime import datetime, timezone
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app, recupera_eventi_dashboard
from src.models.schemas import EventoDashboard


@pytest.mark.asyncio
async def test_recupera_eventi_dashboard_from_pool():
    org_id = str(uuid.uuid4())
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    # Simulazione righe restituite dal database
    ts1 = datetime(2026, 8, 28, 17, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 8, 28, 16, 0, 0, tzinfo=timezone.utc)
    mock_conn.fetch.return_value = [
        {
            "id": str(uuid.uuid4()),
            "tipo_evento": "messaggio",
            "timestamp": ts1,
            "priorita": "media",
            "testo_originale": "Posso prenotare un tavolo per 4?",
            "risposta_ai": "Certamente! A che ora preferite?",
            "gestito_da_ai": True,
            "dettagli": {"conversation_id": "conv-1", "status": "handled"},
        },
        {
            "id": str(uuid.uuid4()),
            "tipo_evento": "recensione",
            "timestamp": ts2,
            "priorita": "alta",
            "testo_originale": "Servizio pessimo e cibo freddo",
            "risposta_ai": "",
            "gestito_da_ai": False,
            "dettagli": {"stelle": 1, "autore": "Mario", "fonte": "Google"},
        },
    ]

    eventi = await recupera_eventi_dashboard(mock_pool, org_id)

    assert len(eventi) == 2
    assert isinstance(eventi[0], EventoDashboard)
    assert eventi[0].tipo_evento == "messaggio"
    assert eventi[0].gestito_da_ai is True
    assert eventi[0].priorita == "media"
    assert eventi[0].testo_originale == "Posso prenotare un tavolo per 4?"

    assert eventi[1].tipo_evento == "recensione"
    assert eventi[1].gestito_da_ai is False
    assert eventi[1].priorita == "alta"
    assert eventi[1].dettagli["stelle"] == 1


@pytest.mark.asyncio
async def test_recupera_eventi_dashboard_fallback_when_no_pool():
    eventi = await recupera_eventi_dashboard(None, str(uuid.uuid4()))
    assert isinstance(eventi, list)


@pytest.mark.asyncio
async def test_recupera_eventi_dashboard_error_handling():
    mock_pool = MagicMock()
    mock_pool.acquire.side_effect = Exception("DB Connection Error")

    eventi = await recupera_eventi_dashboard(mock_pool, str(uuid.uuid4()))
    assert isinstance(eventi, list)


import src.api.main as api_main


@pytest.mark.asyncio
async def test_recupera_eventi_dashboard_applica_finestra_e_limit():
    """La query deve ricevere (org, finestra_giorni, limit) e applicare
    filtro temporale + LIMIT: senza, l'endpoint scarica l'intera storia
    dell'org a ogni poll di 5 secondi."""
    org_id = str(uuid.uuid4())
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    await recupera_eventi_dashboard(mock_pool, org_id)

    args = mock_conn.fetch.call_args.args
    assert args[1] == uuid.UUID(org_id)
    assert args[2] == api_main.DASHBOARD_EVENTI_WINDOW_DAYS
    assert args[2] > 7, "la finestra server deve coprire la sparkline UI (7 giorni)"
    assert args[3] == api_main.DASHBOARD_EVENTI_MAX
    sql = args[0]
    assert sql.count("make_interval(days => $2)") == 3, \
        "il filtro temporale deve coprire tutti e 3 i rami (event_log, messages, reviews)"
    assert "LIMIT" in sql.upper(), "manca il LIMIT sul result set"


@pytest.mark.asyncio
async def test_recupera_eventi_prioritari_filtra_in_sql():
    """I prioritari devono essere filtrati/ordinati/limitati dal DB:
    l'endpoint non deve piu' rieseguire la query completa e filtrare in Python."""
    from src.api.main import recupera_eventi_prioritari

    org_id = str(uuid.uuid4())
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

    result = await recupera_eventi_prioritari(mock_pool, org_id, limite=5)

    assert result == []
    args = mock_conn.fetch.call_args.args
    assert args[1] == uuid.UUID(org_id)
    assert args[2] == api_main.DASHBOARD_EVENTI_WINDOW_DAYS
    assert args[3] == 5
    sql = args[0]
    assert "priorita <> 'bassa'" in sql
    assert "CASE" in sql and "alta" in sql, "manca l'ordinamento alta-prima"
    assert "LIMIT $3" in sql
