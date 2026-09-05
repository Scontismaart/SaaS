#!/usr/bin/env python3
import asyncio
import logging
import os
import asyncpg
from src.whatsapp.config import AppConfig
from src.whatsapp.repository import Repository
from src.whatsapp.service import WhatsAppService
from src.whatsapp.inbound_processor import InboundProcessor
from src.core.bookings import BookingService
from src.core.db.repositories.booking_repo import BookingRepository
from src.core.db.repositories.organization_repo import OrganizationRepository
from src.core.logging_filter import configure_logging

configure_logging(level=logging.INFO)


async def main():
    app_config = AppConfig(
        app_secret=os.getenv("META_APP_SECRET", ""),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        postgres_dsn=os.getenv("DATABASE_URL", ""),
        verify_token=os.getenv("META_VERIFY_TOKEN", ""),
    )
    pool = await asyncpg.create_pool(dsn=app_config.postgres_dsn, min_size=1, max_size=3)
    repo = Repository(pool)
    service = WhatsAppService(app_config, repo)
    # Iniezione dei repository specializzati disaccoppiati
    booking_service = BookingService(
        booking_repo=BookingRepository(pool=pool),
        org_repo=OrganizationRepository(pool=pool),
        repo=BookingRepository(pool=pool),
        whatsapp_service=service,
        app_config=app_config,
    )
    processor = InboundProcessor(app_config, repo, service, booking_service=booking_service)
    while True:
        await processor.process_next_batch()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
