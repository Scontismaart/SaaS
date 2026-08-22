import asyncio
import logging
from datetime import datetime, timedelta, timezone
from src.whatsapp.config import AppConfig

logger = logging.getLogger(__name__)

BACKOFF_SCHEDULE = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
]


class RetryWorker:
    def __init__(self, app_config: AppConfig, repo, service):
        self.app_config = app_config
        self.repo = repo
        self.service = service
        self.max_retries = app_config.max_retry_attempts

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        attempts = await self.repo.claim_delivery_attempts(limit=10)
        for attempt in attempts:
            try:
                await self._process_one(attempt)
            except Exception as e:
                logger.error("Error processing delivery attempt %s: %s", attempt["id"], e)

    async def _process_one(self, attempt: dict):
        message_id = attempt["message_id"]
        payload = await self.repo.reconstruct_payload_for_retry(message_id)
        if not payload:
            await self.repo.update_delivery_attempt(attempt["id"], "failed", {"error": "message not found"})
            return

        org_id = payload["organization_id"]
        from src.whatsapp.config import load_tenant_config
        tenant = await load_tenant_config(org_id, self.app_config, self.repo)

        attempt_num = attempt["attempt_number"]
        try:
            from src.whatsapp.client import MetaClient
            client = MetaClient(tenant)
            result = await self.service.attempt_delivery(
                message_id=message_id,
                phone_number_id=tenant.phone_number_id,
                access_token=tenant.access_token,
                payload=payload.get("content", {}),
                meta_client=client,
            )
            await self.repo.update_delivery_attempt(attempt["id"], "succeeded")
        except Exception as e:
            logger.warning("Delivery attempt %d failed for %s: %s", attempt_num, message_id, e)
            if attempt_num >= self.max_retries:
                await self.repo.update_delivery_attempt(attempt["id"], "failed", {"error": str(e)})
                await self.repo.update_message_status(message_id, "failed", error_code="max_retries",
                                                       error_title=str(e), organization_id=org_id)
            else:
                next_retry = datetime.now(timezone.utc) + BACKOFF_SCHEDULE[min(attempt_num, len(BACKOFF_SCHEDULE) - 1)]
                await self.repo.update_delivery_attempt(attempt["id"], "pending", {"error": str(e)})
                await self.repo.insert_delivery_attempt(message_id, next_retry)
