import hashlib
import hmac
import json
import logging
import time
import uuid
from fastapi import APIRouter, Request, Response, HTTPException, Query
from src.whatsapp.config import AppConfig
from src.whatsapp.models import IngoingWebhook
from src.whatsapp.idempotency import dedup_check

logger = logging.getLogger(__name__)

MAX_BODY_SIZE = 5 * 1024 * 1024  # 5 MB
TIMESTAMP_TOLERANCE = 300  # ±5 minuti per replay check


def create_router(app_config: AppConfig, repo):
    router = APIRouter(prefix="/webhooks", tags=["whatsapp"])

    @router.get("/whatsapp")
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

    @router.post("/whatsapp")
    async def receive_webhook(request: Request):
        trace_id = getattr(request.state, "trace_id", uuid.uuid4().hex[:16])
        client_ip = request.client.host if request.client else "unknown"
        signature = request.headers.get("X-Hub-Signature-256", "")
        timestamp_str = request.headers.get("X-Timestamp", "")

        # Replay protection via X-Timestamp (opt-in — Meta non lo invia)
        if timestamp_str:
            try:
                ts = int(timestamp_str)
                now = time.time()
                if abs(now - ts) > TIMESTAMP_TOLERANCE:
                    logger.warning(
                        json.dumps({
                            "event": "webhook_timestamp_rejected",
                            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "ip": client_ip,
                            "path": request.url.path,
                            "reason": f"timestamp {ts} out of tolerance {TIMESTAMP_TOLERANCE}s",
                        })
                    )
                    raise HTTPException(status_code=403, detail="Timestamp out of tolerance")
            except ValueError:
                logger.warning(
                    json.dumps({
                        "event": "webhook_timestamp_invalid",
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "ip": client_ip,
                        "path": request.url.path,
                        "reason": f"non-integer timestamp: {timestamp_str}",
                    })
                )
                raise HTTPException(status_code=400, detail="Invalid X-Timestamp")

        # Body size limit — letto con streaming per supportare chunked encoding
        body = await _read_limited_body(request, MAX_BODY_SIZE)

        if not _verify_hmac(body, signature, app_config.app_secret):
            logger.warning(
                json.dumps({
                    "event": "webhook_hmac_rejected",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ip": client_ip,
                    "path": request.url.path,
                    "signature": signature,
                    "reason": "signature_mismatch",
                })
            )
            raise HTTPException(status_code=403, detail="Invalid signature")

        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            logger.warning(
                json.dumps({
                    "event": "webhook_json_invalid",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ip": client_ip,
                    "path": request.url.path,
                    "reason": "invalid JSON body",
                })
            )
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
                        await _handle_inbound_message(repo, org_id, msg, value.contacts, trace_id=trace_id)

        return Response(status_code=200)

    return router


async def _read_limited_body(request: Request, max_size: int) -> bytes:
    """Legge il body con limite di dimensione, supporta chunked encoding."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_size:
        logger.warning(
            json.dumps({
                "event": "webhook_body_oversize",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "ip": request.client.host if request.client else "unknown",
                "path": request.url.path,
                "reason": f"Content-Length {content_length} exceeds {max_size}",
            })
        )
        raise HTTPException(status_code=413, detail="Payload too large")

    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_size:
            logger.warning(
                json.dumps({
                    "event": "webhook_body_oversize",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "ip": request.client.host if request.client else "unknown",
                    "path": request.url.path,
                    "reason": f"body exceeded {max_size} during streaming read",
                })
            )
            raise HTTPException(status_code=413, detail="Payload too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def _handle_status_update(repo, org_id, status):
    wam_id = status.id
    new_status = status.status
    biz_data = getattr(status, "biz_opaque_callback_data", None)
    errors = getattr(status, "errors", None)

    # Idempotenza atomica: se gia' processato, skip
    if not await dedup_check(repo.pool, wam_id, "status", new_status):
        return

    if biz_data:
        try:
            uid = uuid.UUID(biz_data)
        except ValueError:
            logger.warning(
                json.dumps({
                    "event": "webhook_invalid_callback_data",
                    "wam_id": wam_id,
                    "biz_opaque_callback_data": biz_data,
                    "reason": "non-UUID, fallback a wam_id",
                })
            )
            # Fallback: aggiorna tramite wam_id (garantito da Meta)
            if wam_id:
                await repo.update_message_status_by_wam_id(
                    wam_id, new_status,
                    error_code=str(errors[0]["code"]) if errors else None,
                    error_title=errors[0]["title"] if errors else None,
                    error_details=errors,
                )
            return
        await repo.update_message_status(
            uid, new_status,
            wam_id=wam_id,
            error_code=str(errors[0]["code"]) if errors else None,
            error_title=errors[0]["title"] if errors else None,
            error_details=errors,
        )
        return

    if wam_id:
        await repo.update_message_status_by_wam_id(
            wam_id, new_status,
            error_code=str(errors[0]["code"]) if errors else None,
            error_title=errors[0]["title"] if errors else None,
            error_details=errors,
        )


async def _handle_inbound_message(repo, org_id, msg, contacts, trace_id=None):
    trace_id = trace_id or uuid.uuid4().hex[:16]
    # Idempotenza atomica
    if not await dedup_check(repo.pool, msg.id, "message", ""):
        logger.info("message_id=%s trace_id=%s action=duplicate_skipped", msg.id, trace_id)
        return

    if not contacts:
        logger.warning("message_id=%s trace_id=%s event=contacts_empty", msg.id, trace_id)

    contact_name = contacts[0].profile.name if contacts and contacts[0].profile else None
    from_number = msg.from_
    contact = await repo.get_or_create_contact(org_id, from_number)
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    async with repo.pool.acquire() as conn:
        async with conn.transaction():
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
                conn=conn,
            )
            await repo.increment_message_usage(org_id, conn=conn)


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
        organization_id=org_data["organization_id"],
        name=value.message_template_name,
        language=value.message_template_language,
        status=value.message_template_status,
        rejected_reason=getattr(value, "reason", None),
    )
