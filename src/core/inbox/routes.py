import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request

from src.core.auth.dependencies import require_ruolo
from src.core.inbox.schemas import (
    AssignRequest,
    AssignResponse,
    ClaimRequest,
    ClaimResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageListItem,
    MessageListResponse,
    ReplyRequest,
    ReplyResponse,
    TeamListResponse,
    TeamMemberItem,
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


def _require_user_id(user: dict) -> str:
    """Le azioni operative (claim/release/resolve/reply) attribuiscono il
    ticket a un operatore: servono la sua identita'. Il path X-API-Key della
    UI transitoria non propaga user_id (dependencies.py) — meglio un 403
    esplicito del KeyError 500 che oggi nasconde il problema."""
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Azione richiede una sessione utente (JWT): l'API key di servizio puo' solo leggere l'inbox",
        )
    return str(user_id)


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
        canale=t.get("canale") or "whatsapp",
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
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _to_ticket_item(conv)


@router.get("/tickets/{conversation_id}/messages", response_model=MessageListResponse)
async def get_ticket_messages(
    conversation_id: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Storico messaggi del ticket, in ordine cronologico: l'operatore non
    risponde piu' alla cieca sull'ultimo preview. Paginazione limit/offset."""
    org_id = user["organization_id"]
    if limit < 1 or limit > 200 or offset < 0:
        raise HTTPException(status_code=422, detail="limit deve essere 1-200 e offset >= 0")
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    rows = await wrepo.list_conversation_messages(
        org_id, conversation_id, limit=limit, offset=offset
    )
    total = rows[0]["total"] if rows else 0
    return MessageListResponse(
        messages=[
            MessageListItem(
                id=str(r["id"]),
                direction=r["direction"],
                message_type=r["message_type"],
                content_text=r.get("content_text"),
                status=r["status"],
                handling_type=r.get("handling_type"),
                created_at=r["created_at"].isoformat(),
                feedback_customer=r.get("feedback_customer"),
                feedback_staff_up=r.get("feedback_staff_up") or 0,
                feedback_staff_down=r.get("feedback_staff_down") or 0,
            )
            for r in rows
        ],
        total=total,
    )


@router.post("/claim/{conversation_id}", response_model=ClaimResponse)
async def claim_ticket(
    conversation_id: str,
    body: ClaimRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await wrepo.claim_ticket(conversation_id, _require_user_id(user),
                                       expected_version=body.expected_version, organization_id=org_id)
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
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await wrepo.release_ticket(conversation_id, _require_user_id(user), organization_id=org_id)
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
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = await wrepo.resolve_ticket(conversation_id, _require_user_id(user), organization_id=org_id)
    if not result:
        raise HTTPException(status_code=409, detail="Cannot resolve: not assigned to you or not CLAIMED")
    return {"ticket_status": result["ticket_status"], "version": result["version"]}


@router.get("/team", response_model=TeamListResponse)
async def list_team(
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    members = await wrepo.list_team_members(org_id)
    return TeamListResponse(members=[
        TeamMemberItem(
            user_id=str(m["user_id"]),
            nome=m["nome"],
            email=m["email"],
            ruolo=m["ruolo"],
        )
        for m in members
    ])


@router.post("/assign/{conversation_id}", response_model=AssignResponse)
async def assign_ticket(
    conversation_id: str,
    body: AssignRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager")),
):
    """Assegna o riassegna un ticket a un membro del team. Solo owner/manager:
    lo staff assegna a se stesso col claim. Riassegnazione ottimistica:
    tre partner non possono sovrascriversi a vicenda."""
    org_id = user["organization_id"]
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    team = await wrepo.list_team_members(org_id)
    if body.assigned_to not in {str(m["user_id"]) for m in team}:
        raise HTTPException(status_code=404, detail="Member not found in this organization")

    result = await wrepo.assign_ticket(
        conversation_id, body.assigned_to, expected_version=body.expected_version,
        organization_id=org_id,
    )
    if not result:
        raise HTTPException(status_code=409, detail="Conflict: ticket status or version mismatch")
    enriched = await wrepo.get_conversation(conversation_id, org_id) or result
    return AssignResponse(
        id=str(result["id"]),
        ticket_status=result["ticket_status"],
        assigned_to=str(result["assigned_to"]) if result.get("assigned_to") else None,
        claimed_at=str(result["claimed_at"]) if result.get("claimed_at") else None,
        version=result["version"],
        assigned_nome=enriched.get("assigned_nome"),
        assigned_email=enriched.get("assigned_email"),
    )


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
    operator_id = _require_user_id(user)
    wrepo = _get_wrepo(request)
    conv = await wrepo.get_conversation(conversation_id, org_id)
    if not conv or str(conv["organization_id"]) != str(org_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv["ticket_status"] != "CLAIMED" or str(conv.get("assigned_to")) != operator_id:
        raise HTTPException(
            status_code=409,
            detail="Ticket non CLAIMED da te: fai il claim prima di rispondere",
        )
    if not conv.get("phone_number"):
        raise HTTPException(status_code=422, detail="Contatto senza identificatore associato")

    app_config = _get_app_config()

    # Dispatch per canale: la reply di un ticket Instagram deve uscire su
    # Instagram DM, non su WhatsApp (phone_number qui e' l'external id del
    # contatto: numero WA o IG user id a seconda del canale).
    if (conv.get("canale") or "whatsapp") == "instagram":
        from src.instagram.repository import InstagramRepository
        from src.instagram.config import load_instagram_config
        from src.instagram.service import InstagramService

        ig_config = await load_instagram_config(
            uuid.UUID(str(org_id)),
            app_config.encryption_key,
            InstagramRepository(pool=request.app.state.pool),
        )
        if not ig_config:
            raise HTTPException(
                status_code=409,
                detail="Account Instagram non configurato per questa organizzazione",
            )
        try:
            result = await InstagramService(wrepo).send_instagram_message(
                org_id=uuid.UUID(str(org_id)),
                to_ig_id=conv["phone_number"],
                text=body.content,
                ig_config=ig_config,
                idempotency_key=body.idempotency_key,
                handling_type="human",
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Invio su Instagram fallito: {e}")
        return ReplyResponse(message_id=str(result["id"]), status=result.get("status", "queued"))

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
            handling_type="human",
        )
    except WhatsAppService.MessageUsageExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except WhatsAppService.MessageBlockedByOptOut as e:
        raise HTTPException(status_code=403, detail=str(e))

    return ReplyResponse(message_id=str(result["id"]), status=result.get("status", "queued"))


@router.post("/messages/{message_id}/feedback", response_model=FeedbackResponse)
async def feedback_message(
    message_id: str,
    body: FeedbackRequest,
    request: Request,
    user: dict = Depends(require_ruolo("owner", "manager", "staff")),
):
    """Feedback staff 👍/👎 su una risposta inviata (task 12): il log dei
    feedback, joinato con prompt_variant/intent negli usage events, e' la
    base per iterare sui prompt. Idempotente per operatore: ri-votare
    aggiorna il proprio giudizio."""
    org_id = user["organization_id"]
    operator_id = _require_user_id(user)
    wrepo = _get_wrepo(request)
    message = await wrepo.get_message_org_scoped(org_id, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if message["direction"] != "outbound":
        raise HTTPException(
            status_code=422,
            detail="Feedback solo su messaggi in uscita (risposte), non su messaggi del cliente",
        )
    row = await wrepo.registra_feedback(
        organization_id=org_id,
        message_id=message["id"],
        conversation_id=str(message["conversation_id"]),
        source="staff_ui",
        value=body.value,
        created_by_user_id=operator_id,
    )
    return FeedbackResponse(message_id=str(row["message_id"]), value=row["value"])
