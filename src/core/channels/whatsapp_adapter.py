from __future__ import annotations

import logging
import uuid
from typing import Any

from src.core.channels.base import ChannelOutboundPort, OutboundSendResult

logger = logging.getLogger(__name__)


class WhatsAppOutboundAdapter(ChannelOutboundPort):
    """Adapter per l'invio outbound di messaggi WhatsApp via Meta Cloud API."""

    def __init__(self, whatsapp_service):
        self.service = whatsapp_service

    async def send_reply(
        self,
        org_id: uuid.UUID | str,
        to_destination: str,
        text: str,
        tenant_config: Any = None,
        handling_type: str = "ai_handled",
    ) -> OutboundSendResult:
        if not to_destination or not tenant_config:
            logger.warning(
                "Impossibile inviare WhatsApp reply: destinatario o tenant_config mancante per org %s",
                org_id,
            )
            return OutboundSendResult(
                success=False,
                channel="whatsapp",
                error="missing_recipient_or_tenant_config",
            )

        payload = {"to": to_destination, "type": "text", "text": {"body": text}}
        try:
            res = await self.service.send_whatsapp_message(
                org_id=org_id,
                to_number=to_destination,
                payload=payload,
                category="service",
                meta_client=None,
                tenant_config=tenant_config,
                handling_type=handling_type,
            )
            wam_id = (res.get("wam_id") or res.get("id")) if isinstance(res, dict) else None
            return OutboundSendResult(
                success=True,
                channel="whatsapp",
                message_id=wam_id,
                wam_id=wam_id,
                raw_response=res if isinstance(res, dict) else {},
            )
        except Exception as e:
            logger.error("Invio risposta WhatsApp fallito per org %s a %s: %s", org_id, to_destination, e)
            raise
