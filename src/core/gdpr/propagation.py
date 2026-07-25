import logging
import os

import httpx

logger = logging.getLogger(__name__)


async def propagate_delete_to_airtable(org_id: str) -> bool:
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    if not api_key or not base_id:
        logger.warning("propagation=airtable skipped reason=missing_config org_id=%s", org_id)
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"https://api.airtable.com/v0/{base_id}/organizations/{org_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        logger.info("propagation=airtable org_id=%s status=%d", org_id, resp.status_code)
        return resp.is_success


async def propagate_delete_to_softr(org_id: str) -> bool:
    webhook_url = os.getenv("SOFTR_WEBHOOK_URL")
    api_key = os.getenv("SOFTR_API_KEY")
    if not webhook_url:
        logger.warning("propagation=softr skipped reason=missing_config org_id=%s", org_id)
        return False
    async with httpx.AsyncClient() as client:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = await client.post(
            webhook_url,
            json={"organization_id": org_id, "action": "delete"},
            headers=headers,
        )
        logger.info("propagation=softr org_id=%s status=%d", org_id, resp.status_code)
        return resp.is_success


async def propagate_hard_delete(org_id: str) -> dict:
    results = {
        "airtable": await propagate_delete_to_airtable(org_id),
        "softr": await propagate_delete_to_softr(org_id),
    }
    logger.info("propagation=complete org_id=%s results=%s", org_id, results)
    return results
