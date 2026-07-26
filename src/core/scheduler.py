import asyncio
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

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
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        wrepo = WhatsAppRepository(pool)
        core_repo = CoreRepository(pool)
        whatsapp = WhatsAppService(None, wrepo)
        service = BookingService(core_repo, whatsapp, None)
        await send_reminders_for_org(service, org["id"])


def _run_reminder_timeout():
    pool = _pool()
    asyncio.run(_reminder_timeout_job(pool))


async def _reminder_timeout_job(pool):
    from src.core.bookings import BookingService
    from src.core.bookings.reminder_job import check_timeouts_for_org
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        core_repo = CoreRepository(pool)
        service = BookingService(core_repo)
        await check_timeouts_for_org(service, org["id"])


def _run_no_show_check():
    pool = _pool()
    asyncio.run(_no_show_check_job(pool))


async def _no_show_check_job(pool):
    from src.core.bookings import BookingService
    from src.core.bookings.no_show_job import mark_da_verificare_for_org
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        core_repo = CoreRepository(pool)
        service = BookingService(core_repo)
        await mark_da_verificare_for_org(service, org["id"])


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
    _scheduler.start()
    print("[scheduler] Avviato — report alle 20:00, retention alle 03:00, booking reminders every 30min, no-show alle 23:30.")


def ferma_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("[scheduler] Arrestato.")
