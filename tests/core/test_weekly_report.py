"""Test orchestratore report settimanale (no Docker).

Verifica calcolo periodo, claim atomico (FIX 2b), invio sincrono
(FIX 2a) e gestione errori/retry (FIX 3). La logica SQL del claim viene
esercitata con dati reali in test_weekly_report_integration.py.
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
    """Se il report e' gia' stato inviato (stato='sent'), ritorna True."""
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


# ── Test flusso di invio ──


def _mock_pool_claim(claim_id="claim-1"):
    """Pool mock dove _claim_periodo ritorna claim_id."""
    conn = AsyncMock()
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    pool.fetch = AsyncMock(return_value=[])
    return pool


@pytest.mark.asyncio
async def test_invio_idempotente_non_reinvia():
    """Se il claim non e' ottenuto (gia' pending/sent), ritorna 'gia_inviato'."""
    pool = _mock_pool_claim()
    with patch("src.core.report.weekly_report._claim_periodo", new=AsyncMock(return_value=None)):
        result = await genera_e_invia_report_settimanale(pool, "org-1")
    assert result["esito"] == "gia_inviato"


@pytest.mark.asyncio
async def test_invio_senza_owner_non_invia():
    """Se l'org non ha owner, ritorna 'no_destinatari' e rilascia il claim."""
    conn = AsyncMock()

    risultati_fetchrow = [
        {"nome": "Test"},  # _get_nome_attivita
        {"totale": 1, "gestiti_da_ai": 1, "escalati": 0, "avg_risposta_sec": None},  # kpi messaggi
        {"totale": 1, "confermate": 1, "cancellate": 0, "no_show": 0, "completate": 0, "da_whatsapp": 1},  # kpi prenotazioni
        {"totale": 0, "con_risposta": 0, "media_stelle": None},  # kpi recensioni
    ]

    async def mock_fetchrow(*args, **kwargs):
        return risultati_fetchrow.pop(0)

    conn.fetchrow = mock_fetchrow
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    pool.fetch = AsyncMock(return_value=[])

    with patch("src.core.report.weekly_report._claim_periodo", new=AsyncMock(return_value="claim-1")), \
         patch("src.core.report.weekly_report.CoreRepository") as MockRepo, \
         patch("src.core.report.weekly_report.genera_pdf", return_value=b"%PDF-fake"), \
         patch("src.core.report.weekly_report._segna_stato") as mock_segna:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_organization_owners = AsyncMock(return_value=[])
        MockRepo.return_value = mock_repo_instance

        result = await genera_e_invia_report_settimanale(pool, "org-1")

    assert result["esito"] == "no_destinatari"
    mock_segna.assert_awaited_once()
    stato = mock_segna.call_args[0][2]
    assert stato == "failed"


@pytest.mark.asyncio
async def test_invio_riuscito_marca_sent():
    """Se l'invio riesce, il claim viene marcato 'sent' e ritorna 'inviato'."""
    conn = AsyncMock()

    risultati_fetchrow = [
        {"nome": "Test"},  # _get_nome_attivita
        {"totale": 1, "gestiti_da_ai": 1, "escalati": 0, "avg_risposta_sec": None},  # kpi messaggi
        {"totale": 1, "confermate": 1, "cancellate": 0, "no_show": 0, "completate": 0, "da_whatsapp": 1},  # kpi prenotazioni
        {"totale": 0, "con_risposta": 0, "media_stelle": None},  # kpi recensioni
    ]

    async def mock_fetchrow(*args, **kwargs):
        return risultati_fetchrow.pop(0)

    conn.fetchrow = mock_fetchrow
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock()

    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    pool.fetch = AsyncMock(return_value=[])

    with patch("src.core.report.weekly_report._claim_periodo", new=AsyncMock(return_value="claim-1")), \
         patch("src.core.report.weekly_report.CoreRepository") as MockRepo, \
         patch("src.core.report.weekly_report.genera_pdf", return_value=b"%PDF-fake"), \
         patch("src.core.report.weekly_report._get_smtp_config", return_value={"host": "x"}), \
         patch("src.core.report.weekly_report._send_with_retry", new=AsyncMock()) as mock_send, \
         patch("src.core.report.weekly_report._segna_stato") as mock_segna:
        mock_repo_instance = MagicMock()
        mock_repo_instance.get_organization_owners = AsyncMock(return_value=[{"email": "o@x.it"}])
        MockRepo.return_value = mock_repo_instance

        result = await genera_e_invia_report_settimanale(pool, "org-1")

    assert result["esito"] == "inviato"
    mock_send.assert_awaited_once()
    mock_segna.assert_awaited_once()
    stato = mock_segna.call_args[0][2]
    assert stato == "sent"


@pytest.mark.asyncio
async def test_errore_permanente_marca_failed_e_raise():
    """Un errore non transiente marca 'failed', allerta Sentry e ri-solleva (nessun retry)."""
    conn = AsyncMock()
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    pool.fetch = AsyncMock(return_value=[])

    errore = ValueError("errore permanente")

    with patch("src.core.report.weekly_report._claim_periodo", new=AsyncMock(return_value="claim-1")), \
         patch("src.core.report.weekly_report._genera_e_invia", side_effect=errore) as mock_genera, \
         patch("src.core.report.weekly_report._segna_stato") as mock_segna, \
         patch("src.core.report.weekly_report._allerta_sentry") as mock_alert, \
         pytest.raises(ValueError, match="errore permanente"):
        await genera_e_invia_report_settimanale(pool, "org-1")

    mock_segna.assert_awaited_once()
    assert mock_segna.call_args[0][2] == "failed"
    mock_alert.assert_called_once()
    # Nessun retry per errori permanenti: un solo tentativo
    assert mock_genera.call_count == 1


@pytest.mark.asyncio
async def test_errore_transiente_retry_poi_failed():
    """Un errore transiente viene ritentato (max 3 tentativi) poi marcato 'failed'."""
    conn = AsyncMock()
    pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=ctx)
    pool.fetch = AsyncMock(return_value=[])

    errore = ConnectionError("SMTP irraggiungibile")

    with patch("src.core.report.weekly_report._claim_periodo", new=AsyncMock(return_value="claim-1")), \
         patch("src.core.report.weekly_report._genera_e_invia", side_effect=errore) as mock_genera, \
         patch("src.core.report.weekly_report._segna_stato") as mock_segna, \
         patch("src.core.report.weekly_report._allerta_sentry") as mock_alert, \
         pytest.raises(ConnectionError, match="SMTP irraggiungibile"):
        await genera_e_invia_report_settimanale(pool, "org-1")

    # 3 tentativi totali (1 + 2 retry esterni) per sole eccezioni transienti
    assert mock_genera.call_count == 3
    mock_segna.assert_awaited_once()
    assert mock_segna.call_args[0][2] == "failed"
    mock_alert.assert_called_once()