"""MFA BFF routes: cookie-only auth, TOTP lifecycle and token confinement."""

import json
import time

import httpx
import pytest
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from src.core.auth import bff
from src.core.auth.csrf import validate_csrf_request
from src.core.auth.denylist import clear_memory_denylist, is_token_revoked
from src.core.auth.routes import _set_session_cookies
from src.core.auth.routes import router as auth_router

pytestmark = pytest.mark.asyncio

USER_ID = "11111111-1111-4111-8111-111111111111"
FACTOR_ID = "22222222-2222-4222-8222-222222222222"
CHALLENGE_ID = "33333333-3333-4333-8333-333333333333"
OLD_ACCESS = "old-access-session-marker"
OLD_REFRESH = "old-refresh-session-marker"
NEW_ACCESS = "new-access-session-marker"
NEW_REFRESH = "new-refresh-session-marker"
QR_SECRET = "totp-secret-marker"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    clear_memory_denylist()
    monkeypatch.setenv("SUPABASE_URL", "https://stage-test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://test")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "memory")
    yield
    clear_memory_denylist()


@pytest.fixture
async def client(monkeypatch):
    app = FastAPI()
    app.include_router(auth_router)

    @app.middleware("http")
    async def mfa_no_store(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/auth/mfa"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.middleware("http")
    async def csrf(request, call_next):
        ok, detail = validate_csrf_request(request)
        if not ok:
            return JSONResponse(status_code=403, content={"detail": detail})
        return await call_next(request)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


def _session_headers(*, csrf=True, extra=None):
    headers = {"Cookie": f"wa_at={OLD_ACCESS}; wa_rt={OLD_REFRESH}"}
    if csrf:
        headers.update({"Origin": "http://test", "X-CSRF-Token": "csrf-test-token"})
        headers["Cookie"] += "; wa_csrf=csrf-test-token"
    if extra:
        headers.update(extra)
    return headers


def _jwt_claims(token):
    if token == NEW_ACCESS:
        return {"sub": USER_ID, "aal": "aal2", "amr": [{"method": "password", "timestamp": int(time.time())}]}
    return {"sub": USER_ID, "aal": "aal1", "amr": [{"method": "password", "timestamp": int(time.time())}]}


def _fake_jwt(monkeypatch):
    async def verify(token, **_kwargs):
        return _jwt_claims(token)

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)


def _mock_auth_client(monkeypatch, handler, seen=None):
    requests = seen if seen is not None else []

    async def capture(request):
        requests.append(request)
        result = handler(request)
        if isinstance(result, httpx.Response):
            return result
        status, body = result
        content = json.dumps(body).encode() if body is not None else b""
        return httpx.Response(status, content=content, headers={"content-type": "application/json"})

    auth_client = httpx.AsyncClient(transport=httpx.MockTransport(capture))

    async def get_client():
        return auth_client

    monkeypatch.setattr(bff, "_client", get_client)
    return auth_client, requests


def _user(factors=None):
    return {"id": USER_ID, "factors": factors or []}


def _factor(status="verified"):
    return {"id": FACTOR_ID, "factor_type": "totp", "friendly_name": "Authenticator", "status": status}


async def test_status_is_cookie_only_sanitized_and_not_cacheable(client, monkeypatch):
    _fake_jwt(monkeypatch)
    auth_client, requests = _mock_auth_client(
        monkeypatch,
        lambda req: (200, _user([_factor()])),
    )
    try:
        response = await client.get("/api/auth/mfa", headers=_session_headers(csrf=False))
    finally:
        await auth_client.aclose()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json() == {
        "aal": "aal1",
        "factors": [{"id": FACTOR_ID, "friendly_name": "Authenticator", "status": "verified"}],
    }
    assert "Authorization" in requests[0].headers
    assert OLD_ACCESS not in response.text
    assert OLD_REFRESH not in response.text


async def test_mfa_routes_reject_authorization_and_api_key_overrides(client, monkeypatch):
    _fake_jwt(monkeypatch)
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: (200, _user()))
    try:
        for header in ({"Authorization": "Bearer override"}, {"X-API-Key": "override"}):
            response = await client.get("/api/auth/mfa", headers=_session_headers(csrf=False, extra=header))
            assert response.status_code == 400
    finally:
        await auth_client.aclose()
    assert not requests


