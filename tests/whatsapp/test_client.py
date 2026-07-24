import httpx
import respx
import pytest
from uuid import UUID
from src.whatsapp.client import MetaClient
from src.whatsapp.models import SendTextRequest, OutboundTextPayload, SendResponse


@pytest.fixture
def tenant_config():
    from src.whatsapp.config import TenantConfig
    return TenantConfig(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        phone_number_id="1234567890",
        waba_id="waba_1",
        access_token="test_access_token",
        business_profile={},
    )


@pytest.fixture
def text_payload():
    return SendTextRequest(
        messaging_product="whatsapp",
        recipient_type="individual",
        to="391234567890",
        type="text",
        text=OutboundTextPayload(body="Ciao!"),
        biz_opaque_callback_data="msg-uuid-1",
    )


class TestMetaClient:
    @respx.mock
    async def test_send_message_success(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        respx.post(url).respond(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "391234567890", "wa_id": "391234567890"}],
                "messages": [{"id": "wamid.outbound.test"}],
            },
        )
        client = MetaClient(tenant_config)
        response = await client.send_message(text_payload)
        assert isinstance(response, SendResponse)
        assert response.messages[0].id == "wamid.outbound.test"
        await client.close()

    @respx.mock
    async def test_send_message_429_retry_after(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        respx.post(url).respond(429, headers={"Retry-After": "2"}, json={"error": {"message": "Too many requests"}})
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(text_payload)
        await client.close()

    @respx.mock
    async def test_send_message_5xx_retryable(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        mock_route = respx.post(url)
        mock_route.respond(500, json={"error": {"message": "Internal error"}})
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(text_payload)
        assert mock_route.call_count == 2
        await client.close()

    @respx.mock
    async def test_send_message_4xx_not_retried(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        mock_route = respx.post(url)
        mock_route.respond(400, json={"error": {"message": "Bad request"}})
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(text_payload)
        assert mock_route.call_count == 1
        await client.close()

    @respx.mock
    async def test_send_message_timeout(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        respx.post(url).side_effect = httpx.TimeoutException("Request timed out")
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.TimeoutException):
            await client.send_message(text_payload)
        await client.close()
