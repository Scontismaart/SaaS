from uuid import UUID

import pytest
import respx

from src.instagram.client import InstagramClient
from src.instagram.models import IgSendTextRequest
from src.whatsapp.client import MetaClient
from src.whatsapp.config import TenantConfig
from src.whatsapp.models import OutboundTextPayload, SendTextRequest


@pytest.mark.parametrize("channel", ["whatsapp", "instagram"])
@pytest.mark.parametrize("malformed_json", [False, True])
@pytest.mark.asyncio
@respx.mock
async def test_malformed_provider_response_is_not_retried_or_exposed(channel, malformed_json, caplog):
    sentinel = "synthetic-provider-secret"
    route = respx.post("https://graph.facebook.com/v20.0/test-identity/messages")
    if malformed_json:
        route.respond(200, content=sentinel.encode())
    else:
        route.respond(200, json={"unexpected": sentinel})
    if channel == "whatsapp":
        client = MetaClient(TenantConfig(
            organization_id=UUID(int=1), phone_number_id="test-identity",
            waba_id="test-waba", access_token="synthetic-token", business_profile={},
        ))
        payload = SendTextRequest(
            messaging_product="whatsapp", recipient_type="individual", to="123",
            type="text", text=OutboundTextPayload(body="Synthetic test"),
        )
    else:
        client = InstagramClient("test-identity", "synthetic-token")
        payload = IgSendTextRequest(recipient={"id": "123"}, message={"text": "Synthetic test"})
    try:
        with pytest.raises(ValueError) as caught:
            await client.send_message(payload)
        assert route.call_count == 1
        assert sentinel not in str(caught.value)
        assert caught.value.__suppress_context__
        assert sentinel not in caplog.text
    finally:
        await client.close()
