"""Test di integrazione del claim atomico e del flusso di invio report (Docker).

Verifica con PostgreSQL reale (fixture pg_pool) i fix del redteam punto 17:
- FIX 2b: claim atomico single-step (pending/sent/failed) e rilascio su errore
- FIX 2a: crash a meta' invio non marca 'sent'; invio sincrono
- FIX 3:  due esecuzioni concorrenti non producono doppio invio
"""

import asyncio
import uuid
from unittest.mock import patch

import pytest

from src.core.report.weekly_report import (
    _calcola_periodo_settimanale,
    _claim_periodo,
    _segna_stato,
    genera_e_invia_report_settimanale,
)

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("reset_db")]

INIZIO, FINE = _calcola_periodo_settimanale()


async def _crea_org(pg_pool):
    async with pg_pool.acquire() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')",
            org_id,
        )
        return str(org_id)


async def _stato_claim(pg_pool, org_id):
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT stato, motivo_errore FROM weekly_report_log "
            "WHERE organization_id = $1 AND periodo_inizio = $2 AND periodo_fine = $3",
            org_id, INIZIO, FINE,
        )
        return row


# ── FIX 2b: claim atomico single-step ──


@pytest.mark.asyncio
async def test_claim_nuovo_ottiene_lock(pg_pool):
    """Primo claim su periodo mai visto: ritorna id e stato 'pending'."""
    org_id = await _crea_org(pg_pool)
    claim_id = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    assert claim_id is not None
    row = await _stato_claim(pg_pool, org_id)
    assert row["stato"] == "pending"


@pytest.mark.asyncio
async def test_claim_pending_non_reclamabile(pg_pool):
    """Se un worker ha gia' il claim (pending), il secondo non lo ottiene."""
    org_id = await _crea_org(pg_pool)
    primo = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    secondo = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    assert primo is not None
    assert secondo is None


@pytest.mark.asyncio
async def test_claim_sent_non_reclamabile(pg_pool):
    """Se il report e' gia' stato inviato (sent), non si puo' reclamare."""
    org_id = await _crea_org(pg_pool)
    claim_id = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    await _segna_stato(pg_pool, claim_id, "sent", destinatari=["o@x.it"])
    nuovo = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    assert nuovo is None


@pytest.mark.asyncio
async def test_claim_failed_reclamabile(pg_pool):
    """Un claim fallito (failed) puo' essere reclamato e torna 'pending'."""
    org_id = await _crea_org(pg_pool)
    primo = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    await _segna_stato(pg_pool, primo, "failed", motivo="SMTP giu'")

    secondo = await _claim_periodo(pg_pool, org_id, INIZIO, FINE)
    assert secondo is not None
    row = await _stato_claim(pg_pool, org_id)
    assert row["stato"] == "pending"


# ── FIX 2a: crash a meta' invio ──


@pytest.mark.asyncio
async def test_crash_a_meta_invio_non_marca_sent(pg_pool):
    """Se il processo muore durante l'invio, il record non viene marcato 'sent'."""
    org_id = await _crea_org(pg_pool)

    # Simula un crash severo (es. OOM/kill -9): la generazione fallisce in
    # modo non gestito prima del _segna_stato('sent'). Un vero kill -9
    # salta anche l'except e lascia 'pending' (stale claim, hardening futuro);
    # un errore gestito marca 'failed'. In entrambi i casi MAI 'sent'.
    # Nessun pre-claim: il claim va fatto dal flusso reale (genera_e_invia_
    # report_settimanale), altrimenti il secondo claim interno fallisce e
    # si esce presto con 'gia_inviato' senza mai chiamare _genera_e_invia.
    with patch(
        "src.core.report.weekly_report._genera_e_invia",
        side_effect=MemoryError("OOM simulato"),
    ), pytest.raises(MemoryError):
        await genera_e_invia_report_settimanale(pg_pool, org_id)

    row = await _stato_claim(pg_pool, org_id)
    assert row["stato"] != "sent"


# ── FIX 3: concorrenza ──


@pytest.mark.asyncio
async def test_due_esecuzioni_concorrenti_non_doppio_invio(pg_pool):
    """Due worker concorrenti: uno invia, l'altro esce con 'gia_inviato'."""
    org_id = await _crea_org(pg_pool)
    sent_count = {"n": 0}

    async def _send_fake(event):
        sent_count["n"] += 1

    async def _fake_genera(pool, org_id, inizio, fine):
        await _send_fake(None)
        return {
            "esito": "inviato",
            "destinatari": ["o@x.it"],
            "periodo_inizio": INIZIO.isoformat(),
            "periodo_fine": FINE.isoformat(),
        }

    with patch(
        "src.core.report.weekly_report._genera_e_invia",
        new=_fake_genera,
    ):
        r1, r2 = await asyncio.gather(
            genera_e_invia_report_settimanale(pg_pool, org_id),
            genera_e_invia_report_settimanale(pg_pool, org_id),
        )

    esiti = {r1["esito"], r2["esito"]}
    assert "inviato" in esiti
    assert "gia_inviato" in esiti
    # Un solo invio effettivo nonostante due esecuzioni concorrenti
    assert sent_count["n"] == 1
    row = await _stato_claim(pg_pool, org_id)
    assert row["stato"] == "sent"