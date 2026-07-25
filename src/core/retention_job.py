import logging

logger = logging.getLogger(__name__)


async def run_retention(pool):
    from src.whatsapp.repository import Repository

    repo = Repository(pool=pool)
    expired = await repo.delete_expired_messages(retention_days=60)
    purged = await repo.purge_soft_deleted_messages(grace_days=30)
    cleaned = await repo.cleanup_empty_conversations()
    logger.info("Retention: %d expired soft-deleted, %d purged, %d empty conversations cleaned", expired, purged, cleaned)
