#!/usr/bin/env python3
import asyncio
import os
import asyncpg
from src.whatsapp.config import AppConfig
from src.whatsapp.repository import Repository
from src.whatsapp.service import WhatsAppService
from src.whatsapp.retry_worker import RetryWorker


async def main():
    app_config = AppConfig(
        app_secret=os.getenv("META_APP_SECRET", ""),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        postgres_dsn=os.getenv("POSTGRES_DSN", ""),
        verify_token=os.getenv("META_VERIFY_TOKEN", ""),
        max_retry_attempts=5,
    )
    pool = await asyncpg.create_pool(dsn=app_config.postgres_dsn)
    repo = Repository(pool)
    service = WhatsAppService(app_config, repo)
    worker = RetryWorker(app_config, repo, service)
    while True:
        await worker.process_next_batch()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
