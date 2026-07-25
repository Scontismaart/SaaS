import hashlib
import hmac
import json
import logging
import uuid
from fastapi import APIRouter, Request, Response, HTTPException, Query
from src.whatsapp.config import AppConfig
from src.whatsapp.models import IngoingWebhook

logger = logging.getLogger(__name__)


def create_router(app_config: AppConfig, repo):
    router = APIRouter(prefix="/webhooks", tags=["whatsapp"])

    @router.get("/whatsapp")
    async def verify_webhook(
        hub_mode: str = Query(None, alias="hub.mode"),
        hub_verify_token: str = Query(None, alias="hub.verify_token"),
        hub_challenge: str = Query(None, alias="hub.challenge"),
    ):
        if hub_mode == "subscribe" and hub_verify_token == app_config.verify_token:
            return Response(content=hub_challenge, media_type="text/plain")
        raise HTTPException(status_code=403, detail="Verify token mismatch")

    @router.post("/whatsapp")
    async def receive_webhook(request: Request):
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_hmac(body, signature, app_config.app_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        webhook = IngoingWebhook.model_validate(data)
        for entry in webhook.entry:
            for change in entry.changes:
                value = change.value
                if change.field == "message_template_status_update":
                    await _handle_template_status_update(repo, value, entry_id=entry.id)
                    continue

                pid = None
                if value.metadata and value.metadata.phone_number_id:
                    pid = value.metadata.phone_number_id
                if not pid:
                    continue
                org_data = await repo.get_org_by_phone_number_id(pid)
                if not org_data:
                    logger.warning("Unknown phone_number_id: %s", pid)
                    continue
                org_id = org_data["organization_id"]

                if value.statuses:
                    for status in value.statuses:
                        await _handle_status_update(repo, org_id, status)
                if value.messages:
                    for msg in value.messages:
                        await _handle_inbound_message(repo, org_id, msg, value.contacts)

        return Response(status_code=200)

    return router


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def _handle_status_update(repo, org_id, status):
    wam_id = status.id
    new_status = status.status
    biz_data = getattr(status, "biz_opaque_callback_data", None)
    errors = getattr(status, "errors", None)

    if wam_id:
        updated = await repo.update_message_status_by_wam_id(
            wam_id, new_status,
            error_code=str(errors[0]["code"]) if errors else None,
            error_title=errors[0]["title"] if errors else None,
            error_details=errors,
        )
        if updated:
            return

    if biz_data:
        await repo.update_message_status(
            uuid.UUID(biz_data), new_status,
            wam_id=wam_id,
            error_code=str(errors[0]["code"]) if errors else None,
            error_title=errors[0]["title"] if errors else None,
            error_details=errors,
        )


async def _handle_inbound_message(repo, org_id, msg, contacts):
    contact_name = contacts[0].profile.name if contacts and contacts[0].profile else None
    from_number = msg.from_
    contact = await repo.get_or_create_contact(org_id, from_number)
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    await repo.upsert_message(
        id=uuid.uuid4(),
        organization_id=org_id,
        conversation_id=conv["id"],
        wam_id=msg.id,
        direction="inbound",
        message_type=msg.type,
        content=msg.model_dump(exclude_none=True),
        content_text=msg.text.body if msg.text else None,
        status="received_pending_ai",
    )


async def _handle_template_status_update(repo, value, entry_id=None):
    waba_id = entry_id
    if waba_id:
        org_data = await repo.get_org_by_waba_id(waba_id)
    else:
        org_data = None
    if not org_data:
        logger.warning("Unknown waba_id for template status update: %s", waba_id)
        return
    await repo.update_template_status(
        name=value.message_template_name,
        language=value.message_template_language,
        status=value.message_template_status,
        reason=getattr(value, "reason", None),
        organization_id=org_data["organization_id"],
    )
