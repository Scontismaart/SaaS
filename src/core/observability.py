"""Process-wide error reporting with privacy-safe defaults."""
import os

from src.core.logging_filter import redact_sensitive_value, sanitize_telemetry_url


def _sanitize_event(event):
    if not isinstance(event, dict):
        return event
    source = event
    request = event.get("request")
    if isinstance(request, dict) and isinstance(request.get("url"), str):
        # Strip URL userinfo before text redaction can replace its @ separator.
        source = {
            **event,
            "request": {
                **request,
                "url": sanitize_telemetry_url(request["url"]),
            },
        }
    safe_event = redact_sensitive_value(source)
    safe_event.pop("user", None)
    request = safe_event.get("request")
    if isinstance(request, dict):
        for key in ("data", "cookies", "headers", "query_string", "env"):
            request.pop(key, None)
    breadcrumbs = safe_event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
        if isinstance(values, list):
            for crumb in values:
                if isinstance(crumb, dict):
                    crumb.pop("data", None)
                    if "message" in crumb:
                        crumb["message"] = "[redacted]"
    return safe_event


def _before_send(event, hint):
    return _sanitize_event(event)


def _before_send_transaction(event, hint):
    return _sanitize_event(event)


def configure_error_reporting() -> bool:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    import sentry_sdk
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        profiles_sample_rate=0.0,
        before_send=_before_send,
        before_send_transaction=_before_send_transaction,
    )
    return True
