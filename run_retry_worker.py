#!/usr/bin/env python3
import asyncio
import logging
import os
import asyncpg
from src.whatsapp.config import AppConfig
from src.whatsapp.repository import Repository
from src.whatsapp.service import WhatsAppService
from src.whatsapp.retry_worker import RetryWorker
from src.core.logging_filter import configure_logging

configure_logging(level=logging.INFO)


async def main():
    app_config = AppConfig(
        app_secret=os.getenv("META_APP_SECRET", ""),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        postgres_dsn=os.getenv("DATABASE_URL", ""),
        verify_token=os.getenv("META_VERIFY_TOKEN", ""),
        max_retry_attempts=5,
    )
    pool = await asyncpg.create_pool(dsn=app_config.postgres_dsn, min_size=1, max_size=3)
    repo = Repository(pool)
    service = WhatsAppService(app_config, repo)
    worker = RetryWorker(app_config, repo, service)
    while True:
        await worker.process_next_batch()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
