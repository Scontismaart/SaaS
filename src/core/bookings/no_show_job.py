from datetime import date
import logging

logger = logging.getLogger(__name__)


async def mark_da_verificare_for_org(service, org_id):
    today = date.today()
    bookings = await service.repo.list_bookings_da_verificare(org_id, today)
    marked = []
    for b in bookings:
        try:
            await service.repo.update_booking_status(org_id, b["id"], "da_verificare")
            marked.append(b)
        except Exception as e:
            logger.error("No-show check failed for booking %s: %s", b["id"], e)
    return marked
