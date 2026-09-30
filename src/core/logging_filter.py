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
from collections.abc import Mapping
from urllib.parse import unquote_plus, urlsplit, urlunsplit

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_E164_RE = re.compile(r"(?<!\d)\+\d{8,15}(?!\d)")

EMAIL_REDACTED = "[email redatta]"
PHONE_REDACTED = "[telefono redatto]"
SENSITIVE_VALUE_REDACTED = "[REDACTED]"

SENSITIVE_PARAMETER_NAMES = frozenset(
    {
        "access_token", "refresh_token", "id_token", "token", "authorization",
        "authorization_code", "client_secret", "code", "state", "code_verifier",
        "code_challenge", "password", "current_password", "new_password",
        "old_password", "password_confirmation", "error_description", "token_hash",
        "provider_token", "provider_refresh_token", "auth_token", "api_key",
        "secret", "secret_key", "totp_secret", "mfa_secret",
        "enrollment_secret", "qr_code", "totp_uri", "otpauth_url",
        "x_api_key", "cookie", "set_cookie", "csrf_token", "x_csrf_token",
        "otp", "totp", "mfa_code", "recovery_code", "session", "nonce",
        "oauth_code", "oauth_state", "oauth_verifier", "oauth_next",
        "pkce_verifier", "pkce_challenge", "wa_oauth_verifier", "wa_oauth_next",
        "wa_at", "wa_rt", "wa_csrf", "session_cookie", "access_cookie",
        "refresh_cookie",
    }
)
_SENSITIVE_KEY_ALIASES = SENSITIVE_PARAMETER_NAMES | {
    name.replace("_", "") for name in SENSITIVE_PARAMETER_NAMES
}
_KEY_VALUE_RE = re.compile(
    r"(?P<boundary>^|[?&;,{ \t])(?P<key_quote>['\"]?)(?P<key>[A-Za-z0-9_%+.-]+)"
    r"(?P=key_quote)(?P<separator>\s*[:=]\s*)"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s&;,{}\[\]]+)"
)
_SENSITIVE_HEADER_RE = re.compile(
    r"(?im)(?P<boundary>^|[\s{,])"
    r"(?P<header>(?:authorization|proxy-authorization|cookie|set-cookie|"
    r"x-api-key|api-key|x-csrf-token)\s*:\s*)[^\r\n]*"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
)
_ABSOLUTE_HTTP_URL_RE = re.compile(r"\bhttps?://[^\s<>\"']+", re.IGNORECASE)
_HTTP_REQUEST_TARGET_RE = re.compile(
    r"\b(?P<method>GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD)\s+"
    r"(?P<target>/[^\s<>\"']+)",
    re.IGNORECASE,
)
_LOG_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def redact_pii(text: str) -> str:
    """Maschera email e numeri di telefono E.164 in una stringa di log."""
    text = _EMAIL_RE.sub(EMAIL_REDACTED, text)
    text = _PHONE_E164_RE.sub(PHONE_REDACTED, text)
    return text


def _normalize_sensitive_key(name: object) -> str:
    raw = unquote_plus(str(name)).strip()
    return re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").casefold()


def _is_sensitive_key(name: object) -> bool:
    return _normalize_sensitive_key(name) in _SENSITIVE_KEY_ALIASES


def redact_sensitive_text(text: str) -> str:
    """Redact sensitive names case-insensitively, including URL-encoded keys."""
    # Redact complete URL query strings before key=value parsing. Otherwise
    # the generic parser can consume ``http://host/path?code=...`` as the
    # harmless-looking pair ``http=//host/path?code=...`` and miss the code.
    text = _ABSOLUTE_HTTP_URL_RE.sub(
        lambda match: _sanitize_logged_url(match.group(0)), text
    )
    text = _HTTP_REQUEST_TARGET_RE.sub(
        lambda match: f"{match.group('method')} {_sanitize_logged_url(match.group('target'))}",
        text,
    )

    def replace_header(match: re.Match) -> str:
        return f"{match.group('boundary')}{match.group('header')}{SENSITIVE_VALUE_REDACTED}"

    def replace_key_value(match: re.Match) -> str:
        if not _is_sensitive_key(match.group("key")):
            return match.group(0)
        value = match.group("value")
        quote = value[0] if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0] else ""
        safe_value = f"{quote}{SENSITIVE_VALUE_REDACTED}{quote}"
        return (
            f"{match.group('boundary')}{match.group('key_quote')}{match.group('key')}"
            f"{match.group('key_quote')}{match.group('separator')}{safe_value}"
        )

    text = _SENSITIVE_HEADER_RE.sub(replace_header, text)
    text = _KEY_VALUE_RE.sub(replace_key_value, text)
    text = _BEARER_RE.sub(f"Bearer {SENSITIVE_VALUE_REDACTED}", text)
    text = _JWT_RE.sub(SENSITIVE_VALUE_REDACTED, text)
    return redact_pii(text)


