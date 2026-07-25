from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from uuid import UUID


class TextEntry(BaseModel):
    body: str

class ButtonReply(BaseModel):
    id: str
    title: Optional[str] = None

class InteractiveEntry(BaseModel):
    type: Optional[str] = None
    button_reply: Optional[ButtonReply] = None

class ContextEntry(BaseModel):
    from_: Optional[str] = Field(None, alias="from")
    id: Optional[str] = None

class MessageEntry(BaseModel):
    id: str
    from_: str = Field(alias="from")
    type: str
    text: Optional[TextEntry] = None
    interactive: Optional[InteractiveEntry] = None
    context: Optional[ContextEntry] = None
    timestamp: Optional[str] = None

    model_config = {"populate_by_name": True}

class StatusEntry(BaseModel):
    id: str
    status: str
    timestamp: str
    recipient_id: Optional[str] = None
    errors: Optional[list[dict[str, Any]]] = None
    biz_opaque_callback_data: Optional[str] = None
    conversation: Optional[dict[str, Any]] = None

class MetadataEntry(BaseModel):
    display_phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None

class ProfileEntry(BaseModel):
    name: Optional[str] = None

class ContactEntry(BaseModel):
    profile: Optional[ProfileEntry] = None
    wa_id: Optional[str] = None

class ChangeValue(BaseModel):
    messaging_product: str = "whatsapp"
    metadata: Optional[MetadataEntry] = None
    contacts: Optional[list[ContactEntry]] = None
    messages: Optional[list[MessageEntry]] = None
    statuses: Optional[list[StatusEntry]] = None
    message_template_id: Optional[int] = None
    message_template_name: Optional[str] = None
    message_template_language: Optional[str] = None
    message_template_status: Optional[str] = None
    reason: Optional[str] = None
    event: Optional[str] = None

class ChangeEntry(BaseModel):
    field: str = "messages"
    value: ChangeValue

class Entry(BaseModel):
    id: Optional[str] = None
    changes: list[ChangeEntry]

class IngoingWebhook(BaseModel):
    object: str
    entry: list[Entry]


class OutboundTextPayload(BaseModel):
    preview_url: Optional[bool] = None
    body: str

class OutboundTemplateComponents(BaseModel):
    type: str
    parameters: list[dict[str, Any]]

class OutboundTemplatePayload(BaseModel):
    name: str
    language: dict[str, str]
    components: Optional[list[OutboundTemplateComponents]] = None

class SendTextRequest(BaseModel):
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "text"
    text: OutboundTextPayload
    biz_opaque_callback_data: Optional[str] = None

class SendTemplateRequest(BaseModel):
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "template"
    template: OutboundTemplatePayload
    biz_opaque_callback_data: Optional[str] = None

class ContactResponse(BaseModel):
    input: str
    wa_id: str

class MessageResponse(BaseModel):
    id: str

class SendResponse(BaseModel):
    messaging_product: str
    contacts: list[ContactResponse]
    messages: list[MessageResponse]
