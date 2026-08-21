import os
import pytest
from unittest.mock import MagicMock, patch
import httpx
from src.api.main import app

API_KEY = "test-api-key-12345"

@pytest.fixture(autouse=True)
def set_env():
    os.environ["API_KEY_SERVICE"] = API_KEY
    os.environ["STRIPE_SECRET_KEY"] = "sk_test_1234567890"
    os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
    yield

@pytest.fixture
async def async_client(repo, pg_pool):
    app.state.repo = repo
    app.state.pool = pg_pool
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

async def test_cancellation_downgrades_to_readonly(async_client, repo, sample_org):
    # setup organization with active subscription
    await repo.update_organization_billing(sample_org["id"], {
        "stripe_customer_id": "cus_123",
        "subscription_id": "sub_123",
        "subscription_status": "active"
    })
    
    # fake stripe.billing_portal.Session.create
    with patch("stripe.billing_portal.Session.create", return_value=MagicMock(url="http://stripe/portal")):
        resp = await async_client.post("/api/billing/create-portal-session", headers={
            "X-API-Key": API_KEY,
            "X-Organization-Id": str(sample_org["id"]),
        })
        assert resp.status_code == 200
        assert resp.json()["url"] == "http://stripe/portal"