"""Orchestratore report settimanale.

Flusso: calcola KPI -> genera PDF -> genera CSV -> invia email -> logga invio.
Idempotenza: il log in weekly_report_log viene scritto SOLO dopo l'invio
email riuscito. Il constraint UNIQUE(org, periodo_inizio, periodo_fine)
impedisce invii doppi.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from src.core.analytics.kpi import calcola_kpi_settimanali
from src.core.db.repository import CoreRepository
from src.core.notifications.email_service import (
    EmailAttachment,
    EmailEvent,
    _enqueue,
)
from src.core.report.csv_export import genera_csv, get_prenotazioni_completate
from src.core.report.pdf_generator import genera_pdf

logger = logging.getLogger(__name__)


def _calcola_periodo_settimanale(oggi: date | None = None) -> tuple[date, date]:
    """Calcola il periodo lunedi-domenica della settimana PRECEDENTE.

    Se oggi e' lunedi, il periodo e' lunedi scorso -> domenica scorsa.
    """
    if oggi is None:
        oggi = datetime.now(tz=timezone.utc).date()
    # Lunedi della settimana corrente
    lunedi_corrente = oggi - timedelta(days=oggi.weekday())
    # Settimana precedente
    fine = lunedi_corrente - timedelta(days=1)   # Domenica scorsa
    inizio = fine - timedelta(days=6)            # Lunedi scorso
    return inizio, fine


async def _is_report_gia_inviato(
    pool,
    org_id: str,
    inizio: date,
    fine: date,
) -> bool:
    """Controlla se il report per questo periodo e' gia' stato inviato."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id FROM weekly_report_log
            WHERE organization_id = $1
              AND periodo_inizio = $2
              AND periodo_fine = $3
        """, org_id, inizio, fine)
    return row is not None


async def _registra_invio(
    pool,
    org_id: str,
    inizio: date,
    fine: date,
    destinatari: list[str],
) -> None:
    """Registra l'invio del report nel log di idempotenza."""
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO weekly_report_log
                (organization_id, periodo_inizio, periodo_fine, destinatari)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (organization_id, periodo_inizio, periodo_fine) DO NOTHING
        """, org_id, inizio, fine, destinatari)


async def _get_nome_attivita(pool, org_id: str) -> str:
    """Recupera il nome dell'attivita' dall'organizzazione."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                COALESCE(
                    business_profile->>'nome',
                    name,
                    'La tua attività'
                ) AS nome
            FROM organizations
            WHERE id = $1
        """, org_id)
    return row["nome"] if row else "La tua attività"


async def genera_e_invia_report_settimanale(
    pool,
    org_id: str,
    forza: bool = False,
) -> dict:
    """Genera e invia il report settimanale per un'organizzazione.

    Args:
        pool: asyncpg connection pool
        org_id: UUID dell'organizzazione
        forza: se True, ignora il check di idempotenza

    Returns:
        dict con esito, periodo, e dettagli dell'invio
    """
    inizio, fine = _calcola_periodo_settimanale()

    # Check idempotenza
    if not forza and await _is_report_gia_inviato(pool, org_id, inizio, fine):
        logger.info(
            "report_settimanale=gia_inviato org=%s periodo=%s/%s",
            org_id, inizio, fine,
        )
        return {
            "esito": "gia_inviato",
            "periodo_inizio": inizio.isoformat(),
            "periodo_fine": fine.isoformat(),
        }

    # 1. Nome attivita'
    nome = await _get_nome_attivita(pool, org_id)

    # 2. Calcola KPI
    kpi = await calcola_kpi_settimanali(pool, org_id, inizio, fine, nome_attivita=nome)

    # 3. Genera PDF
    pdf_bytes = genera_pdf(kpi)

    # 4. Genera CSV prenotazioni
    prenotazioni = await get_prenotazioni_completate(pool, org_id, inizio, fine)
    csv_bytes = genera_csv(prenotazioni)

    # 5. Destinatari (owner dell'org)
    repo = CoreRepository(pool)
    owners = await repo.get_organization_owners(org_id)
    if not owners:
        logger.warning(
            "report_settimanale=no_owners org=%s", org_id,
        )
        return {"esito": "no_destinatari", "periodo_inizio": inizio.isoformat(), "periodo_fine": fine.isoformat()}

    destinatari = [o["email"] for o in owners]

    # 6. Prepara allegati
    allegati = [
        EmailAttachment(
            filename=f"report-settimanale-{inizio.isoformat()}.pdf",
            content=pdf_bytes,
            maintype="application",
            subtype="pdf",
        ),
    ]
    # CSV allegato solo se ci sono prenotazioni
    if prenotazioni:
        allegati.append(
            EmailAttachment(
                filename=f"prenotazioni-{inizio.isoformat()}.csv",
                content=csv_bytes,
                maintype="text",
                subtype="csv",
            ),
        )

    # 7. Invia email
    periodo_str = f"{inizio.strftime('%d/%m')} - {fine.strftime('%d/%m/%Y')}"
    _enqueue(EmailEvent(
        org_id=org_id,
        subject=f"Report settimanale {nome} — {periodo_str}",
        body=(
            f"In allegato il report settimanale della tua attività "
            f"({periodo_str}).\n\n"
            f"Il report include i KPI della settimana e, se presenti, "
            f"l'export CSV delle prenotazioni completate.\n\n"
            f"— Melpis"
        ),
        pool=pool,
        attachments=allegati,
    ))

    # 8. Registra invio (DOPO l'enqueue — se l'enqueue fallisce,
    #    non registriamo e il prossimo trigger riprovera')
    await _registra_invio(pool, org_id, inizio, fine, destinatari)

    logger.info(
        "report_settimanale=inviato org=%s periodo=%s/%s destinatari=%s",
        org_id, inizio, fine, destinatari,
    )
    return {
        "esito": "inviato",
        "periodo_inizio": inizio.isoformat(),
        "periodo_fine": fine.isoformat(),
        "destinatari": destinatari,
        "pdf_size_bytes": len(pdf_bytes),
        "csv_righe": len(prenotazioni),
    }


async def genera_report_tutte_le_org(pool) -> list[dict]:
    """Genera e invia il report settimanale per TUTTE le organizzazioni attive."""
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    risultati = []
    for org in orgs:
        org_id = str(org["id"])
        try:
            risultato = await genera_e_invia_report_settimanale(pool, org_id)
            risultati.append({"org_id": org_id, **risultato})
        except Exception as e:
            logger.error(
                "report_settimanale=errore org=%s errore=%s",
                org_id, str(e),
            )
            risultati.append({"org_id": org_id, "esito": "errore", "errore": str(e)})
    return risultati
