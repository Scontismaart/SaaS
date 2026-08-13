import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.auth.dependencies import require_ruolo
from src.core.inbox.schemas import (
    ClaimRequest,
    ClaimResponse,
    ReplyRequest,
    ReplyResponse,
    TicketListItem,
    TicketListResponse,
)
from src.whatsapp.config import AppConfig, load_tenant_config
from src.whatsapp.repository import Repository as WhatsAppRepository
from src.whatsapp.service import WhatsAppService

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _get_wrepo(request: Request) -> WhatsAppRepository:
    pool = request.app.state.pool
    if pool is None:
        raise HTTPException(500, "Database not available")
    return WhatsAppRepository(pool=pool)


def _get_app_config() -> AppConfig:
    return AppConfig(
        app_secret=os.environ.get("META_APP_SECRET", ""),
        encryption_key=os.environ.get("ENCRYPTION_KEY", ""),
        postgres_dsn="",
        verify_token=os.environ.get("META_VERIFY_TOKEN", ""),
    )


def _to_ticket_item(t: dict) -> TicketListItem:
    return TicketListItem(
        id=str(t["id"]),
        organization_id=str(t["organization_id"]),
        contact_id=str(t["contact_id"]),
        ticket_status=t["ticket_status"],
        assigned_to=str(t["assigned_to"]) if t.get("assigned_to") else None,
        assigned_nome=t.get("assigned_nome"),
        assigned_email=t.get("assigned_email"),
        pending_staff_at=t["pending_staff_at"].isoformat() if t.get("pending_staff_at") else None,
        claimed_at=t["claimed_at"].isoformat() if t.get("claimed_at") else None,
        resolved_at=t["resolved_at"].isoformat() if t.get("resolved_at") else None,
        last_message_at=t["last_message_at"].isoformat() if t.get("last_message_at") else None,
        created_at=t["created_at"].isoformat(),
        version=t["version"],
        sla_minutes=t.get("sla_minutes") or 15,
        sla_due_at=t["sla_due_at"].isoformat() if t.get("sla_due_at") else None,
        is_overdue=bool(t.get("is_overdue")),
        priorita=t.get("priorita") or "media",
        phone_number=t.get("phone_number"),
        last_message_preview=t.get("last_message_preview"),
    )


@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    request: Request,
    status: str | None = None,
    priorita: str | None = None,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    tickets = await wrepo.list_tickets(org_id, status=status, priorita=priorita)
    return TicketListResponse(tickets=[_to_ticket_item(t) for t in tickets])


@router.get("/tickets/{conversation_id}", response_model=TicketListItem)
async def get_ticket(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _to_ticket_item(conv)


@router.post("/claim/{conversation_id}", response_model=ClaimResponse)
async def claim_ticket(
    conversation_id: str,
    body: ClaimRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await wrepo.claim_ticket(conversation_id, user["user_id"], expected_version=body.expected_version)
    if not result:
        raise HTTPException(status_code=409, detail="Conflict: ticket already claimed or version mismatch")
    return ClaimResponse(
        id=str(result["id"]),
        ticket_status=result["ticket_status"],
        assigned_to=str(result["assigned_to"]) if result.get("assigned_to") else None,
        claimed_at=str(result["claimed_at"]) if result.get("claimed_at") else None,
        version=result["version"],
        assigned_nome=result.get("assigned_nome"),
        assigned_email=result.get("assigned_email"),
    )


@router.post("/release/{conversation_id}")
async def release_ticket(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await wrepo.release_ticket(conversation_id, user["user_id"])
    if not result:
        raise HTTPException(status_code=409, detail="Cannot release: not assigned to you or not CLAIMED")
    return {"ticket_status": result["ticket_status"], "version": result["version"]}


@router.post("/resolve/{conversation_id}")
async def resolve_ticket(
    conversation_id: str,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await wrepo.resolve_ticket(conversation_id, user["user_id"])
    if not result:
        raise HTTPException(status_code=409, detail="Cannot resolve: not assigned to you or not CLAIMED")
    return {"ticket_status": result["ticket_status"], "version": result["version"]}


@router.post("/reply/{conversation_id}", response_model=ReplyResponse)
async def reply_to_ticket(
    conversation_id: str,
    body: ReplyRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Inoltra la risposta manuale dell'operatore a Meta Cloud API.
    Idempotente su (organization_id, idempotency_key): una ri-sottomissione
    involontaria dello stesso client (doppio click, retry dopo timeout
    apparente) restituisce il messaggio gia' inviato invece di duplicarlo."""
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv["ticket_status"] != "CLAIMED" or str(conv.get("assigned_to")) != str(user["user_id"]):
        raise HTTPException(
            status_code=409,
            detail="Ticket non CLAIMED da te: fai il claim prima di rispondere",
        )
    if not conv.get("phone_number"):
        raise HTTPException(status_code=422, detail="Contatto senza numero di telefono associato")

    app_config = _get_app_config()
    tenant_config = await load_tenant_config(uuid.UUID(str(org_id)), app_config, wrepo)
    service = WhatsAppService(app_config, wrepo)
    payload = {"to": conv["phone_number"], "type": body.message_type, "text": {"body": body.content}}

    try:
        result = await service.send_whatsapp_message(
            org_id=uuid.UUID(str(org_id)),
            to_number=conv["phone_number"],
            payload=payload,
            category="service",
            meta_client=None,
            tenant_config=tenant_config,
            idempotency_key=body.idempotency_key,
        )
    except WhatsAppService.MessageUsageExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except WhatsAppService.MessageBlockedByOptOut as e:
        raise HTTPException(status_code=403, detail=str(e))

    return ReplyResponse(message_id=str(result["id"]), status=result.get("status", "queued"))
