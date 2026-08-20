"""Orchestratore report settimanale.

Flusso: claim atomico -> calcola KPI -> genera PDF -> genera CSV -> invia
email (sincrono con retry) -> marca 'sent'.

Correzioni redteam punto 17:
- FIX 2b: claim atomico single-step con colonna 'stato' (pending/sent/
  failed). Il lock e' un'INSERT ... ON CONFLICT DO UPDATE ... WHERE
  stato='failed' RETURNING id: 1 riga = claim ottenuto, 0 righe = gia'
  'pending' (in corso) o 'sent' (inviato). Su errore il record viene
  marcato 'failed' (mai lasciato bloccato in 'pending').
- FIX 2a: invio sincrono via _send_with_retry (niente coda RAM) e
  concorrenza reale in genera_report_tutte_le_org con asyncio.gather +
  asyncio.Semaphore(5).
- FIX 3: allowlist di eccezioni transienti con retry esterni limitati e
  alert su Sentry; qualsiasi altra eccezione e' permanente (alert
  immediato, nessun retry).
"""

import asyncio
import logging
import smtplib
from datetime import date, datetime, timedelta, timezone

import sentry_sdk

from src.core.analytics.kpi import calcola_kpi_settimanali
from src.core.db.repository import CoreRepository
from src.core.notifications.email_service import (
    EmailAttachment,
    EmailEvent,
    _get_smtp_config,
    _send_with_retry,
)
from src.core.report.csv_export import genera_csv, get_prenotazioni_completate
from src.core.report.pdf_generator import genera_pdf

logger = logging.getLogger(__name__)

# FIX 3: eccezioni considerate transitorie (retry esterno limitato).
# asyncio.TimeoutError e' alias di TimeoutError da Python 3.11; incluso
# per chiarezza/esplicitezza della allowlist.
TRANSIENT_EXCEPTIONS = (
    smtplib.SMTPException,
    ConnectionError,
    TimeoutError,
    asyncio.TimeoutError,
)

