import asyncio
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.core.db.scoping import system_scope
from src.models.schemas import ReportOutput

_report_cache: dict[str, ReportOutput] = {}
_scheduler: BackgroundScheduler | None = None


def _ottieni_storico_ref():
    raise RuntimeError("ottieni_storico_ref non impostato. Chiama imposta_fonte_dati().")


_ottieni_storico = _ottieni_storico_ref
_pool_ref = lambda: (_ for _ in ()).throw(RuntimeError("pool non impostato. Chiama imposta_pool()."))
_pool = _pool_ref


def imposta_fonte_dati(callback):
    global _ottieni_storico
    _ottieni_storico = callback


def imposta_pool(pool):
    global _pool
    _pool = lambda: pool


def get_report_cache(data: str) -> ReportOutput | None:
    return _report_cache.get(data)


def set_report_cache(data: str, report: ReportOutput):
    _report_cache[data] = report


def genera_e_caching():
    from src.core.crew_runner_report import genera_report

    oggi = datetime.now().strftime("%Y-%m-%d")
    storico = _ottieni_storico()
    report = genera_report(storico)
    _report_cache[oggi] = report
    print(f"[scheduler] Report per {oggi} generato e cachato.")


def _run_retention():
    pool = _pool()
    asyncio.run(_retention_job(pool))


async def _retention_job(pool):
    from src.core.retention_job import run_retention

    await run_retention(pool)


def _run_reminder_check():
    pool = _pool()
    asyncio.run(_reminder_check_job(pool))


async def _reminder_check_job(pool):
    from src.core.bookings import BookingService
    from src.core.bookings.reminder_job import send_reminders_for_org
    from src.whatsapp.repository import Repository as WhatsAppRepository
    from src.whatsapp.service import WhatsAppService
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id, timezone FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        wrepo = WhatsAppRepository(pool)
        core_repo = CoreRepository(pool)
        whatsapp = WhatsAppService(None, wrepo)
        service = BookingService(core_repo, whatsapp, None)
        await send_reminders_for_org(service, org["id"], org.get("timezone", "Europe/Rome"))


def _run_reminder_timeout():
    pool = _pool()
    asyncio.run(_reminder_timeout_job(pool))


async def _reminder_timeout_job(pool):
    from src.core.bookings import BookingService
    from src.core.bookings.reminder_job import check_timeouts_for_org
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id, timezone FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        core_repo = CoreRepository(pool)
        service = BookingService(core_repo)
        await check_timeouts_for_org(service, org["id"], org.get("timezone", "Europe/Rome"))


def _run_no_show_check():
    pool = _pool()
    asyncio.run(_no_show_check_job(pool))


async def _no_show_check_job(pool):
    from src.core.bookings import BookingService
    from src.core.bookings.no_show_job import mark_da_verificare_for_org
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id, timezone FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        core_repo = CoreRepository(pool)
        service = BookingService(core_repo)
        await mark_da_verificare_for_org(service, org["id"], org.get("timezone", "Europe/Rome"))


def _run_calendar_sync():
    pool = _pool()
    asyncio.run(_calendar_sync_job(pool))


@system_scope("worker queue: enumerazione org con sync calendar abilitata")
async def _calendar_sync_job(pool):
    encryption_key = os.getenv("ENCRYPTION_KEY", "")
    if not encryption_key:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("calendar=sync_skipped reason=no_encryption_key")
        return
    from src.core.db.repository import CoreRepository
    from src.core.calendar import GoogleCalendarService
    repo = CoreRepository(pool)
    calendar_service = GoogleCalendarService(repo, encryption_key)
    orgs = await pool.fetch("""
        SELECT id FROM google_calendar_credentials
        WHERE sync_enabled = true
    """)
    created = 0
    for org in orgs:
        org_id = org["id"]
        bookings = await pool.fetch("""
            SELECT * FROM bookings
            WHERE organization_id = $1
              AND stato IN ('in_attesa', 'confermata', 'da_verificare')
              AND data >= CURRENT_DATE
              AND google_event_id IS NULL
        """, org_id)
        for b in bookings:
            await calendar_service.sync_booking_state(dict(b), org_id)
            created += 1
        await pool.execute(
            "UPDATE google_calendar_credentials SET last_sync_at = NOW() WHERE organization_id = $1",
            org_id,
        )
    if created:
        logger = __import__("logging").getLogger(__name__)
        logger.info("calendar=sync_complete created=%d", created)


