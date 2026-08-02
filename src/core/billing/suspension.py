"""Stato di sospensione org — derivato, mai memorizzato.

is_org_suspended() calcola lo stato dalla sola verita' canonica
(subscription_status + trial_end su organizations). Non c'e' colonna
dedicata: aggiungerne una significherebbe un secondo posto dove lo stato
puo' disallinearsi dai dati di billing.

La colonna suspension_notified_at NON fa parte di questo: e' un fatto
storico ("ho gia' mandato la mail?"), non derivabile, e viene gestita
separatamente dal webhook e dal job trial.
"""

from datetime import datetime, timezone


def is_org_suspended(subscription_status: str | None, trial_end=None) -> bool:
    """True se l'org non puo' usare il pipeline conversazionale.

    - canceled: sempre sospesa.
    - trial_end scaduto: sospesa solo se lo status NON e' active/past_due.
      Un'org pagante puo' avere un trial_end residuo nel passato: trattarla
      come sospesa sarebbe un falso positivo che bloccherebbe il servizio
      che sta effettivamente pagando.
    """
    if subscription_status == "canceled":
        return True
    if subscription_status in ("active", "past_due"):
        return False
    if not trial_end:
        return False
    if isinstance(trial_end, datetime) and trial_end.tzinfo is None:
        trial_end = trial_end.replace(tzinfo=timezone.utc)
    return trial_end <= datetime.now(timezone.utc)
