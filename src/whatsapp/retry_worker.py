from __future__ import annotations

import logging
from typing import Any
from src.whatsapp.config import AppConfig
from src.core.workers.retry_worker import MultiChannelRetryWorker, BACKOFF_SCHEDULE

logger = logging.getLogger(__name__)


class RetryWorker:
    """
    WhatsApp-specific facade delegating directly to MultiChannelRetryWorker.
    Maintained for full backwards-compatibility.
    """

    def __init__(
        self,
        app_config: AppConfig,
        repo: Any,
        service: Any = None,
        channel_router: Any = None,
    ):
        self.app_config = app_config
        self.repo = repo
        self.service = service
        self.channel_router = channel_router
        self._worker = MultiChannelRetryWorker(
            app_config=app_config,
            repo=repo,
            service=service,
            channel_router=channel_router,
        )
        self.max_retries = self._worker.max_retries

    async def process_next_batch(self):
        return await self._worker.process_next_batch()

    async def _process_one(self, attempt: dict):
        return await self._worker._process_one(attempt)
