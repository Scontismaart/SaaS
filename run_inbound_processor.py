#!/usr/bin/env python3
import asyncio
import os
import asyncpg
from src.whatsapp.config import AppConfig
from src.whatsapp.repository import Repository
from src.whatsapp.service import WhatsAppService
from src.whatsapp.inbound_processor import InboundProcessor
from src.core.bookings import BookingService
from src.core.db.repository import CoreRepository


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
    # Senza questo, self.booking_service resta None nel worker reale: ne'
    # la creazione prenotazione da risposta AI ne' la gestione risposta ai
    # reminder (conferma/cancella) scattano mai in produzione, pur essendo
    # implementate correttamente in InboundProcessor.
    booking_service = BookingService(
        repo=CoreRepository(pool=pool),
        whatsapp_service=service,
        app_config=app_config,
    )
    processor = InboundProcessor(app_config, repo, service, booking_service=booking_service)
    while True:
        await processor.process_next_batch()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
