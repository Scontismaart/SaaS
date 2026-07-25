import asyncio
import logging
import uuid
from src.core.security_logger import security_audit
from src.whatsapp.config import AppConfig

logger = logging.getLogger(__name__)


class InboundProcessor:
    def __init__(self, app_config: AppConfig, repo, service):
        self.app_config = app_config
        self.repo = repo
        self.service = service

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        messages = await self.repo.claim_inbound_messages(limit=10)
        for msg in messages:
            try:
                await self._process_one(msg)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg["id"], e)

    async def _process_one(self, msg: dict):
        org_id = msg["organization_id"]
        text = msg.get("content_text", "")
        content = msg.get("content", {})

        opt_out = await self.service.check_opt_out(text)
        if opt_out["is_opt_out"]:
            from_number = content.get("from", "")
            contact = await self.repo.get_or_create_contact(org_id, from_number)
            await self.repo.record_consent_event(
                contact_id=contact["id"],
                event_type="opt_out",
                method="keyword_match",
                triggering_message_id=msg["id"],
                matched_text=text,
            )
            security_audit("consent_opt_out", contact_id=str(contact["id"]), organization_id=str(org_id))
            await self.repo.update_message_status(msg["id"], "handled")
            return

        fast_reply = await self.service.fast_path_match(text, {})
        if fast_reply:
            await self.repo.update_message_status(msg["id"], "handled")
            return

        logger.info("Message %s requires AI processing (not yet wired)", msg["id"])
        await self.repo.update_message_status(msg["id"], "handled")
