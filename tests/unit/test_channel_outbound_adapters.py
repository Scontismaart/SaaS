import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.channels.base import OutboundSendResult
from src.core.channels.whatsapp_adapter import WhatsAppOutboundAdapter
from src.core.channels.instagram_adapter import InstagramOutboundAdapter
from src.core.channels.router import OutboundChannelRouter


@pytest.mark.asyncio
async def test_whatsapp_adapter_missing_recipient_or_config():
    service = AsyncMock()
    adapter = WhatsAppOutboundAdapter(service)

    # Missing recipient
    res1 = await adapter.send_reply(uuid.uuid4(), "", "Test", tenant_config=MagicMock())
    assert res1.success is False
    assert res1.error == "missing_recipient_or_tenant_config"

    # Missing config
    res2 = await adapter.send_reply(uuid.uuid4(), "+393401122334", "Test", tenant_config=None)
    assert res2.success is False
    assert res2.error == "missing_recipient_or_tenant_config"

    service.send_whatsapp_message.assert_not_called()


@pytest.mark.asyncio
async def test_whatsapp_adapter_success():
    service = AsyncMock()
    service.send_whatsapp_message.return_value = {"wam_id": "meta-msg-999"}
    adapter = WhatsAppOutboundAdapter(service)

    org_id = uuid.uuid4()
    tenant_cfg = MagicMock()

    res = await adapter.send_reply(
        org_id=org_id,
        to_destination="+393401122334",
        text="Ciao dal test!",
        tenant_config=tenant_cfg,
        handling_type="ai_handled",
    )

    assert res.success is True
    assert res.channel == "whatsapp"
    assert res.wam_id == "meta-msg-999"
    service.send_whatsapp_message.assert_awaited_once_with(
        org_id=org_id,
        to_number="+393401122334",
        payload={"to": "+393401122334", "type": "text", "text": {"body": "Ciao dal test!"}},
        category="service",
        meta_client=None,
        tenant_config=tenant_cfg,
        handling_type="ai_handled",
        idempotency_key=None,
    )


@pytest.mark.asyncio
async def test_whatsapp_adapter_exception_propagates():
    service = AsyncMock()
    service.send_whatsapp_message.side_effect = RuntimeError("Meta network failure")
    adapter = WhatsAppOutboundAdapter(service)

    with pytest.raises(RuntimeError, match="Meta network failure"):
        await adapter.send_reply(
            org_id=uuid.uuid4(),
            to_destination="+393401122334",
            text="Fail test",
            tenant_config=MagicMock(),
        )


@pytest.mark.asyncio
async def test_instagram_adapter_missing_recipient():
    repo = MagicMock()
    adapter = InstagramOutboundAdapter(repo, "mock_enc_key")

    res = await adapter.send_reply(uuid.uuid4(), "", "Ciao IG")
    assert res.success is False
    assert res.channel == "instagram"
    assert res.error == "missing_recipient"


@pytest.mark.asyncio
async def test_instagram_adapter_not_configured():
    repo = MagicMock()
    repo.pool = None
    adapter = InstagramOutboundAdapter(repo, "mock_enc_key")

    with patch("src.instagram.config.load_instagram_config", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = None
        res = await adapter.send_reply(uuid.uuid4(), "ig_user_123", "Ciao IG")
        assert res.success is False
        assert res.error == "instagram_not_configured"


@pytest.mark.asyncio
async def test_instagram_adapter_success():
    repo = MagicMock()
    repo.pool = None
    adapter = InstagramOutboundAdapter(repo, "mock_enc_key")

    with patch("src.instagram.config.load_instagram_config", new_callable=AsyncMock) as mock_load, \
         patch("src.instagram.service.InstagramService.send_instagram_message", new_callable=AsyncMock) as mock_send:

        mock_load.return_value = MagicMock()
        mock_send.return_value = {"message_id": "ig-msg-777"}

        org_id = uuid.uuid4()
        res = await adapter.send_reply(org_id, "ig_user_123", "Risposta IG")

        assert res.success is True
        assert res.channel == "instagram"
        assert res.message_id == "ig-msg-777"
        mock_send.assert_awaited_once_with(
            org_id=org_id,
            to_ig_id="ig_user_123",
            text="Risposta IG",
            ig_config=mock_load.return_value,
            handling_type="ai_handled",
        )


def test_outbound_channel_router():
    wa_adapter = MagicMock()
    ig_adapter = MagicMock()
    router = OutboundChannelRouter({"whatsapp": wa_adapter, "instagram": ig_adapter})

    assert router.get_adapter("whatsapp") is wa_adapter
    assert router.get_adapter("WHATSAPP") is wa_adapter
    assert router.get_adapter("instagram") is ig_adapter
    assert router.get_adapter(None) is wa_adapter
    assert router.get_adapter("unknown_channel") is wa_adapter
