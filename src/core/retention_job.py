import logging

logger = logging.getLogger(__name__)


async def run_retention(pool):
    from src.whatsapp.repository import Repository
    from src.whatsapp.idempotency import purge_webhook_idempotency

    repo = Repository(pool=pool)
    expired = await repo.delete_expired_messages(retention_days=60)
    purged = await repo.purge_soft_deleted_messages(grace_days=30)
    cleaned = await repo.cleanup_empty_conversations()
    simulation_purged = await repo.purge_simulation_requests(retention_days=30)
    webhook_purged = await purge_webhook_idempotency(pool, days=7)
    logger.info(
        "Retention: %d expired soft-deleted, %d purged, %d empty conversations cleaned, %d simulator records purged, %d webhook idempotency records purged",
        expired, purged, cleaned, simulation_purged, webhook_purged,
    )