# FIX 3: tentativi totali del flusso (1 iniziale + 2 retry esterni).
MAX_TENTATIVI_TRANSIENTI = 3


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
              AND stato = 'sent'
        """, org_id, inizio, fine)
    return row is not None


async def _claim_periodo(
    pool,
    org_id: str,
    inizio: date,
    fine: date,
) -> str | None:
    """Claim atomico single-step del periodo (FIX 2b).

    Una singola query atomica: se non esiste un record lo inserisce in
    'pending'; se esiste con stato 'failed' lo ri-assegna a 'pending'.
    In entrambi i casi RETURNING restituisce l'id del claim (1 riga).
    Se il record esiste gia' come 'pending' (altro worker in corso) o
    'sent' (gia' inviato), il WHERE del DO UPDATE non e' soddisfatto,
    nessuna riga viene aggiornata e RETURNING non restituisce nulla
    (0 righe) -> il chiamante esce con "gia_inviato/in_corso".
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO weekly_report_log
                (organization_id, periodo_inizio, periodo_fine, stato)
            VALUES ($1, $2, $3, 'pending')
            ON CONFLICT (organization_id, periodo_inizio, periodo_fine)
            DO UPDATE SET stato = 'pending'
            WHERE weekly_report_log.stato = 'failed'
            RETURNING id
        """, org_id, inizio, fine)
    return str(row["id"]) if row else None


async def _segna_stato(
    pool,
    claim_id: str,
    stato: str,
    destinatari: list[str] | None = None,
    motivo: str | None = None,
) -> None:
    """Aggiorna lo stato del claim (FIX 2b/3).

    - 'sent':   invio riuscito -> destinatari e inviato_at aggiornati.
    - 'failed': invio fallito -> destinatari/inviato_at invariati
                (il prossimo run puo' reclamare e riprovare).
    """
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE weekly_report_log
            SET stato = $2,
                destinatari = CASE WHEN $2 = 'sent' THEN $3 ELSE destinatari END,
                inviato_at = CASE WHEN $2 = 'sent' THEN NOW() ELSE inviato_at END,
                motivo_errore = $4
            WHERE id = $1
        """, claim_id, stato, destinatari, motivo)


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


def _allerta_sentry(exc: BaseException, org_id: str) -> None:
    """Invia l'eccezione a Sentry senza mai rompere il flusso report."""
    try:
        sentry_sdk.capture_exception(exc)
    except Exception:
        logger.exception("report_settimanale=sentry_fallito org=%s", org_id)
    logger.error(
        "report_settimanale=errore org=%s errore=%s",
        org_id, exc,
    )


async def _genera_e_invia(pool, org_id: str, inizio: date, fine: date) -> dict:
    """Genera KPI/PDF/CSV e invia l'email in modo sincrono.

    Restituisce il dict di esito ('inviato' o 'no_destinatari').
    Le eccezioni NON vengono gestite qui: propagano al chiamante che le
    classifica come transitorie o permanenti (FIX 3).
    """
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

    # 7. Invia email (sincrono, con retry tenacity interno 3x)
    # Se SMTP non e' configurato _send_with_retry tornerebbe silenziosamente
    # senza inviare: lo verifichiamo qui per far fallire il flusso (FIX 3)
    # invece di marcare 'sent' un report mai spedito.
    if _get_smtp_config() is None:
        raise RuntimeError("configurazione SMTP assente — email report non inviata")

    periodo_str = f"{inizio.strftime('%d/%m')} - {fine.strftime('%d/%m/%Y')}"
    await _send_with_retry(EmailEvent(
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


async def genera_e_invia_report_settimanale(
    pool,
    org_id: str,
    forza: bool = False,
) -> dict:
    """Genera e invia il report settimanale per un'organizzazione.

    Args:
        pool: asyncpg connection pool
        org_id: UUID dell'organizzazione
        forza: se True, ignora il claim di idempotenza e reinvia

    Returns:
        dict con esito, periodo, e dettagli dell'invio.
        Solleva l'eccezione se il flusso fallisce definitivamente
        (record marcato 'failed' e alert Sentry).
    """
    inizio, fine = _calcola_periodo_settimanale()

    # FIX 2b: claim atomico (se forza=False). Se il periodo e' gia'
    # 'pending' (in corso) o 'sent' (inviato), non si procede.
    claim_id = None
    if not forza:
        claim_id = await _claim_periodo(pool, org_id, inizio, fine)
        if claim_id is None:
            logger.info(
                "report_settimanale=gia_inviato org=%s periodo=%s/%s",
                org_id, inizio, fine,
            )
            return {
                "esito": "gia_inviato",
                "periodo_inizio": inizio.isoformat(),
                "periodo_fine": fine.isoformat(),
            }

    # FIX 3: flusso con retry limitato per sole eccezioni transienti.
    # 'inviato' evita di rispedire l'email se il fallimento avviene dopo
    # l'invio (es. mark 'sent' con DB momentaneamente irraggiungibile).
    risultato: dict | None = None
    inviato = False
    ultimo_errore: BaseException | None = None

    for tentativo in range(1, MAX_TENTATIVI_TRANSIENTI + 1):
        try:
            if not inviato:
                risultato = await _genera_e_invia(pool, org_id, inizio, fine)

            if risultato["esito"] == "no_destinatari":
                # Nessun destinatario: non e' un errore, ma il claim va
                # rilasciato (-> 'failed') per permettere un nuovo tentativo
                # quando l'org avra' un owner.
                await _segna_stato(pool, claim_id, "failed", motivo="nessun destinatario")
                return risultato

            inviato = True
            await _segna_stato(pool, claim_id, "sent", destinatari=risultato["destinatari"])
            return risultato

        except TRANSIENT_EXCEPTIONS as e:
            ultimo_errore = e
            if tentativo < MAX_TENTATIVI_TRANSIENTI:
                logger.warning(
                    "report_settimanale=retry_transiente org=%s tentativo=%d/%d errore=%s",
                    org_id, tentativo, MAX_TENTATIVI_TRANSIENTI, e,
                )
                continue
        except Exception as e:
            # Errore permanente: nessun retry (FIX 3).
            ultimo_errore = e
            break

    # Esauriti i retry (transiente) o errore permanente: marca 'failed'
    # e ri-solleva, cosi' il record non resta bloccato in 'pending'.
    try:
        await _segna_stato(pool, claim_id, "failed", motivo=str(ultimo_errore))
    except Exception:
        logger.exception("report_settimanale=marca_failed_fallita org=%s", org_id)
    _allerta_sentry(ultimo_errore, org_id)
    raise ultimo_errore


async def genera_report_tutte_le_org(pool) -> list[dict]:
    """Genera e invia il report settimanale per TUTTE le org attive.

    Concorrenza reale con asyncio.gather + Semaphore(5). Il pool di
    produzione e' dimensionato con max_size=5 (src/api/main.py:109), quindi
    il semaforo non crea colli di bottiglia. Con return_exceptions=True gli
    errori vengono catturati per singolo tenant e mappati nell'esito,
    mai persi nell'array dei risultati.
    """
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)

    semaforo = asyncio.Semaphore(5)

    async def _con_semaforo(org) -> dict:
        async with semaforo:
            return await genera_e_invia_report_settimanale(pool, str(org["id"]))

    risultati_grezzi = await asyncio.gather(
        *(_con_semaforo(org) for org in orgs),
        return_exceptions=True,
    )

    # FIX 2a: discriminare esplicitamente le eccezioni restituite da gather
    # e mapparle al tenant corrispondente (ordine preservato).
    risultati = []
    for idx, ris in enumerate(risultati_grezzi):
        org_id = str(orgs[idx]["id"])
        if isinstance(ris, Exception):
            risultati.append({"org_id": org_id, "esito": "errore", "errore": str(ris)})
        elif isinstance(ris, dict):
            risultati.append({"org_id": org_id, **ris})
        else:
            risultati.append({"org_id": org_id, "esito": "errore", "errore": repr(ris)})
    return risultati