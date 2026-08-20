"""Test di integrazione KPI settimanali su PostgreSQL reale (Docker).

Verifica con dati reali (fixture pg_pool) che le query di
calcola_kpi_messaggi/prenotazioni/recensioni filtrino e calcolino
correttamente (FIX 5 redteam punto 17), includendo:
- dati al confine del periodo (dentro/fuori)
- messaggi AI-handled vs human/escalated, risposti/non risposti
- stati prenotazioni, recensioni con/senza risposta
- verifica di equivalenza FIX 1: kpi.messaggi == calcola_statistiche
  sullo stesso storico eventi (entrambi leggono da event_log)
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from src.core.analytics.kpi import (
    calcola_kpi_messaggi,
    calcola_kpi_prenotazioni,
    calcola_kpi_recensioni,
    calcola_kpi_settimanali,
)
from src.core.statistiche import calcola_statistiche
from src.models.schemas import EventoDashboard

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("reset_db")]

# Periodo di riferimento (lunedi-domenica)
INIZIO = date(2026, 8, 10)
FINE = date(2026, 8, 16)

# Timestamp di riferimento nel periodo
T0 = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)  # dentro il periodo
T_DENTRO_AL_CONFINE = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)  # ultimo istante del periodo
T_FUORI_PRIMA = datetime(2026, 8, 9, 23, 59, 59, tzinfo=timezone.utc)  # giorno prima
T_FUORI_DOPO = datetime(2026, 8, 17, 0, 0, 0, tzinfo=timezone.utc)  # primo istante dopo


async def _setup_org_conv_contact(pg_pool):
    """Crea org + contatto + conversazione; ritorna i relativi id."""
    async with pg_pool.acquire() as conn:
        org = await conn.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Org Test') RETURNING id",
            uuid.uuid4(),
        )
        contact = await conn.fetchrow(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234501') RETURNING id",
            uuid.uuid4(), org["id"],
        )
        conv = await conn.fetchrow(
            "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
            uuid.uuid4(), org["id"], contact["id"],
        )
        return org["id"], contact["id"], conv["id"]


async def _inserisci_messaggio(pg_pool, org_id, conv_id, ts, handling_type, replied=False):
    """Inserisce un messaggio inbound gestito; il trigger popola event_log."""
    async with pg_pool.acquire() as conn:
        msg_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO messages
                (id, organization_id, conversation_id, direction, message_type,
                 content, content_text, status, handling_type, created_at, replied_at)
            VALUES ($1, $2, $3, 'inbound', 'text',
                    '{}'::jsonb, 'msg', 'handled', $4, $5::timestamptz,
                    CASE WHEN $6 THEN $5::timestamptz + INTERVAL '1 minute' ELSE NULL END)
            """,
            msg_id, org_id, conv_id, handling_type, ts, replied,
        )


def _storico_da_event_log(rows) -> list[EventoDashboard]:
    """Costruisce EventoDashboard dalle righe event_log (come il dashboard)."""
    return [
        EventoDashboard(
            id=str(r["id"]),
            tipo_evento=r["tipo_evento"],
            timestamp=r["created_at"],
            priorita=r["priorita"],
            testo_originale=r["testo_originale"],
            risposta_ai=r["risposta_ai"],
            gestito_da_ai=r["gestito_da_ai"],
            dettagli=json.loads(r["dettagli"] or "{}"),
        )
        for r in rows
    ]


# ── FIX 5: KPI Messaggi con dati reali e boundary ──


