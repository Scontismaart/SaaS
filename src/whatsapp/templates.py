import logging
import uuid
import httpx
from src.whatsapp.config import AppConfig

logger = logging.getLogger(__name__)


class TemplateSyncer:
    BASE_URL = "https://graph.facebook.com/v20.0"

    def __init__(self, app_config: AppConfig, repo):
        self.app_config = app_config
        self.repo = repo

    async def pull_sync(self, waba_id: str, org_id: uuid.UUID):
        access_token = await self._get_access_token(org_id)
        url = f"{self.BASE_URL}/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            for tpl in data.get("data", []):
                await self.repo.upsert_template(
                    organization_id=org_id,
                    name=tpl["name"],
                    language=tpl.get("language", "it"),
                    category=tpl.get("category", "MARKETING"),
                    status=tpl.get("status", "PENDING"),
                    components=tpl.get("components", []),
                )

    async def process_push_update(self, event: dict):
        status = event.get("message_template_status", "PENDING")
        await self.repo.update_template_status(
            name=event.get("message_template_name"),
            language=event.get("message_template_language"),
            status=status,
            reason=event.get("reason"),
        )

    async def _get_access_token(self, org_id: uuid.UUID) -> str:
        from src.whatsapp.config import load_tenant_config
        tenant = await load_tenant_config(org_id, self.app_config, self.repo)
        return tenant.access_token
