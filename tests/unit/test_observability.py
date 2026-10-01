from src.core.observability import (
    _before_send,
    _before_send_transaction,
    configure_error_reporting,
)


def test_sentry_payload_strips_request_and_user_pii():
    event = {"user": {"email": "person@example.test"}, "request": {
        "url": "https://app.test/api", "headers": {"authorization": "secret"},
        "cookies": {"session": "secret"}, "data": {"message": "private"},
    }, "breadcrumbs": {"values": [{"message": "private", "data": {"token": "secret"}}]}}
    sanitized = _before_send(event, {})
    assert "user" not in sanitized
    assert sanitized["request"] == {"url": "https://app.test/api"}
    assert sanitized["breadcrumbs"]["values"] == [{"message": "[redacted]"}]


def test_sentry_error_and_transaction_drop_auth_query_and_redact_nested_values():
    event = {
        "request": {
            "url": (
                "https://app.test/api/auth/google/callback?"
                "code=SYNTHETIC_CODE&state=SYNTHETIC_STATE"
            ),
            "query_string": "code=SYNTHETIC_CODE",
            "data": {"password": "SYNTHETIC_PASSWORD"},
            "headers": {"Cookie": "wa_at=SYNTHETIC_COOKIE"},
        },
        "exception": {
            "values": [{"value": "failure code=SYNTHETIC_EXCEPTION_CODE"}]
        },
        "extra": {"access_token": "SYNTHETIC_ACCESS_TOKEN"},
    }
    transaction = {
        "request": {
            "url": "https://app.test/api/auth/google/callback?CoDe=SYNTHETIC_TX_CODE"
        },
        "contexts": {"auth": {"refreshToken": "SYNTHETIC_REFRESH_TOKEN"}},
    }

    sanitized_error = _before_send(event, {})
    sanitized_transaction = _before_send_transaction(transaction, {})

    assert sanitized_error["request"]["url"] == "https://app.test/api/auth/google/callback"
    assert sanitized_transaction["request"]["url"] == "https://app.test/api/auth/google/callback"
    assert "SYNTHETIC" not in repr(sanitized_error)
    assert "SYNTHETIC" not in repr(sanitized_transaction)


def test_sentry_drops_url_userinfo_before_error_or_transaction_reporting():
    event = {
        "request": {
            "url": (
                "https://qa_user:SYNTHETIC_USERINFO_SECRET@app.test:443/"
                "api/auth/google/callback?code=SYNTHETIC_CODE"
            )
        }
    }
    expected = "https://app.test:443/api/auth/google/callback"

    for scrubber in (_before_send, _before_send_transaction):
        sanitized = scrubber(event, {})
        assert sanitized["request"]["url"] == expected
        assert "SYNTHETIC" not in repr(sanitized)


def test_sentry_drops_malformed_url_instead_of_exposing_userinfo():
    event = {
        "request": {
            "url": "https://qa_user:SYNTHETIC_PASSWORD@[broken/api?code=SYNTHETIC_CODE"
        }
    }

    for scrubber in (_before_send, _before_send_transaction):
        sanitized = scrubber(event, {})
        assert sanitized["request"]["url"] == "[REDACTED]"
        assert "SYNTHETIC" not in repr(sanitized)


def test_sentry_registers_scrubber_for_errors_and_transactions(monkeypatch):
    import sentry_sdk

    captured = {}
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.test/1")
    monkeypatch.setattr(sentry_sdk, "init", lambda **options: captured.update(options))

    assert configure_error_reporting() is True
    assert captured["before_send"] is _before_send
    assert captured["before_send_transaction"] is _before_send_transaction