@pytest.mark.asyncio
async def test_kpi_messaggi_boundary_filtra_periodo(pg_pool):
    """Messaggi dentro/fuori periodo e al confine vengono conteggiati correttamente."""
    org_id, _contact, conv_id = await _setup_org_conv_contact(pg_pool)
    # 2 AI-handled + 1 escalato dentro il periodo (uno al confine)
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0, "ai_handled", replied=True)
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T_DENTRO_AL_CONFINE, "ai_handled")
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0 + timedelta(minutes=5), "escalated", replied=True)
    # Fuori periodo: prima e dopo
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T_FUORI_PRIMA, "ai_handled")
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T_FUORI_DOPO, "ai_handled")

    kpi = await calcola_kpi_messaggi(pg_pool, str(org_id), INIZIO, FINE)

    assert kpi.totale == 3
    assert kpi.gestiti_da_ai == 2
    assert kpi.escalati_a_umano == 1
    assert kpi.percentuale_ai == round((2 / 3) * 100, 1)
    # tempo medio: 2 messaggi risposti (1 min + 1 min) / 2 = 60s
    assert kpi.tempo_medio_risposta_secondi == 60.0


@pytest.mark.asyncio
async def test_kpi_messaggi_nessun_messaggio(pg_pool):
    """Nessun messaggio nel periodo: tutto zero, nessun errore."""
    org_id, _contact, _conv_id = await _setup_org_conv_contact(pg_pool)
    kpi = await calcola_kpi_messaggi(pg_pool, str(org_id), INIZIO, FINE)
    assert kpi.totale == 0
    assert kpi.gestiti_da_ai == 0
    assert kpi.escalati_a_umano == 0
    assert kpi.percentuale_ai == 0.0
    assert kpi.tempo_medio_risposta_secondi is None


@pytest.mark.asyncio
async def test_kpi_messaggi_non_contamina_altre_org(pg_pool):
    """I messaggi di un'altra org non influenzano i KPI dell'org test."""
    org_id, _contact, conv_id = await _setup_org_conv_contact(pg_pool)
    altra_org_id, _c2, conv2 = await _setup_org_conv_contact(pg_pool)
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0, "ai_handled")
    await _inserisci_messaggio(pg_pool, altra_org_id, conv2, T0, "ai_handled")

    kpi = await calcola_kpi_messaggi(pg_pool, str(org_id), INIZIO, FINE)
    assert kpi.totale == 1


# ── FIX 5: KPI Prenotazioni ──


@pytest.mark.asyncio
async def test_kpi_prenotazioni_stati_e_periodo(pg_pool):
    """Stati prenotazioni conteggiati correttamente, filtrati per periodo."""
    org_id, _contact, _conv_id = await _setup_org_conv_contact(pg_pool)
    async with pg_pool.acquire() as conn:
        for stato, ts, origine in [
            ("confermata", T0, "WhatsApp"),
            ("completata", T0, "Dashboard"),
            ("cancellata", T0, "WhatsApp"),
            ("no_show", T0, "WhatsApp"),
            ("completata", T_FUORI_PRIMA, "WhatsApp"),
            ("confermata", T_DENTRO_AL_CONFINE, "WhatsApp"),
        ]:
            await conn.execute(
                """
                INSERT INTO bookings
                    (id, organization_id, nome_cliente, telefono, data, ora,
                     coperti, stato, origine, created_at)
                VALUES ($1, $2, 'Cliente', '', '2026-08-12', '20:00', 2,
                        $3, $4, $5)
                """,
                uuid.uuid4(), org_id, stato, origine, ts,
            )

    kpi = await calcola_kpi_prenotazioni(pg_pool, str(org_id), INIZIO, FINE)

    assert kpi.totale == 5  # tutte tranne quella fuori periodo
    assert kpi.confermate == 2
    assert kpi.completate == 1
    assert kpi.cancellate == 1
    assert kpi.no_show == 1
    assert kpi.da_whatsapp == 4


# ── FIX 5: KPI Recensioni ──


