from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.models.schemas import ReportOutput

# Cache in memoria: chiave = data YYYY-MM-DD, valore = ReportOutput
_report_cache: dict[str, ReportOutput] = {}

_scheduler: BackgroundScheduler | None = None


def _ottieni_storico_ref():
    """Callback impostato da main.py per accedere allo storico senza
    dipendenza circolare. Va chiamato dopo l'avvio."""
    raise RuntimeError(
        "ottieni_storico_ref non impostato. Chiama imposta_fonte_dati()."
    )


_ottieni_storico = _ottieni_storico_ref


def imposta_fonte_dati(callback):
    """Collega lo scheduler allo storico messaggi di main.py."""
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


def _polling_email():
    from src.core.email_config_store import carica_config
    from src.core.email_sources.gmail_api import recupera_nuove_email
    from src.core.documenti.chunking import chunk_testo
    from src.core.documenti.vector_store import aggiungi

    configs = carica_config()
    totale_globale = 0
    for cfg in configs:
        try:
            email = recupera_nuove_email(indirizzo_forzato=cfg["indirizzo"])
        except Exception as e:
            print(f"[scheduler] Polling fallito per {cfg['indirizzo']}: {e}")
            continue
        totale = 0
        for e in email:
            testo = e.corpo_testo
            if not testo:
                continue
            chunks = chunk_testo(testo)
            metadati = [{"fonte": e.oggetto, "tipo": "email"}] * len(chunks)
            totale += aggiungi(chunks, metadati)
        totale_globale += totale

    if totale_globale:
        print(f"[scheduler] Polling email: indicizzati {totale_globale} chunk.")


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


def avvia_polling_email(minuti: int = 5):
    if _scheduler is None:
        return
    _scheduler.add_job(
        _polling_email,
        IntervalTrigger(minutes=minuti),
        id="polling_email",
        name="Controllo nuove email",
        replace_existing=True,
    )
    print(f"[scheduler] Polling email avviato — ogni {minuti} minuti.")


def ferma_polling_email():
    if _scheduler is None:
        return
    if _scheduler.get_job("polling_email"):
        _scheduler.remove_job("polling_email")
        print("[scheduler] Polling email arrestato.")
