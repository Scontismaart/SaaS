import os
from unittest.mock import MagicMock
import pytest
from starlette.datastructures import Headers

from src.core.auth.csrf import (
    _allowed_origins,
    _request_origin,
    _same_origin,
    validate_csrf_request,
    issue_csrf_token,
    clear_csrf_token,
    csrf_cookie_name,
    CSRF_COOKIE,
    CSRF_HEADER,
)


def _make_request(
    method="POST",
    path="/api/bookings",
    headers=None,
    cookies=None,
):
    req = MagicMock()
    req.method = method
    req.url.path = path
    req.headers = Headers(headers or {})
    req.cookies = cookies or {}
    return req


from src.core.auth.bff import access_cookie_name


def test_csrf_exempt_methods():
    req = _make_request(method="GET", cookies={access_cookie_name(): "token"})
    ok, err = validate_csrf_request(req)
    assert ok is True
    assert err is None


def test_csrf_exempt_paths():
    req = _make_request(method="POST", path="/api/auth/login", cookies={access_cookie_name(): "token"})
    ok, err = validate_csrf_request(req)
    assert ok is True
    assert err is None


def test_csrf_api_key_exempt():
    req = _make_request(
        method="POST",
        path="/api/bookings",
        headers={"x-api-key": "secret-key"},
        cookies={access_cookie_name(): "token"},
    )
    ok, err = validate_csrf_request(req)
    assert ok is True
    assert err is None


def test_csrf_bearer_exempt():
    req = _make_request(
        method="POST",
        path="/api/bookings",
        headers={"authorization": "Bearer jwt-token"},
        cookies={access_cookie_name(): "token"},
    )
    ok, err = validate_csrf_request(req)
    assert ok is True
    assert err is None


def test_csrf_public_app_url_in_allowed_origins(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "http://localhost:8080")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    origins = _allowed_origins()
    assert "http://localhost:8080" in origins
    assert "http://localhost:5173" in origins


def test_csrf_same_origin_direct_match():
    req = _make_request(headers={"host": "localhost:8080"})
    assert _same_origin(req, "http://localhost:8080") is True


def test_csrf_same_origin_forwarded_host():
    req = _make_request(headers={"host": "api:8000", "x-forwarded-host": "localhost:8080"})
    assert _same_origin(req, "http://localhost:8080") is True


def test_csrf_same_origin_hostname_fallback():
    req = _make_request(headers={"host": "localhost"})
    assert _same_origin(req, "http://localhost:8080") is True


def test_csrf_different_origin_fails_same_origin():
    req = _make_request(headers={"host": "localhost:8080"})
    assert _same_origin(req, "http://external-site.com") is False


def test_csrf_valid_mutation(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080")
    csrf_token = "valid-token-12345"
    req = _make_request(
        method="POST",
        path="/api/bookings",
        headers={
            "origin": "http://localhost:8080",
            CSRF_HEADER: csrf_token,
        },
        cookies={
            access_cookie_name(): "session-jwt",
            csrf_cookie_name(): csrf_token,
        },
    )
    ok, err = validate_csrf_request(req)
    assert ok is True
    assert err is None


def test_csrf_untrusted_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    csrf_token = "valid-token-12345"
    req = _make_request(
        method="POST",
        path="/api/bookings",
        headers={
            "origin": "http://other-site.com",
            "host": "localhost:8000",
            CSRF_HEADER: csrf_token,
        },
        cookies={
            access_cookie_name(): "session-jwt",
            csrf_cookie_name(): csrf_token,
        },
    )
    ok, err = validate_csrf_request(req)
    assert ok is False
    assert err == "Origine richiesta non valida"


def test_csrf_mismatched_token(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:8080")
    req = _make_request(
        method="POST",
        path="/api/bookings",
        headers={
            "origin": "http://localhost:8080",
            CSRF_HEADER: "wrong-token",
        },
        cookies={
            access_cookie_name(): "session-jwt",
            csrf_cookie_name(): "valid-token",
        },
    )
    ok, err = validate_csrf_request(req)
    assert ok is False
    assert err == "CSRF token non valido"