@pytest.mark.asyncio
async def test_kpi_recensioni_risposta_e_stelle(pg_pool):
    """Recensioni con/senza risposta e media stelle, filtrate per periodo."""
    org_id, _contact, _conv_id = await _setup_org_conv_contact(pg_pool)
    async with pg_pool.acquire() as conn:
        for stelle, stato, ts in [
            (5, "pubblicata", T0),
            (3, "bozza_generata", T0),
            (1, "approvata", T_DENTRO_AL_CONFINE),
            (2, "nuova", T0),              # senza risposta
            (4, "pubblicata", T_FUORI_PRIMA),  # fuori periodo
        ]:
            await conn.execute(
                """
                INSERT INTO reviews
                    (id, organization_id, testo, valutazione_stelle,
                     fonte, autore, stato, created_at)
                VALUES ($1, $2, 'recensione', $3, 'google', 'Tizio', $4, $5)
                """,
                uuid.uuid4(), org_id, stelle, stato, ts,
            )

    kpi = await calcola_kpi_recensioni(pg_pool, str(org_id), INIZIO, FINE)

    assert kpi.totale == 4  # esclusa quella fuori periodo
    assert kpi.con_risposta == 3  # pubblicata/bozza_generata/approvata
    assert kpi.percentuale_risposta == 75.0
    assert kpi.media_stelle == round((5 + 3 + 1 + 2) / 4, 1)


# ── FIX 1: equivalenza kpi.messaggi == calcola_statistiche ──


@pytest.mark.asyncio
async def test_equivalenza_kpi_statistiche_su_stessi_dati(pg_pool):
    """I numeri di kpi.messaggi coincidono con calcola_statistiche sullo
    stesso storico eventi (entrambi leggono da event_log)."""
    org_id, _contact, conv_id = await _setup_org_conv_contact(pg_pool)
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0, "ai_handled")
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0 + timedelta(hours=1), "ai_handled")
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0 + timedelta(hours=2), "escalated")
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T_FUORI_PRIMA, "ai_handled")  # fuori periodo

    # Storico eventi dal DB (stessa fonte di event_log usata da KPI)
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM event_log
            WHERE organization_id = $1
              AND source_table = 'messages'
              AND tipo_evento = 'messaggio'
              AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
              AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')
            """,
            org_id, INIZIO, FINE,
        )
    storico = _storico_da_event_log(rows)
    stats = calcola_statistiche(storico)

    kpi = await calcola_kpi_messaggi(pg_pool, str(org_id), INIZIO, FINE)

    # Equivalenza matematica richiesta dal FIX 1
    assert kpi.totale == stats.totale_messaggi
    assert kpi.gestiti_da_ai == stats.gestiti_da_ai
    assert kpi.escalati_a_umano == stats.girati_a_umano
    assert kpi.totale == kpi.gestiti_da_ai + kpi.escalati_a_umano


@pytest.mark.asyncio
async def test_calcola_kpi_settimanali_aggregato_reale(pg_pool):
    """Aggregato settimanale su dati reali: tutti i sotto-KPI popolati."""
    org_id, _contact, conv_id = await _setup_org_conv_contact(pg_pool)
    await _inserisci_messaggio(pg_pool, org_id, conv_id, T0, "ai_handled")
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bookings (id, organization_id, nome_cliente, data, ora, coperti, stato, created_at) "
            "VALUES ($1, $2, 'C', '2026-08-12', '20:00', 2, 'confermata', $3)",
            uuid.uuid4(), org_id, T0,
        )
        await conn.execute(
            "INSERT INTO reviews (id, organization_id, testo, valutazione_stelle, created_at) "
            "VALUES ($1, $2, 'r', 4, $3)",
            uuid.uuid4(), org_id, T0,
        )

    kpi = await calcola_kpi_settimanali(
        pg_pool, str(org_id), INIZIO, FINE, nome_attivita="Ristorante Test",
    )

    assert kpi.periodo_inizio == "2026-08-10"
    assert kpi.periodo_fine == "2026-08-16"
    assert kpi.nome_attivita == "Ristorante Test"
    assert kpi.messaggi.totale == 1
    assert kpi.prenotazioni.totale == 1
    assert kpi.recensioni.totale == 1