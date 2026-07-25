import pytest
from pydantic import ValidationError
from src.whatsapp.models import (
    IngoingWebhook, StatusEntry, MessageEntry,
    SendTextRequest, SendResponse,
    OutboundTextPayload, OutboundTemplatePayload,
)

class TestIngoingWebhook:
    def test_parse_status_payload(self, status_webhook_fixture):
        webhook = IngoingWebhook.model_validate(status_webhook_fixture)
        assert len(webhook.entry) == 1
        status = webhook.entry[0].changes[0].value.statuses[0]
        assert status.id == "wamid.example"
        assert status.status == "delivered"
        assert status.timestamp == "1712345678"

    def test_parse_message_payload(self, message_webhook_fixture):
        webhook = IngoingWebhook.model_validate(message_webhook_fixture)
        msg = webhook.entry[0].changes[0].value.messages[0]
        assert msg.id == "wamid.inbound.1"
        assert msg.type == "text"
        assert msg.text.body == "Ciao, vorrei prenotare"

    def test_parse_interactive_button_reply(self, button_reply_fixture):
        webhook = IngoingWebhook.model_validate(button_reply_fixture)
        msg = webhook.entry[0].changes[0].value.messages[0]
        assert msg.type == "interactive"
        assert msg.interactive.button_reply.id == "unsubscribe_confirm"

    def test_parse_template_status_update(self, template_status_fixture):
        webhook = IngoingWebhook.model_validate(template_status_fixture)
        assert webhook.entry[0].changes[0].field == "message_template_status_update"
        tsu = webhook.entry[0].changes[0].value
        assert tsu.message_template_name == "promo_welcome"
        assert tsu.message_template_status == "APPROVED"

    def test_invalid_webhook_rejected(self):
        with pytest.raises(ValidationError):
            IngoingWebhook.model_validate({})

    def test_send_text_request_serialization(self):
        req = SendTextRequest(
            messaging_product="whatsapp",
            recipient_type="individual",
            to="391234567890",
            type="text",
            text=OutboundTextPayload(body="Ciao!"),
        )
        data = req.model_dump(exclude_none=True)
        assert data["text"]["body"] == "Ciao!"

    def test_send_response_parse(self):
        resp = SendResponse.model_validate({
            "messaging_product": "whatsapp",
            "contacts": [{"input": "391234567890", "wa_id": "391234567890"}],
            "messages": [{"id": "wamid.outbound.1"}],
        })
        assert resp.messages[0].id == "wamid.outbound.1"
