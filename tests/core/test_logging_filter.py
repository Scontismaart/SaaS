import logging

from src.core.logging_filter import (
    PIIRedactionFilter,
    configure_logging,
    redact_pii,
)


def _make_record(msg: str, *args) -> logging.LogRecord:
    logger = logging.getLogger("test")
    return logger.makeRecord(
        logger.name, logging.INFO, "test.py", 1, msg, args, None
    )


def test_redact_pii_masks_email():
    assert redact_pii("contatto: mario.rossi@gmail.com") == "contatto: [email redatta]"


def test_redact_pii_masks_phone_e164():
    assert redact_pii("from=+393401234567") == "from=[telefono redatto]"


def test_redact_pii_leaves_free_text_untouched():
    testo = "Ciao Mario, il tuo tavolo e' pronto alle 20:00"
    assert redact_pii(testo) == testo


def test_redact_pii_leaves_technical_ids_untouched():
    # ID/timestamp senza "+" non devono essere confusi con un telefono:
    # una redazione troppo aggressiva romperebbe l'osservabilita' (vedi
    # docstring del modulo). Solo il formato E.164 con "+" viene mascherato.
    testo = "duration_ms=1734000000 attempt=3"
    assert redact_pii(testo) == testo

def test_filter_never_drops_free_text():
    # Il difetto della vecchia PIIWhitelistFilter: scartava qualunque riga
    # non in formato key=value. Qui verifichiamo l'opposto: non deve MAI
    # scartare, solo redigere.
    f = PIIRedactionFilter()
    record = _make_record("Ciao Mario, il tuo tavolo e' pronto alle 20:00")
    assert f.filter(record) is True


def test_filter_never_drops_empty_message():
    f = PIIRedactionFilter()
    record = _make_record("")
    assert f.filter(record) is True


def test_filter_redacts_phone_from_args():
    f = PIIRedactionFilter()
    record = _make_record("from=%s", "+393401234567")
    f.filter(record)
    assert record.getMessage() == "from=[telefono redatto]"


def test_filter_redacts_email_from_args():
    f = PIIRedactionFilter()
    record = _make_record("user=%s", "mario.rossi@gmail.com")
    f.filter(record)
    assert record.getMessage() == "user=[email redatta]"


def test_configure_logging_idempotent():
    root = logging.getLogger()
    handlers_before = list(root.handlers)
    configure_logging()
    count_after_first = len(root.handlers)
    configure_logging()
    assert len(root.handlers) == count_after_first
    root.handlers = handlers_before


def test_configure_logging_attaches_pii_filter():
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers.clear()
    root._pii_redaction_configured = False
    try:
        configure_logging()
        assert any(
            isinstance(f, PIIRedactionFilter)
            for h in root.handlers
            for f in h.filters
        )
    finally:
        root.handlers = saved
