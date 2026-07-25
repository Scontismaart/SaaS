import os
import pytest
import httpx
from unittest.mock import patch, MagicMock

API_KEY = "test-api-key-12345"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["DATABASE_URL"] = ""
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo):
    from src.api.main import app
    app.state.repo = repo
    app.state.pool = MagicMock()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_create_checkout_session_no_auth(async_client):
    resp = await async_client.post("/api/billing/create-checkout-session", json={
        "plan": "starter",
        "success_url": "http://localhost:5173/success",
        "cancel_url": "http://localhost:5173/cancel",
    })
    assert resp.status_code == 401


async def test_create_checkout_session_invalid_key(async_client):
    resp = await async_client.post("/api/billing/create-checkout-session", json={
        "plan": "starter",
        "success_url": "http://localhost:5173/success",
        "cancel_url": "http://localhost:5173/cancel",
    }, headers={"X-API-Key": "invalid"})
    assert resp.status_code == 403


async def test_create_checkout_session_bad_plan(async_client, sample_org):
    resp = await async_client.post("/api/billing/create-checkout-session", json={
        "plan": "nonexistent",
        "success_url": "http://localhost:5173/success",
        "cancel_url": "http://localhost:5173/cancel",
    }, headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 400


async def test_get_subscription_authenticated(async_client, sample_org):
    resp = await async_client.get("/api/billing/subscription", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["subscription_status"] == "incomplete"
    assert data["messages_used_this_period"] == 0


async def test_get_usage_authenticated(async_client, sample_org):
    resp = await async_client.get("/api/billing/usage", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["messages_used"] == 0
    assert data["percentage"] == 0


async def test_create_portal_session_no_customer(async_client, sample_org):
    resp = await async_client.post("/api/billing/create-portal-session", headers={
        "X-API-Key": API_KEY,
        "X-Organization-Id": str(sample_org["id"]),
    })
    assert resp.status_code == 400
    assert "No Stripe customer found" in resp.json()["detail"]
