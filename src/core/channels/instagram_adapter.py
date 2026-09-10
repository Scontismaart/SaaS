from __future__ import annotations

import logging
import uuid
from typing import Any

from src.core.channels.base import ChannelOutboundPort, OutboundSendResult

logger = logging.getLogger(__name__)


class InstagramOutboundAdapter(ChannelOutboundPort):
    """Adapter per l'invio outbound di messaggi Instagram Direct Message via Graph API."""

    def __init__(self, repo, encryption_key: str):
        self.repo = repo
        self.encryption_key = encryption_key

    async def send_reply(
        self,
        org_id: uuid.UUID | str,
        to_destination: str,
        text: str,
        tenant_config: Any = None,
        handling_type: str = "ai_handled",
        idempotency_key: str | None = None,  # accettata per interfaccia; IG fuori scope P1.2
    ) -> OutboundSendResult:
        if not to_destination:
            logger.warning(
                "Impossibile inviare Instagram reply: destinatario mancante per org %s",
                org_id,
            )
            return OutboundSendResult(
                success=False,
                channel="instagram",
                error="missing_recipient",
            )

        from src.instagram.config import load_instagram_config
        from src.instagram.repository import InstagramRepository
        from src.instagram.service import InstagramService

        try:
            pool = getattr(self.repo, "pool", None)
            ig_repo = InstagramRepository(pool) if pool else self.repo
            ig_config = await load_instagram_config(org_id, self.encryption_key, ig_repo)
            if not ig_config:
                logger.warning(
                    "Org %s: account Instagram non configurato, risposta AI non inviata",
                    org_id,
                )
                return OutboundSendResult(
                    success=False,
                    channel="instagram",
                    error="instagram_not_configured",
                )

            res = await InstagramService(self.repo).send_instagram_message(
                org_id=org_id,
                to_ig_id=to_destination,
                text=text,
                ig_config=ig_config,
                handling_type=handling_type,
            )
            msg_id = (
                res.get("message_id")
                or res.get("wam_id")
                or res.get("id")
                if isinstance(res, dict)
                else None
            )
            return OutboundSendResult(
                success=True,
                channel="instagram",
                message_id=msg_id,
                wam_id=msg_id,
                raw_response=res if isinstance(res, dict) else {},
            )
        except Exception as e:
            logger.error(
                "Invio risposta AI Instagram fallito per org %s a %s: %s",
                org_id,
                to_destination,
                e,
            )
            raise
