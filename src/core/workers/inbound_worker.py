from __future__ import annotations

import logging
from typing import Any

from src.core.inbound.service import InboundProcessingService

logger = logging.getLogger(__name__)


class InboundWorker:
    """
    Worker puro dedicato al background polling e alla gestione dei claim su DB.
    Completamente disaccoppiato dalla logica di business e dai canali di messaggistica.
    """

    def __init__(
        self,
        repo: Any,
        inbound_service: InboundProcessingService,
        batch_size: int = 10,
    ):
        self.repo = repo
        self.inbound_service = inbound_service
        self.batch_size = batch_size

    async def process_next_batch(self):
        """Esegue il reaper dei claim pendenti/scaduti e preleva il prossimo batch atomico."""
        await self.repo.reap_stale_claims()
        messages = await self.repo.claim_inbound_messages(limit=self.batch_size)
        for msg in messages:
            try:
                await self.inbound_service.process_message(msg)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg.get("id"), e)
