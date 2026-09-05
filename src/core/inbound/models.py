from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InboundMessageContext:
    """Contesto di esecuzione per un messaggio in ingresso nella pipeline."""
    message_id: uuid.UUID | str
    organization_id: uuid.UUID | str
    conversation_id: str
    text: str
    channel: str
    sender_destination: str
    sender_name: str
    raw_content: dict[str, Any] = field(default_factory=dict)
    tenant_config: Any = None
    business_profile_raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessingOutcome:
    """Risultato dell'elaborazione di un messaggio inbound."""
    action: str  # "handled", "yielded", "ignored", "error"
    handling_type: str = ""
    meta_message_id: str | None = None
    response_text: str | None = None
    richiede_umano: bool = False
    error: str | None = None
