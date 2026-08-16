"""Test del client Graph API Instagram: endpoint, payload e header.
Mock httpx con respx, nessuna rete reale."""
import pytest
import respx
from httpx import Response

from src.instagram.client import InstagramClient
from src.instagram.models import IgSendTextRequest


@pytest.fixture
def client():
    c = InstagramClient(ig_user_id="17841400000000099", access_token="IGQ-token")
    yield c


class TestInstagramClient:
    @respx.mock
    async def test_send_message_payload_and_url(self, client):
        route = respx.post("https://graph.facebook.com/v20.0/17841400000000099/messages").mock(
            return_value=Response(200, json={"recipient_id": "123456789", "message_id": "mid.out.1"})
        )
        payload = IgSendTextRequest(recipient={"id": "123456789"}, message={"text": "Certo!"})
        response = await client.send_message(payload)

        assert route.called
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer IGQ-token"
        import json as _json
        body = _json.loads(request.content)
        assert body == {"recipient": {"id": "123456789"}, "message": {"text": "Certo!"}}

        assert response.recipient_id == "123456789"
        assert response.message_id == "mid.out.1"

    @respx.mock
    async def test_send_message_error_400_no_retry(self, client):
        route = respx.post("https://graph.facebook.com/v20.0/17841400000000099/messages").mock(
            return_value=Response(400, json={"error": {"message": "bad recipient"}})
        )
        with pytest.raises(Exception):
            await client.send_message(
                IgSendTextRequest(recipient={"id": "x"}, message={"text": "y"})
            )
        assert route.call_count == 1  # 4xx non e' retryable

    async def test_close(self, client):
        await client.close()
