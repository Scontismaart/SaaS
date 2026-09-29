from src.core.observability import _before_send


def test_sentry_payload_strips_request_and_user_pii():
    event = {"user": {"email": "person@example.test"}, "request": {
        "url": "https://app.test/api", "headers": {"authorization": "secret"},
        "cookies": {"session": "secret"}, "data": {"message": "private"},
    }, "breadcrumbs": {"values": [{"message": "private", "data": {"token": "secret"}}]}}
    sanitized = _before_send(event, {})
    assert "user" not in sanitized
    assert sanitized["request"] == {"url": "https://app.test/api"}
    assert sanitized["breadcrumbs"]["values"] == [{"message": "[redacted]"}]
