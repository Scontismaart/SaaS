from typing import Optional

from pydantic import BaseModel


class ClaimRequest(BaseModel):
    expected_version: int


class ClaimResponse(BaseModel):
    id: str
    ticket_status: str
    assigned_to: Optional[str] = None
    claimed_at: Optional[str] = None
    version: int
    assigned_nome: Optional[str] = None
    assigned_email: Optional[str] = None


class TicketListItem(BaseModel):
    id: str
    organization_id: str
    contact_id: str
    ticket_status: str
    assigned_to: Optional[str] = None
    assigned_nome: Optional[str] = None
    assigned_email: Optional[str] = None
    pending_staff_at: Optional[str] = None
    claimed_at: Optional[str] = None
    resolved_at: Optional[str] = None
    last_message_at: Optional[str] = None
    created_at: str
    version: int
    sla_minutes: int = 15
    sla_due_at: Optional[str] = None
    is_overdue: bool = False
    priorita: str = "media"
    phone_number: Optional[str] = None
    last_message_preview: Optional[str] = None


class TicketListResponse(BaseModel):
    tickets: list[TicketListItem]


class ReplyRequest(BaseModel):
    content: str
    message_type: str = "text"
    idempotency_key: str


class ReplyResponse(BaseModel):
    message_id: str
    status: str


class AssignRequest(BaseModel):
    assigned_to: str
    expected_version: int


class AssignResponse(BaseModel):
    id: str
    ticket_status: str
    assigned_to: Optional[str] = None
    claimed_at: Optional[str] = None
    version: int
    assigned_nome: Optional[str] = None
    assigned_email: Optional[str] = None


class TeamMemberItem(BaseModel):
    user_id: str
    nome: str
    email: str
    ruolo: str


class TeamListResponse(BaseModel):
    members: list[TeamMemberItem]


class MessageListItem(BaseModel):
    id: str
    direction: str
    message_type: str
    content_text: Optional[str] = None
    status: str
    handling_type: Optional[str] = None
    created_at: str


class MessageListResponse(BaseModel):
    messages: list[MessageListItem]
    total: int
