"""Wiring Airtable AI tools -> production orchestrator (Fase A, P1.4).

Fase A: SOLO tool read/create/update. Il tool distruttivo e' categoricamente
escluso (Fase B separata, two-turn con conferma umana).

Policy di offerta (tutte devono valere, fail-closed):
1. intent del messaggio in AI_TOOL_INTENTS (booking/complaint);
2. budget NON basso (kill-switch: a budget esaurito niente chiamate esterne);
3. connessione Airtable attiva per il tenant (nessun segreto all'LLM: org/base
   iniettati server-side dalla factory).
"""
from __future__ import annotations

import logging
import uuid
from src.core import ai_safety
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# Intent per cui il CRM Airtable e' pertinente (faq/chitchat/out_of_scope: no).
AI_TOOL_INTENTS = frozenset({"booking", "complaint"})

# Fase A: delete categoricamente escluso (vedi DeleteRecordTool two-turn, Fase B).
FASE_A_EXCLUDED_TOOLS = frozenset({"airtable_delete_record"})


async def build_airtable_tools_for_org(
    organization_id: uuid.UUID | str,
    connection_repo: Any,
    mapping_repo: Any,
    core_repo: Any,
) -> list:
    """Costruisce i tool Fase A per il tenant, o [] se non configurato.

    Non solleva mai: assenza di connessione attiva -> lista vuota (fail-closed,
    nessun segreto esposto, nessun errore all'orchestratore).
    """
    from src.integrations.airtable.ai_service import AirtableAIService
    from src.integrations.airtable.ai_tools import create_airtable_tools

    if not ai_safety.CRM_AI_TOOLS_ENABLED:
        return []

    try:
        conn = await connection_repo.get_default_active_connection(organization_id)
    except Exception as exc:
        logger.warning("Airtable tools non disponibili per org %s: %s", organization_id, exc)
        return []
    if not conn or not conn.get("is_active"):
        return []

    service = AirtableAIService(
        connection_repo=connection_repo,
        mapping_repo=mapping_repo,
        core_repo=core_repo,
    )
    try:
        tools = create_airtable_tools(
            service, organization_id, base_id=conn.get("base_id")
        )
    except Exception as exc:
        logger.warning("Costruzione Airtable tools fallita per org %s: %s", organization_id, exc)
        return []
    offered = [t for t in tools if getattr(t, "name", "") not in FASE_A_EXCLUDED_TOOLS]
    logger.info(
        "Airtable tools Fase A offerti per org %s: %s",
        organization_id, sorted(getattr(t, "name", "?") for t in offered),
    )
    return offered


async def select_airtable_tools(
    *,
    intent: str | None,
    budget_ratio: float | None,
    organization_id: uuid.UUID | str | None,
    factory: Callable[[Any], Awaitable[list]] | None,
) -> list:
    """Gate di offerta tool: intent allowlist + kill-switch budget + factory."""
    from src.core.llm_routing import _budget_is_low

    if not ai_safety.CRM_AI_TOOLS_ENABLED:
        return []

    if not factory or not organization_id:
        return []
    if (intent or "") not in AI_TOOL_INTENTS:
        return []
    if _budget_is_low(budget_ratio):
        logger.warning(
            "Airtable tools disabilitati per org %s: budget basso (kill-switch)",
            organization_id,
        )
        return []
    try:
        tools = await factory(organization_id) or []
    except Exception as exc:
        logger.warning("Airtable tool factory fallita per org %s: %s", organization_id, exc)
        return []
    # Difesa in profondita': il delete resta escluso anche se la factory
    # fornita non filtra (il filtro primario e' in build_airtable_tools_for_org).
    return [t for t in tools if getattr(t, "name", "") not in FASE_A_EXCLUDED_TOOLS]


def build_airtable_tool_factory(pool: Any, core_repo: Any) -> Callable[[Any], Awaitable[list]]:
    """Factory per-request chiusa su pool/repos condivisi (tenant passato a chiamata)."""
    from src.integrations.airtable.repository import (
        AirtableConnectionRepository,
        AirtableMappingRepository,
    )

    connection_repo = AirtableConnectionRepository(pool)
    mapping_repo = AirtableMappingRepository(pool)

    async def _factory(organization_id: uuid.UUID | str) -> list:
        return await build_airtable_tools_for_org(
            organization_id, connection_repo, mapping_repo, core_repo
        )

    return _factory
