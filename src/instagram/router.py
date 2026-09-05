import json
import logging
import uuid
from fastapi import APIRouter, Request, Response, HTTPException, Query

from src.whatsapp.config import AppConfig
from src.whatsapp.idempotency import dedup_check
from src.core.channels.inbound.meta_security import MetaWebhookSecurity
from src.instagram.models import InstagramWebhook

logger = logging.getLogger(__name__)

MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB
TIMESTAMP_TOLERANCE = 300  # ±5 minuti per replay check


def create_router(app_config: AppConfig, wrepo, igrepo, security: MetaWebhookSecurity = None):
    """Webhook Instagram DM. La sicurezza (verifica firma HMAC con la stessa
    META_APP_SECRET dell'app Meta, replay protection, body limit) e' gestita
    dal componente centralizzato MetaWebhookSecurity."""
    router = APIRouter(prefix="/webhooks", tags=["instagram"])

    webhook_sec = security or MetaWebhookSecurity(
        app_secret=app_config.app_secret if app_config else "",
        verify_token=app_config.verify_token if app_config else "",
        max_body_size=MAX_BODY_SIZE,
        timestamp_tolerance=TIMESTAMP_TOLERANCE,
    )

    @router.get("/instagram")
    async def verify_webhook(
        hub_mode: str = Query(None, alias="hub.mode"),
        hub_verify_token: str = Query(None, alias="hub.verify_token"),
        hub_challenge: str = Query(None, alias="hub.challenge"),
    ):
        verify_token_configured = app_config.verify_token if app_config else webhook_sec.verify_token
        return webhook_sec.verify_challenge(
            hub_mode=hub_mode,
            hub_verify_token=hub_verify_token,
            hub_challenge=hub_challenge,
            override_token=verify_token_configured,
        )

    @router.post("/instagram")
    async def receive_webhook(request: Request):
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex[:16])
        active_secret = app_config.app_secret if app_config else webhook_sec.app_secret

        body = await webhook_sec.authenticate_and_read(request, override_secret=active_secret)

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        webhook = InstagramWebhook.model_validate(data)
        for entry in webhook.entry:
            for event in entry.messaging:
                await _handle_dm(wrepo, igrepo, entry.id, event, trace_id=trace_id)

        return Response(status_code=200)

    return router


async def _handle_dm(wrepo, igrepo, entry_id, event, trace_id=None):
    """Un DM in arrivo: dedup sul mid, lookup tenant per recipient.id (l'IG
    account del locale), contatto/conversazione canale instagram, messaggio
    inbound in coda per l'InboundProcessor (che e' channel-agnostic)."""
    trace_id = trace_id or uuid.uuid4().hex[:16]
    if event.message is None or event.message.is_echo or not event.message.text:
        return

    mid = event.message.mid
    # Prefisso ig: i mid e i wam_id vivono nella stessa tabella/chiavi
    if not await dedup_check(wrepo.pool, f"ig:{mid}", "message", ""):
        logger.info("mid=%s trace_id=%s action=duplicate_skipped", mid, trace_id)
        return

    ig_user_id = event.recipient.id
    org_data = await igrepo.get_org_by_instagram_user_id(ig_user_id)
    if not org_data:
        logger.warning("Unknown instagram account id: %s", ig_user_id)
        return
    org_id = org_data["organization_id"]

    sender_ig_id = event.sender.id
    contact = await wrepo.get_or_create_contact(org_id, sender_ig_id)
    conv = await wrepo.get_or_create_conversation(org_id, contact["id"], canale="instagram")
    async with wrepo.pool.acquire() as conn:
        async with conn.transaction():
            await wrepo.upsert_message(
                id=uuid.uuid4(),
                organization_id=org_id,
                conversation_id=conv["id"],
                wam_id=f"ig:{mid}",
                direction="inbound",
                message_type="text",
                content={
                    "from": sender_ig_id,
                    "mid": mid,
                    "text": event.message.text,
                    "channel": "instagram",
                },
                content_text=event.message.text,
                status="received_pending_ai",
                conn=conn,
            )
            await wrepo.increment_message_usage(org_id, conn=conn)
