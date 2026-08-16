from typing import Any, Optional
from pydantic import BaseModel, Field


class IgSender(BaseModel):
    id: str


class IgRecipient(BaseModel):
    id: str


class IgMessage(BaseModel):
    mid: str
    text: Optional[str] = None
    is_echo: Optional[bool] = None
    attachments: Optional[list[dict[str, Any]]] = None


class IgMessagingEvent(BaseModel):
    sender: IgSender
    recipient: IgRecipient
    timestamp: Optional[int] = None
    message: Optional[IgMessage] = None


class IgEntry(BaseModel):
    id: Optional[str] = None
    time: Optional[int] = None
    messaging: list[IgMessagingEvent] = Field(default_factory=list)


class InstagramWebhook(BaseModel):
    """Envelope webhook Instagram DM: stessa struttura entry[] dei webhook
    Meta ma con messaging[] invece di changes[].value (vedere
    src/whatsapp/models.py per il parallelo WhatsApp)."""
    object: str
    entry: list[IgEntry]


class IgSendTextRequest(BaseModel):
    recipient: IgRecipient
    message: dict[str, Any] = Field(default_factory=dict)


class IgSendResponse(BaseModel):
    recipient_id: Optional[str] = None
    message_id: Optional[str] = None
