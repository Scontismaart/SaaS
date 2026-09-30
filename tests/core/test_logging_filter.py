import logging

from src.core.logging_filter import (
    PIIRedactionFilter,
    configure_logging,
    redact_pii,
    redact_sensitive_text,
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


def _uvicorn_access_record(target: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "uvicorn/protocols/http/h11_impl.py",
        466,
        '%s - "%s %s HTTP/1.1" %d',
        ("192.0.2.10:1234", "GET", target, status),
        None,
    )


def test_redact_sensitive_text_handles_case_encoded_names_and_keeps_safe_fields():
    text = (
        "GET /api/auth/google/callback?%63ode=SYNTHETIC_CODE"
        "&CODE=SYNTHETIC_DUPLICATE&StAtE=SYNTHETIC_STATE&lang=it"
    )
    safe = redact_sensitive_text(text)

    assert "/api/auth/google/callback" in safe
    assert "lang=it" in safe
    assert "[REDACTED]" in safe
    assert all(
        value not in safe
        for value in ("SYNTHETIC_CODE", "SYNTHETIC_DUPLICATE", "SYNTHETIC_STATE")
    )


def test_redaction_covers_generic_and_mfa_enrollment_secrets():
    text = (
        "secret=SYNTHETIC_GENERIC_SECRET "
        "totp_secret=SYNTHETIC_TOTP_SECRET "
        "mfa_secret=SYNTHETIC_MFA_SECRET "
        "enrollment_secret=SYNTHETIC_ENROLLMENT_SECRET "
        "qr_code=SYNTHETIC_QR_CODE "
        "otpauth_url=SYNTHETIC_OTP_URI"
    )
    safe = redact_sensitive_text(text)

    assert all(
        marker not in safe
        for marker in (
            "SYNTHETIC_GENERIC_SECRET",
            "SYNTHETIC_TOTP_SECRET",
            "SYNTHETIC_MFA_SECRET",
            "SYNTHETIC_ENROLLMENT_SECRET",
            "SYNTHETIC_QR_CODE",
            "SYNTHETIC_OTP_URI",
        )
    )

    record = _make_record("mfa setup completed")
    record.auth_context = {
        "secret": "SYNTHETIC_STRUCTURED_SECRET",
        "totp_secret": "SYNTHETIC_STRUCTURED_TOTP",
        "qr_code": "SYNTHETIC_STRUCTURED_QR",
    }
    PIIRedactionFilter().filter(record)
    assert "SYNTHETIC" not in repr(record.auth_context)


def test_uvicorn_callback_success_error_and_malformed_records_are_redacted():
    cases = (
        (
            (
                "/api/auth/google/callback?code=SYNTHETIC_SUCCESS_CODE"
                "&StAtE=SYNTHETIC_SUCCESS_STATE&lang=it"
            ),
            302,
            ("SYNTHETIC_SUCCESS_CODE", "SYNTHETIC_SUCCESS_STATE"),
        ),
        (
            (
                "/api/auth/google/callback?error_description=SYNTHETIC_PROVIDER_ERROR"
                "&state=SYNTHETIC_ERROR_STATE"
            ),
            302,
            ("SYNTHETIC_PROVIDER_ERROR", "SYNTHETIC_ERROR_STATE"),
        ),
        (
            (
                "/api/auth/google/callback?code=SYNTHETIC_BAD_CODE"
                "&CODE_VERIFIER=SYNTHETIC_VERIFIER&code_challenge=SYNTHETIC_CHALLENGE"
                "&ACCESS_TOKEN=SYNTHETIC_ACCESS&refresh_token=SYNTHETIC_REFRESH"
                "&id_token=SYNTHETIC_ID&token=SYNTHETIC_TOKEN"
                "&authorization=SYNTHETIC_AUTHORIZATION"
                "&client_secret=SYNTHETIC_CLIENT_SECRET&password=SYNTHETIC_PASSWORD"
            ),
            302,
            (
                "SYNTHETIC_BAD_CODE", "SYNTHETIC_VERIFIER", "SYNTHETIC_CHALLENGE",
                "SYNTHETIC_ACCESS", "SYNTHETIC_REFRESH", "SYNTHETIC_ID",
                "SYNTHETIC_TOKEN", "SYNTHETIC_AUTHORIZATION",
                "SYNTHETIC_CLIENT_SECRET", "SYNTHETIC_PASSWORD",
            ),
        ),
    )
    redactor = PIIRedactionFilter()

    for target, status, canaries in cases:
        record = _uvicorn_access_record(target, status)
        assert redactor.filter(record)
        rendered = record.getMessage()
        assert 'GET /api/auth/google/callback' in rendered
        assert f' {status}' in rendered
        assert all(value not in rendered for value in canaries)
    assert "lang=it" in redact_sensitive_text(cases[0][0])


def test_redaction_covers_error_trace_headers_and_structured_extra():
    try:
        raise RuntimeError(
            "exchange failed ?code=SYNTHETIC_EXCEPTION_CODE"
            "&state=SYNTHETIC_EXCEPTION_STATE"
        )
    except RuntimeError:
        import sys

        exc_info = sys.exc_info()

    record = logging.LogRecord(
        "uvicorn.error",
        logging.ERROR,
        "routes.py",
        12,
        'request body={"password":"SYNTHETIC_PASSWORD"}',
        (),
        exc_info,
    )
    record.auth_context = {
        "refreshToken": "SYNTHETIC_REFRESH_TOKEN",
        "operation": "google_callback",
    }
    record.headers = {
        "Cookie": "wa_at=SYNTHETIC_COOKIE; wa_rt=SYNTHETIC_COOKIE_RT",
        "Authorization": "Bearer SYNTHETIC_BEARER_TOKEN",
    }

    PIIRedactionFilter().filter(record)
    rendered = logging.Formatter().format(record)

    assert 'request body=' in rendered
    assert '"password":"[REDACTED]"' in rendered
    assert "google_callback" in record.auth_context["operation"]
    assert "SYNTHETIC" not in rendered
    assert "SYNTHETIC" not in repr(record.auth_context)
    assert "SYNTHETIC" not in repr(record.headers)


def test_configure_logging_disables_raw_uvicorn_access_but_keeps_errors():
    configure_logging()
    access_logger = logging.getLogger("uvicorn.access")
    error_logger = logging.getLogger("uvicorn.error")
    assert access_logger.disabled is True
    assert error_logger.disabled is False
    assert any(isinstance(item, PIIRedactionFilter) for item in error_logger.filters)


def test_formatting_failure_suppresses_raw_message_and_still_redacts_extra():
    class Unformattable:
        def __str__(self):
            raise RuntimeError("SYNTHETIC_FORMAT_FAILURE")

    record = _make_record("password=%s", Unformattable())
    record.refresh_token = "SYNTHETIC_EXTRA_TOKEN"

    PIIRedactionFilter().filter(record)

    assert "SYNTHETIC" not in logging.Formatter().format(record)
    assert record.refresh_token == "[REDACTED]"
