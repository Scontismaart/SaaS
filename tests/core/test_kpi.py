"""Test calcolo KPI settimanali con dati mock (no Docker)."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.analytics.kpi import (
    calcola_kpi_messaggi,
    calcola_kpi_prenotazioni,
    calcola_kpi_recensioni,
    calcola_kpi_settimanali,
)
from src.models.schemas import (
    KPIMessaggi,
    KPIPrenotazioni,
    KPIRecensioni,
    KPISettimanali,
)

ORG_ID = "org-test-001"
INIZIO = date(2026, 8, 11)
FINE = date(2026, 8, 17)


def _mock_pool(fetchrow_result):
    """Crea un mock asyncpg pool con un risultato fetchrow predefinito."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    return pool


# ── Test KPI Messaggi ──


@pytest.mark.asyncio
async def test_kpi_messaggi_base():
    """Calcolo KPI messaggi con dati normali."""
    pool = _mock_pool({
        "totale": 100,
        "gestiti_da_ai": 85,
        "escalati": 10,
        "avg_risposta_sec": 12.5,
    })

    result = await calcola_kpi_messaggi(pool, ORG_ID, INIZIO, FINE)

    assert isinstance(result, KPIMessaggi)
    assert result.totale == 100
    assert result.gestiti_da_ai == 85
    assert result.escalati_a_umano == 10
    assert result.percentuale_ai == 85.0
    assert result.tempo_medio_risposta_secondi == 12.5


@pytest.mark.asyncio
async def test_kpi_messaggi_vuoto():
    """Nessun messaggio nel periodo: tutti zero, nessun errore."""
    pool = _mock_pool({
        "totale": 0,
        "gestiti_da_ai": 0,
        "escalati": 0,
        "avg_risposta_sec": None,
    })

    result = await calcola_kpi_messaggi(pool, ORG_ID, INIZIO, FINE)

    assert result.totale == 0
    assert result.percentuale_ai == 0.0
    assert result.tempo_medio_risposta_secondi is None


@pytest.mark.asyncio
async def test_kpi_messaggi_null_coercion():
    """Valori NULL dal DB vengono convertiti in 0 (non None)."""
    pool = _mock_pool({
        "totale": None,
        "gestiti_da_ai": None,
        "escalati": None,
        "avg_risposta_sec": None,
    })

    result = await calcola_kpi_messaggi(pool, ORG_ID, INIZIO, FINE)
    assert result.totale == 0
    assert result.gestiti_da_ai == 0


# ── Test KPI Prenotazioni ──


@pytest.mark.asyncio
async def test_kpi_prenotazioni_base():
    """Calcolo KPI prenotazioni con dati normali."""
    pool = _mock_pool({
        "totale": 25,
        "confermate": 18,
        "cancellate": 3,
        "no_show": 2,
        "completate": 15,
        "da_whatsapp": 12,
    })

    result = await calcola_kpi_prenotazioni(pool, ORG_ID, INIZIO, FINE)

    assert isinstance(result, KPIPrenotazioni)
    assert result.totale == 25
    assert result.confermate == 18
    assert result.completate == 15
    assert result.da_whatsapp == 12


@pytest.mark.asyncio
async def test_kpi_prenotazioni_vuoto():
    """Nessuna prenotazione: tutti zero."""
    pool = _mock_pool({
        "totale": 0, "confermate": 0, "cancellate": 0,
        "no_show": 0, "completate": 0, "da_whatsapp": 0,
    })

    result = await calcola_kpi_prenotazioni(pool, ORG_ID, INIZIO, FINE)
    assert result.totale == 0


# ── Test KPI Recensioni ──


@pytest.mark.asyncio
async def test_kpi_recensioni_base():
    """Calcolo KPI recensioni con dati normali."""
    pool = _mock_pool({
        "totale": 10,
        "con_risposta": 8,
        "media_stelle": 4.2,
    })

    result = await calcola_kpi_recensioni(pool, ORG_ID, INIZIO, FINE)

    assert isinstance(result, KPIRecensioni)
    assert result.totale == 10
    assert result.con_risposta == 8
    assert result.percentuale_risposta == 80.0
    assert result.media_stelle == 4.2


@pytest.mark.asyncio
async def test_kpi_recensioni_senza_stelle():
    """Recensioni senza valutazione stelle: media = None."""
    pool = _mock_pool({
        "totale": 5,
        "con_risposta": 3,
        "media_stelle": None,
    })

    result = await calcola_kpi_recensioni(pool, ORG_ID, INIZIO, FINE)
    assert result.media_stelle is None
    assert result.percentuale_risposta == 60.0


# ── Test KPI Settimanali (aggregato) ──


@pytest.mark.asyncio
async def test_kpi_settimanali_completo():
    """Calcolo aggregato di tutti i KPI."""
    # Tre fetchrow successive: messaggi, prenotazioni, recensioni
    call_count = 0
    results = [
        {"totale": 100, "gestiti_da_ai": 80, "escalati": 15, "avg_risposta_sec": 30.0},
        {"totale": 20, "confermate": 15, "cancellate": 2, "no_show": 1, "completate": 12, "da_whatsapp": 8},
        {"totale": 5, "con_risposta": 4, "media_stelle": 4.5},
    ]

    conn = AsyncMock()

    async def mock_fetchrow(*args, **kwargs):
        nonlocal call_count
        result = results[call_count]
        call_count += 1
        return result

    conn.fetchrow = mock_fetchrow

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)

    result = await calcola_kpi_settimanali(pool, ORG_ID, INIZIO, FINE, nome_attivita="Ristorante Test")

    assert isinstance(result, KPISettimanali)
    assert result.periodo_inizio == "2026-08-11"
    assert result.periodo_fine == "2026-08-17"
    assert result.nome_attivita == "Ristorante Test"
    assert result.messaggi.totale == 100
    assert result.prenotazioni.totale == 20
    assert result.recensioni.totale == 5
