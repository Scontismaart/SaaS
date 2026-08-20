"""Calcolo KPI settimanali da database.

Query dirette SQL — nessun LLM coinvolto. Ogni metrica e' calcolata
per una singola organizzazione nel periodo [inizio, fine].
"""

from datetime import date

from src.models.schemas import (
    KPIMessaggi,
    KPIPrenotazioni,
    KPIRecensioni,
    KPISettimanali,
)

# Fonte unificata degli analytics (FIX 1 redteam punto 17):
# i conteggi messaggi leggono da event_log, la stessa proiezione derivata
# da trigger che alimenta il dashboard (src/core/db/triggers.sql). Il
# trigger log_message_event registra solo i messaggi inbound gestiti
# (status='handled'), quindi i numeri coincidono con calcola_statistiche
# sullo storico eventi (verifica di equivalenza in test_kpi_integration.py).


async def calcola_kpi_messaggi(pool, org_id: str, inizio: date, fine: date) -> KPIMessaggi:
    """KPI messaggi inbound nel periodo: totale, gestiti da AI, escalati, tempo medio risposta.

    Conteggi (totale/gestiti/escalati) da event_log; il tempo medio di
    risposta resta su messages perche' event_log non espone replied_at.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                (SELECT COUNT(*) FROM event_log
                 WHERE organization_id = $1
                   AND source_table = 'messages'
                   AND tipo_evento = 'messaggio'
                   AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
                   AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')) AS totale,
                (SELECT COUNT(*) FROM event_log
                 WHERE organization_id = $1
                   AND source_table = 'messages'
                   AND tipo_evento = 'messaggio'
                   AND gestito_da_ai
                   AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
                   AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')) AS gestiti_da_ai,
                (SELECT COUNT(*) FROM event_log
                 WHERE organization_id = $1
                   AND source_table = 'messages'
                   AND tipo_evento = 'messaggio'
                   AND NOT gestito_da_ai
                   AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
                   AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')) AS escalati,
                (SELECT EXTRACT(EPOCH FROM AVG(replied_at - created_at))
                 FROM messages
                 WHERE organization_id = $1
                   AND direction = 'inbound'
                   AND replied_at IS NOT NULL
                   AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
                   AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')) AS avg_risposta_sec
        """, org_id, inizio, fine)

    totale = row["totale"] or 0
    gestiti = row["gestiti_da_ai"] or 0
    escalati = row["escalati"] or 0
    avg_sec = float(row["avg_risposta_sec"]) if row["avg_risposta_sec"] is not None else None
    pct = round((gestiti / totale) * 100, 1) if totale > 0 else 0.0

    return KPIMessaggi(
        totale=totale,
        gestiti_da_ai=gestiti,
        escalati_a_umano=escalati,
        percentuale_ai=pct,
        tempo_medio_risposta_secondi=round(avg_sec, 1) if avg_sec is not None else None,
    )


async def calcola_kpi_prenotazioni(pool, org_id: str, inizio: date, fine: date) -> KPIPrenotazioni:
    """KPI prenotazioni create nel periodo."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) AS totale,
                COUNT(*) FILTER (WHERE stato = 'confermata') AS confermate,
                COUNT(*) FILTER (WHERE stato = 'cancellata') AS cancellate,
                COUNT(*) FILTER (WHERE stato = 'no_show') AS no_show,
                COUNT(*) FILTER (WHERE stato = 'completata') AS completate,
                COUNT(*) FILTER (WHERE origine = 'WhatsApp') AS da_whatsapp
            FROM bookings
            WHERE organization_id = $1
              AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
              AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')
        """, org_id, inizio, fine)

    return KPIPrenotazioni(
        totale=row["totale"] or 0,
        confermate=row["confermate"] or 0,
        cancellate=row["cancellate"] or 0,
        no_show=row["no_show"] or 0,
        completate=row["completate"] or 0,
        da_whatsapp=row["da_whatsapp"] or 0,
    )


async def calcola_kpi_recensioni(pool, org_id: str, inizio: date, fine: date) -> KPIRecensioni:
    """KPI recensioni nel periodo: totale, risposte, media stelle."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COUNT(*) AS totale,
                COUNT(*) FILTER (
                    WHERE stato IN ('bozza_generata', 'approvata', 'pubblicata')
                ) AS con_risposta,
                AVG(valutazione_stelle) FILTER (
                    WHERE valutazione_stelle IS NOT NULL
                ) AS media_stelle
            FROM reviews
            WHERE organization_id = $1
              AND created_at >= ($2::timestamp AT TIME ZONE 'UTC')
              AND created_at < (($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')
        """, org_id, inizio, fine)

    totale = row["totale"] or 0
    con_risposta = row["con_risposta"] or 0
    media = float(row["media_stelle"]) if row["media_stelle"] is not None else None
    pct = round((con_risposta / totale) * 100, 1) if totale > 0 else 0.0

    return KPIRecensioni(
        totale=totale,
        con_risposta=con_risposta,
        percentuale_risposta=pct,
        media_stelle=round(media, 1) if media is not None else None,
    )


async def calcola_kpi_settimanali(
    pool,
    org_id: str,
    inizio: date,
    fine: date,
    nome_attivita: str = "",
) -> KPISettimanali:
    """Calcola tutti i KPI settimanali per un'organizzazione."""
    messaggi = await calcola_kpi_messaggi(pool, org_id, inizio, fine)
    prenotazioni = await calcola_kpi_prenotazioni(pool, org_id, inizio, fine)
    recensioni = await calcola_kpi_recensioni(pool, org_id, inizio, fine)

    return KPISettimanali(
        periodo_inizio=inizio.isoformat(),
        periodo_fine=fine.isoformat(),
        nome_attivita=nome_attivita,
        messaggi=messaggi,
        prenotazioni=prenotazioni,
        recensioni=recensioni,
    )
