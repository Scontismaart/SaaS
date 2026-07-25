from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.models.schemas import ReportOutput

_report_cache: dict[str, ReportOutput] = {}
_scheduler: BackgroundScheduler | None = None


def _ottieni_storico_ref():
    raise RuntimeError("ottieni_storico_ref non impostato. Chiama imposta_fonte_dati().")


_ottieni_storico = _ottieni_storico_ref


def imposta_fonte_dati(callback):
    global _ottieni_storico
    _ottieni_storico = callback


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
    _scheduler.start()
    print("[scheduler] Avviato — job giornaliero alle 20:00.")


def ferma_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        print("[scheduler] Arrestato.")
