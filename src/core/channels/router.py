from __future__ import annotations

import logging
from typing import Mapping

from src.core.channels.base import ChannelOutboundPort

logger = logging.getLogger(__name__)


class OutboundChannelRouter:
    """Router che seleziona l'adapter di canale outbound corretto in base alla tipologia di messaggio."""

    def __init__(self, adapters: Mapping[str, ChannelOutboundPort]):
        self._adapters = {k.lower(): v for k, v in adapters.items()}

    def get_adapter(self, channel: str | None) -> ChannelOutboundPort:
        chan_key = (channel or "whatsapp").lower()
        adapter = self._adapters.get(chan_key)
        if not adapter:
            # Fallback di default su whatsapp se disponibile
            adapter = self._adapters.get("whatsapp")
        if not adapter:
            raise KeyError(f"Nessun adapter registrato per il canale '{channel}'")
        return adapter