def redact_sensitive_value(value, *, key: object | None = None):
    """Recursively redact structured log/event values by sensitive field name."""
    if key is not None and _is_sensitive_key(key):
        return SENSITIVE_VALUE_REDACTED
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, BaseException):
        return redact_sensitive_text(str(value))
    if isinstance(value, Mapping):
        return {
            item_key: redact_sensitive_value(item_value, key=item_key)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_value(item) for item in value)
    return value


def sanitize_telemetry_url(url: str) -> str:
    """Preserve host/path without URL credentials, query, or fragment."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return SENSITIVE_VALUE_REDACTED
    authority = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, authority, parts.path, "", ""))


def _sanitize_logged_url(url: str) -> str:
    """Redact sensitive URL query values while preserving safe parameters."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return SENSITIVE_VALUE_REDACTED

    query_parts = re.split(r"([&;])", parts.query)
    for index in range(0, len(query_parts), 2):
        key, separator, _value = query_parts[index].partition("=")
        if separator and _is_sensitive_key(key):
            query_parts[index] = f"{key}={SENSITIVE_VALUE_REDACTED}"

    authority = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit(
        (parts.scheme, authority, parts.path, "".join(query_parts), "")
    )

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
        except Exception:  # noqa: BLE001 - a formatting failure must fail closed
            record.msg = "[log redatto: impossibile formattare il messaggio in sicurezza]"
            record.args = ()
        else:
            record.msg = redact_sensitive_text(rendered)
            record.args = ()

        if record.exc_info:
            try:
                exception_text = logging.Formatter().formatException(record.exc_info)
                record.exc_text = redact_sensitive_text(exception_text)
            except Exception:  # noqa: BLE001 - never emit an unredacted traceback
                record.exc_text = "[traceback redatto]"
        elif record.exc_text:
            record.exc_text = redact_sensitive_text(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_sensitive_text(record.stack_info)

        for key, value in tuple(record.__dict__.items()):
            if key not in _LOG_RECORD_FIELDS:
                record.__dict__[key] = redact_sensitive_value(value, key=key)
        return True


def _ensure_redaction_filter(logger: logging.Logger) -> None:
    if not any(isinstance(item, PIIRedactionFilter) for item in logger.filters):
        logger.addFilter(PIIRedactionFilter())
    for handler in logger.handlers:
        if not any(isinstance(item, PIIRedactionFilter) for item in handler.filters):
            handler.addFilter(PIIRedactionFilter())


def configure_logging(level: int = logging.INFO) -> None:
    """Configura il root logger con redazione PII attiva.

    Idempotente: se il root logger ha gia' handler configurati da questa
    funzione (marcati), non li duplica. Va chiamata una sola volta per
    processo, il piu' presto possibile in ciascun entrypoint (API, worker).
    """
    root = logging.getLogger()
    if not getattr(root, "_pii_redaction_configured", False):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        handler.addFilter(PIIRedactionFilter())

        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(level)
        root._pii_redaction_configured = True

    # Uvicorn's access logger receives the raw request target, including
    # OAuth query values. Disable it at source even for manual CLI launches
    # that omit --no-access-log; keep Uvicorn errors available.
    logging.getLogger("uvicorn.access").disabled = True
    for logger_name in ("uvicorn.error", "httpx", "httpx2"):
        _ensure_redaction_filter(logging.getLogger(logger_name))