async def test_enrollment_returns_qr_and_secret_no_store_without_logging(client, monkeypatch, caplog):
    _fake_jwt(monkeypatch)
    bodies = iter([
        (200, _user()),
        (200, {
            "id": FACTOR_ID,
            "type": "totp",
            "totp": {"qr_code": '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', "secret": QR_SECRET},
        }),
    ])
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: next(bodies))
    try:
        response = await client.post("/api/auth/mfa/enroll", headers=_session_headers())
    finally:
        await auth_client.aclose()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["factor_id"] == FACTOR_ID
    assert response.json()["qr_code"].startswith("data:image/svg+xml;base64,")
    assert response.json()["secret"] == QR_SECRET
    assert requests[1].url.path.endswith("/factors")
    assert json.loads(requests[1].content)["factor_type"] == "totp"
    assert QR_SECRET not in caplog.text


async def test_enrollment_blocks_duplicate_verified_and_pending_factors(client, monkeypatch):
    _fake_jwt(monkeypatch)
    auth_client, requests = _mock_auth_client(
        monkeypatch,
        lambda _req: (200, _user([_factor("verified"), _factor("unverified")])),
    )
    try:
        response = await client.post("/api/auth/mfa/enroll", headers=_session_headers())
    finally:
        await auth_client.aclose()
    assert response.status_code == 409
    assert len(requests) == 1


async def test_enrollment_requires_recent_authentication(client, monkeypatch):
    async def verify(_token, **_kwargs):
        return {"sub": USER_ID, "aal": "aal1", "amr": [
            {"method": "token_refresh", "timestamp": int(time.time())},
            {"method": "password", "timestamp": int(time.time()) - 301},
        ]}

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: (200, _user()))
    try:
        response = await client.post("/api/auth/mfa/enroll", headers=_session_headers())
    finally:
        await auth_client.aclose()
    assert response.status_code == 428
    assert "esci e accedi di nuovo" in response.json()["detail"]
    assert not requests


async def test_enrollment_accepts_fresh_oauth_amr(client, monkeypatch):
    async def verify(_token, **_kwargs):
        return {"sub": USER_ID, "aal": "aal1", "amr": [{"method": "oauth", "timestamp": int(time.time())}]}

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)
    bodies = iter([
        (200, _user()),
        (200, {
            "id": FACTOR_ID,
            "type": "totp",
            "totp": {"qr_code": '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0"/></svg>', "secret": QR_SECRET},
        }),
    ])
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: next(bodies))
    try:
        response = await client.post("/api/auth/mfa/enroll", headers=_session_headers())
    finally:
        await auth_client.aclose()
    assert response.status_code == 200
    assert len(requests) == 2


async def test_enrollment_rejects_nonfinite_auth_method_timestamp(client, monkeypatch):
    async def verify(_token, **_kwargs):
        return {"sub": USER_ID, "aal": "aal1", "amr": [{"method": "password", "timestamp": float("nan")}]}

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: (200, _user()))
    try:
        response = await client.post("/api/auth/mfa/enroll", headers=_session_headers())
    finally:
        await auth_client.aclose()
    assert response.status_code == 428
    assert not requests


@pytest.mark.parametrize("amr", [
    [{"method": [], "timestamp": int(time.time())}],
    [{"method": "password", "timestamp": 10**10000}],
])
async def test_enrollment_rejects_malformed_auth_method_claims(client, monkeypatch, amr):
    async def verify(_token, **_kwargs):
        return {"sub": USER_ID, "aal": "aal1", "amr": amr}

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: (200, _user()))
    try:
        response = await client.post("/api/auth/mfa/enroll", headers=_session_headers())
    finally:
        await auth_client.aclose()
    assert response.status_code == 428
    assert not requests


async def test_challenge_and_wrong_or_expired_code_are_sanitized(client, monkeypatch):
    _fake_jwt(monkeypatch)
    bodies = iter([
        (200, _user([_factor()])),
        (200, {"id": CHALLENGE_ID}),
        (200, _user([_factor()])),
        (422, {"msg": "raw provider error secret-data"}),
    ])
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: next(bodies))
    try:
        challenge = await client.post(
            "/api/auth/mfa/challenge",
            json={"factor_id": FACTOR_ID},
            headers=_session_headers(),
        )
        verify = await client.post(
            "/api/auth/mfa/verify",
            json={"factor_id": FACTOR_ID, "challenge_id": CHALLENGE_ID, "code": "000000"},
            headers=_session_headers(),
        )
    finally:
        await auth_client.aclose()
    assert challenge.status_code == 200
    assert challenge.json() == {"challenge_id": CHALLENGE_ID}
    assert verify.status_code == 422
    assert "raw provider error" not in verify.text
    assert "secret-data" not in verify.text
    assert verify.headers["cache-control"] == "no-store, private"
    assert requests[1].url.path.endswith(f"/factors/{FACTOR_ID}/challenge")


