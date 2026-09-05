from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class OutboundSendResult:
    success: bool
    channel: str
    message_id: str | None = None
    wam_id: str | None = None
    raw_response: dict[str, Any] | None = None
    error: str | None = None


class ChannelOutboundPort(Protocol):
    """Protocollo standard per gli adapter di invio verso i canali esterni."""

    async def send_reply(
        self,
        org_id: uuid.UUID | str,
        to_destination: str,
        text: str,
        tenant_config: Any = None,
        handling_type: str = "ai_handled",
    ) -> OutboundSendResult:
        ...
