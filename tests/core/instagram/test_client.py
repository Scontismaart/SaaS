"""Test del client Graph API Instagram: endpoint, payload e header.
Mock httpx con respx, nessuna rete reale."""
import pytest
import respx
import httpx
from httpx import Response
from tenacity import wait_none

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

    @pytest.mark.parametrize(
        ("failure", "expected_calls"),
        [("timeout", 1), (500, 1), (401, 1), (403, 1), (429, 3)],
    )
    @respx.mock
    async def test_send_message_retry_policy_and_sanitized_logs(
        self, client, failure, expected_calls, caplog, monkeypatch
    ):
        monkeypatch.setattr(InstagramClient.send_message.retry, "wait", wait_none())
        caplog.set_level("WARNING")
        route = respx.post(
            "https://graph.facebook.com/v20.0/17841400000000099/messages"
        )
        if failure == "timeout":
            route.mock(side_effect=httpx.ReadTimeout("private-token-and-body"))
            expected_exception = httpx.ReadTimeout
        else:
            route.respond(
                failure,
                json={"error": {"message": "private-token-and-body"}},
            )
            expected_exception = httpx.HTTPStatusError

        with pytest.raises(expected_exception):
            await client.send_message(
                IgSendTextRequest(recipient={"id": "x"}, message={"text": "y"})
            )

        assert route.call_count == expected_calls
        assert all("private-token-and-body" not in record.message for record in caplog.records)
        await client.close()

    async def test_close(self, client):
        await client.close()