def _run_nonce_cleanup():
    pool = _pool()
    asyncio.run(_nonce_cleanup_job(pool))


async def _nonce_cleanup_job(pool):
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM oauth_nonces WHERE created_at < NOW() - INTERVAL '1 day'"
        )
        logger = __import__("logging").getLogger(__name__)
        logger.info("cleanup=oauth_nonces deleted=%s", result)


def _run_suspension_notice():
    pool = _pool()
    asyncio.run(_suspension_notice_job(pool))


async def _suspension_notice_job(pool):
    """Notifica via email i gestori delle org con trial scaduto e mai
    notificati. Idempotente per costruzione: l'UPDATE con WHERE
    suspension_notified_at IS NULL e' un claim atomico — un'org viene
    notificata esattamente una volta (condiviso con subscription.deleted)."""
    from src.core.notifications.email_service import enqueue_suspension_notice
    claimed = await pool.fetch("""
        UPDATE organizations SET suspension_notified_at = NOW()
        WHERE trial_end < NOW()
          AND subscription_status IN ('trialing', 'incomplete')
          AND suspension_notified_at IS NULL
        RETURNING id
    """)
    for org in claimed:
        enqueue_suspension_notice(str(org["id"]), pool)
    if claimed:
        logger = __import__("logging").getLogger(__name__)
        logger.info("suspension=notice_enqueued count=%d", len(claimed))


def _run_weekly_report():
    pool = _pool()
    asyncio.run(_weekly_report_job(pool))


async def _weekly_report_job(pool):
    """Genera e invia il report settimanale per tutte le org attive.
    Idempotente: un report gia' inviato per lo stesso periodo non viene
    reinviato (weekly_report_log con constraint UNIQUE)."""
    from src.core.report.weekly_report import genera_report_tutte_le_org
    risultati = await genera_report_tutte_le_org(pool)
    logger = __import__("logging").getLogger(__name__)
    inviati = sum(1 for r in risultati if r.get("esito") == "inviato")
    errori = sum(1 for r in risultati if r.get("esito") == "errore")
    logger.info("report_settimanale=completato inviati=%d errori=%d totale=%d",
                inviati, errori, len(risultati))


def avvia_scheduler():
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        genera_e_caching,
        CronTrigger(hour=20, minute=0),
        id="report_giornaliero",
        name="Genera report di fine giornata",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_retention,
        CronTrigger(hour=3, minute=0),
        id="retention_giornaliero",
        name="Data retention — soft-delete e purge",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_reminder_check,
        CronTrigger(minute="*/30"),
        id="booking_reminder_send",
        name="Invia reminder prenotazioni 24h prima",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_reminder_timeout,
        CronTrigger(minute="*/30"),
        id="booking_reminder_timeout",
        name="Flagga reminder senza risposta dopo 12h",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_no_show_check,
        CronTrigger(hour=23, minute=30),
        id="booking_no_show",
        name="Marca da_verificare prenotazioni non completate",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_calendar_sync,
        CronTrigger(minute=0),
        id="calendar_sync",
        name="Riconciliazione eventi Google Calendar",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_nonce_cleanup,
        CronTrigger(hour=4, minute=0),
        id="oauth_nonce_cleanup",
        name="Pulisce nonce OAuth scaduti",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_suspension_notice,
        CronTrigger(hour=8, minute=0),
        id="suspension_notice",
        name="Notifica email org con trial scaduto",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_weekly_report,
        CronTrigger(day_of_week="mon", hour=8, minute=30),
        id="report_settimanale",
        name="Report settimanale PDF via email (tutti i tenant attivi)",
        replace_existing=True,
    )
    _scheduler.start()
    print("[scheduler] Avviato — report 20:00, retention 03:00, reminders every 30min, no-show 23:30, calendar sync every 60min, nonce cleanup 04:00, suspension notice 08:00, report settimanale lun 08:30.")


def ferma_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("[scheduler] Arrestato.")
