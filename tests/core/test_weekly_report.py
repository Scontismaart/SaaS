"""Test orchestratore report settimanale (no Docker).

Verifica idempotenza, gestione errori, calcolo periodo.
"""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.report.weekly_report import (
    _calcola_periodo_settimanale,
    _is_report_gia_inviato,
    genera_e_invia_report_settimanale,
)

# ── Test calcolo periodo ──


def test_periodo_da_martedi():
    """Se oggi e' martedi 18/8/2026 (weekday=1), il periodo e' 10/8 - 16/8."""
    inizio, fine = _calcola_periodo_settimanale(date(2026, 8, 18))
    assert inizio == date(2026, 8, 10)
    assert fine == date(2026, 8, 16)


def test_periodo_da_mercoledi():
    """Mercoledi 19/8/2026 → periodo 10/8 - 16/8."""
    inizio, fine = _calcola_periodo_settimanale(date(2026, 8, 19))
    assert inizio == date(2026, 8, 10)
    assert fine == date(2026, 8, 16)


def test_periodo_da_lunedi():
    """Lunedi 17/8/2026 → periodo 10/8 - 16/8 (la settimana scorsa)."""
    inizio, fine = _calcola_periodo_settimanale(date(2026, 8, 17))
    assert inizio == date(2026, 8, 10)
    assert fine == date(2026, 8, 16)


def test_periodo_settimana_completa():
    """Il periodo e' sempre 7 giorni (lunedi-domenica)."""
    for day_offset in range(7):
        inizio, fine = _calcola_periodo_settimanale(date(2026, 8, 18 + day_offset))
        delta = (fine - inizio).days
        assert delta == 6, f"offset {day_offset}: {inizio} - {fine} = {delta} giorni"


# ── Test idempotenza ──


@pytest.mark.asyncio
async def test_report_gia_inviato():
    """Se il report e' gia' stato inviato, ritorna True."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": "some-id"})

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)

    result = await _is_report_gia_inviato(pool, "org-1", date(2026, 8, 11), date(2026, 8, 17))
    assert result is True


@pytest.mark.asyncio
async def test_report_non_ancora_inviato():
    """Se il report non e' mai stato inviato, ritorna False."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)

    result = await _is_report_gia_inviato(pool, "org-1", date(2026, 8, 11), date(2026, 8, 17))
    assert result is False


@pytest.mark.asyncio
async def test_invio_idempotente_non_reinvia():
    """Se il report e' gia' stato inviato, genera_e_invia ritorna 'gia_inviato'."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value={"id": "existing"})

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)

    result = await genera_e_invia_report_settimanale(pool, "org-1")
    assert result["esito"] == "gia_inviato"


@pytest.mark.asyncio
async def test_invio_senza_owner_non_invia():
    """Se l'org non ha owner, ritorna 'no_destinatari'."""
    call_count = {"n": 0}
    results = [
        None,   # _is_report_gia_inviato -> non trovato
        {"nome": "Test"},  # _get_nome_attivita
    ]

    conn = AsyncMock()

    async def mock_fetchrow(*args, **kwargs):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(results):
            return results[idx]
        return {"totale": 0, "gestiti_da_ai": 0, "escalati": 0,
                "avg_risposta_sec": None, "confermate": 0, "cancellate": 0,
                "no_show": 0, "completate": 0, "da_whatsapp": 0,
                "con_risposta": 0, "media_stelle": None}

    conn.fetchrow = mock_fetchrow
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    pool.fetch = AsyncMock(return_value=[])

    # Mock CoreRepository.get_organization_owners per ritornare lista vuota
    with patch("src.core.report.weekly_report.CoreRepository") as MockRepo, \
         patch("src.core.report.weekly_report.genera_pdf", return_value=b"%PDF-fake"):
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_organization_owners = AsyncMock(return_value=[])
        MockRepo.return_value = mock_repo_instance

        result = await genera_e_invia_report_settimanale(pool, "org-1")

    assert result["esito"] == "no_destinatari"
