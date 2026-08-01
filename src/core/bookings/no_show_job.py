from datetime import datetime
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)


async def mark_da_verificare_for_org(service, org_id, org_timezone: str = "Europe/Rome"):
    tz = ZoneInfo(org_timezone)
    today = datetime.now(tz).date()
    bookings = await service.repo.list_bookings_da_verificare(org_id, today)
    marked = []
    for b in bookings:
        try:
            await service.repo.update_booking_status(org_id, b["id"], "da_verificare")
            marked.append(b)
        except Exception as e:
            logger.error("No-show check failed for booking %s: %s", b["id"], e)
    return marked
