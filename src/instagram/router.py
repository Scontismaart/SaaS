import hmac
import json
import logging
import time
import uuid
from fastapi import APIRouter, Request, Response, HTTPException, Query

from src.whatsapp.config import AppConfig
from src.whatsapp.idempotency import dedup_check
from src.whatsapp.router import _read_limited_body, _verify_hmac
from src.instagram.models import InstagramWebhook

logger = logging.getLogger(__name__)

MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB
TIMESTAMP_TOLERANCE = 300  # ±5 minuti per replay check


def create_router(app_config: AppConfig, wrepo, igrepo):
    """Webhook Instagram DM. La sicurezza (verifica firma HMAC con la stessa
    META_APP_SECRET dell'app Meta, replay protection, body limit) e' riusata
    da src.whatsapp.router: stessa piattaforma Meta, stesse garanzie."""
    router = APIRouter(prefix="/webhooks", tags=["instagram"])

    @router.get("/instagram")
    async def verify_webhook(
        hub_mode: str = Query(None, alias="hub.mode"),
        hub_verify_token: str = Query(None, alias="hub.verify_token"),
        hub_challenge: str = Query(None, alias="hub.challenge"),
    ):
        verify_token_configured = app_config.verify_token or ""
        if (hub_mode == "subscribe"
                and verify_token_configured
                and hmac.compare_digest(hub_verify_token or "", verify_token_configured)):
            return Response(content=hub_challenge, media_type="text/plain")
        raise HTTPException(status_code=403, detail="Verify token mismatch")

    @router.post("/instagram")
    async def receive_webhook(request: Request):
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex[:16])
        client_ip = request.client.host if request.client else "unknown"
        signature = request.headers.get("X-Hub-Signature-256", "")
        timestamp_str = request.headers.get("X-Timestamp", "")

        if timestamp_str:
            try:
                ts = int(timestamp_str)
                if abs(time.time() - ts) > TIMESTAMP_TOLERANCE:
                    logger.warning("webhook_timestamp_rejected ip=%s path=%s", client_ip, request.url.path)
                    raise HTTPException(status_code=403, detail="Timestamp out of tolerance")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid X-Timestamp")

        body = await _read_limited_body(request, MAX_BODY_SIZE)

        if not _verify_hmac(body, signature, app_config.app_secret):
            logger.warning(
                json.dumps({
                    "event": "webhook_hmac_rejected",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ip": client_ip,
                    "path": request.url.path,
                    "reason": "signature_mismatch",
                })
            )
            raise HTTPException(status_code=403, detail="Invalid signature")

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
