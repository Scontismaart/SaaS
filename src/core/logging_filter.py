"""Filtro di redazione PII per i log applicativi.

Design: NON scarta righe di log (a differenza della vecchia implementazione
allow-list, che eliminava silenziosamente qualunque riga non in formato
key=value con chiavi whitelisted -- inutilizzabile con lo stile di logging
realmente in uso nel repo, in gran parte testo libero con interpolazione
%s). Questo filtro invece maschera i pattern PII riconosciuti (email,
numeri di telefono in formato E.164) dentro il testo del messaggio gia'
renderizzato, e lascia sempre passare la riga.

Limite dichiarato: la redazione e' basata su regex, quindi e' un
mitigamento (difesa in profondita'), non una garanzia assoluta. Non
riconosce numeri di telefono senza prefisso "+" (es. wa_id/phone_number_id
di Meta, spesso solo cifre) perche' un pattern del genere colliderebbe con
troppi identificativi tecnici legittimi (timestamp epoch, ID numerici) e
comprometterebbe l'osservabilita' piu' di quanto protegga. Per una
redazione completa, lo standard di riferimento resta il logging
strutturato (campi separati, non testo libero) nei punti che maneggiano
dati del contatto.
"""

import logging
import re

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_E164_RE = re.compile(r"(?<!\d)\+\d{8,15}(?!\d)")

EMAIL_REDACTED = "[email redatta]"
PHONE_REDACTED = "[telefono redatto]"


def redact_pii(text: str) -> str:
    """Maschera email e numeri di telefono E.164 in una stringa di log."""
    text = _EMAIL_RE.sub(EMAIL_REDACTED, text)
    text = _PHONE_E164_RE.sub(PHONE_REDACTED, text)
    return text

class PIIRedactionFilter(logging.Filter):
    """Maschera PII nel testo gia' renderizzato del record di log.

    A differenza di un filtro allow-list, ritorna sempre True: non scarta
    mai una riga di log, la modifica sul posto (record.msg) dopo aver
    applicato l'interpolazione %-style, cosi' da coprire sia
    logger.info("...%s...", valore) sia logger.info(stringa_gia_pronta).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        redacted = redact_pii(rendered)
        record.msg = redacted
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configura il root logger con redazione PII attiva.

    Idempotente: se il root logger ha gia' handler configurati da questa
    funzione (marcati), non li duplica. Va chiamata una sola volta per
    processo, il piu' presto possibile in ciascun entrypoint (API, worker).
    """
    root = logging.getLogger()
    if getattr(root, "_pii_redaction_configured", False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(PIIRedactionFilter())

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root._pii_redaction_configured = True
