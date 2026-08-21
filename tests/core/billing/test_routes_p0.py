import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
import httpx
from src.api.main import app

API_KEY = "test-api-key-12345"

@pytest.fixture
async def async_client(repo):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

async def test_cancellation_downgrades_to_readonly(async_client, repo, sample_org):
    import stripe
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