async def test_verify_promotes_same_user_and_sets_only_httponly_session_cookies(client, monkeypatch):
    _fake_jwt(monkeypatch)
    bodies = iter([
        (200, _user([_factor()])),
        (200, {
            "access_token": NEW_ACCESS,
            "refresh_token": NEW_REFRESH,
            "user": {"id": USER_ID},
            "expires_in": 3600,
        }),
    ])
    auth_client, _requests = _mock_auth_client(monkeypatch, lambda _req: next(bodies))
    try:
        response = await client.post(
            "/api/auth/mfa/verify",
            json={"factor_id": FACTOR_ID, "challenge_id": CHALLENGE_ID, "code": "123456"},
            headers=_session_headers(),
        )
    finally:
        await auth_client.aclose()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["aal"] == "aal2"
    assert NEW_ACCESS not in response.text
    assert NEW_REFRESH not in response.text
    assert OLD_ACCESS not in response.text
    assert OLD_REFRESH not in response.text
    cookies = response.headers.get_list("set-cookie")
    assert any(item.startswith("wa_at=") and "HttpOnly" in item for item in cookies)
    assert any(item.startswith("wa_rt=") and "HttpOnly" in item for item in cookies)
    assert any(item.startswith("wa_csrf=") and "HttpOnly" not in item for item in cookies)
    assert await is_token_revoked(OLD_ACCESS)
    assert await is_token_revoked(OLD_REFRESH)


async def test_production_session_cookies_are_secure_and_host_only(monkeypatch):
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "true")
    response = Response()
    _set_session_cookies(response, {
        "access_token": "opaque-access-test-value",
        "refresh_token": "opaque-refresh-test-value",
    })

    cookies = response.headers.getlist("set-cookie")
    assert len(cookies) == 2
    for cookie in cookies:
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Domain=" not in cookie


async def test_verify_rejects_unexpected_identity_or_non_aal2_session(client, monkeypatch):
    async def verify(token, **_kwargs):
        if token == NEW_ACCESS:
            return {"sub": "other-user", "aal": "aal1"}
        return {"sub": USER_ID, "aal": "aal1"}

    monkeypatch.setattr("src.core.auth.dependencies.verify_supabase_jwt", verify)
    bodies = iter([
        (200, _user([_factor()])),
        (200, {"access_token": NEW_ACCESS, "refresh_token": NEW_REFRESH, "user": {"id": USER_ID}}),
    ])
    auth_client, _requests = _mock_auth_client(monkeypatch, lambda _req: next(bodies))
    try:
        response = await client.post(
            "/api/auth/mfa/verify",
            json={"factor_id": FACTOR_ID, "challenge_id": CHALLENGE_ID, "code": "123456"},
            headers=_session_headers(),
        )
    finally:
        await auth_client.aclose()
    assert response.status_code == 502
    assert await is_token_revoked(NEW_ACCESS)
    assert await is_token_revoked(NEW_REFRESH)


async def test_cancel_deletes_only_owned_unverified_totp(client, monkeypatch):
    _fake_jwt(monkeypatch)
    bodies = iter([
        (200, _user([_factor("unverified")])),
        (204, None),
    ])
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: next(bodies))
    try:
        response = await client.delete(
            f"/api/auth/mfa/factors/{FACTOR_ID}",
            headers=_session_headers(),
        )
    finally:
        await auth_client.aclose()
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert requests[1].method == "DELETE"
    assert requests[1].url.path.endswith(f"/factors/{FACTOR_ID}")


async def test_cancel_refuses_verified_factor(client, monkeypatch):
    _fake_jwt(monkeypatch)
    auth_client, requests = _mock_auth_client(
        monkeypatch,
        lambda _req: (200, _user([_factor("verified")])),
    )
    try:
        response = await client.delete(
            f"/api/auth/mfa/factors/{FACTOR_ID}",
            headers=_session_headers(),
        )
    finally:
        await auth_client.aclose()
    assert response.status_code == 409
    assert len(requests) == 1


async def test_mfa_mutations_require_csrf_cookie_and_origin(client, monkeypatch):
    _fake_jwt(monkeypatch)
    auth_client, requests = _mock_auth_client(monkeypatch, lambda _req: (200, _user()))
    try:
        response = await client.post(
            "/api/auth/mfa/enroll",
            headers={"Cookie": f"wa_at={OLD_ACCESS}; wa_rt={OLD_REFRESH}"},
        )
    finally:
        await auth_client.aclose()
    assert response.status_code == 403
    assert not requests
