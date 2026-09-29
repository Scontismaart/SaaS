"""Process-wide error reporting with privacy-safe defaults."""
import os


def _before_send(event, hint):
    event.pop("user", None)
    request = event.get("request")
    if isinstance(request, dict):
        for key in ("data", "cookies", "headers", "query_string", "env"):
            request.pop(key, None)
    for crumb in event.get("breadcrumbs", {}).get("values", []):
        crumb.pop("data", None)
        if "message" in crumb:
            crumb["message"] = "[redacted]"
    return event


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
    )
    return True
