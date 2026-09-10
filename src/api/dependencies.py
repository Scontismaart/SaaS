"""Centralized FastAPI Dependency Injection (Invarianti 1, 2, 8).

Sostituisce gli accessi manuali e non tipizzati `getattr(request.app.state, ...)`
con dipendenze dichiarative, type-checked e riutilizzabili per tutti i router.
"""

from typing import Any
import asyncpg
from fastapi import Depends, HTTPException, Request

from src.core.auth.dependencies import (
    get_current_user,
    get_organization_context,
    require_ruolo,
)


def get_repo(request: Request) -> Any:
    """Restituisce l'istanza di CoreRepository dal request state."""
    repo = getattr(request.app.state, "repo", None)
    if repo is None:
        raise HTTPException(status_code=500, detail="Repository non inizializzato")
    return repo


def get_pool(request: Request) -> asyncpg.Pool:
    """Restituisce il connection pool asyncpg del database."""
    pool = getattr(request.app.state, "pool", None)
    if pool is None:
        repo = getattr(request.app.state, "repo", None)
        pool = getattr(repo, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database non disponibile")
    return pool


def get_external_booking_repo(request: Request) -> Any:
    """Restituisce l'ExternalBookingRepository dal request state o creandolo dal pool."""
    ext_repo = getattr(request.app.state, "external_booking_repo", None)
    if ext_repo is not None:
        return ext_repo
    pool = get_pool(request)
    from src.core.db.repositories.external_booking_repo import ExternalBookingRepository
    ext_repo = ExternalBookingRepository(pool)
    request.app.state.external_booking_repo = ext_repo
    return ext_repo


def get_airtable_service(request: Request) -> Any:
    """Restituisce l'AirtableConnectionService dal request state o creandolo dal pool."""
    svc = getattr(request.app.state, "airtable_service", None)
    if svc is not None:
        return svc
    pool = get_pool(request)
    repo = getattr(request.app.state, "repo", None)
    from src.integrations.airtable.repository import AirtableConnectionRepository
    from src.integrations.airtable.service import AirtableConnectionService
    airtable_repo = AirtableConnectionRepository(pool)
    svc = AirtableConnectionService(repo=airtable_repo, core_repo=repo)
    request.app.state.airtable_service = svc
    return svc


def get_airtable_webhook_service(request: Request) -> Any:
    """Restituisce l'AirtableWebhookService dal request state o creandolo dal pool."""
    svc = getattr(request.app.state, "airtable_webhook_service", None)
    if svc is not None:
        return svc
    pool = get_pool(request)
    from src.integrations.airtable.repository import (
        AirtableConnectionRepository,
        AirtableMappingRepository,
        AirtableWebhookRepository,
    )
    from src.integrations.airtable.webhook_service import (
        AirtableWebhookPayloadFetcher,
        AirtableWebhookService,
    )
    webhook_repo = AirtableWebhookRepository(pool)
    mapping_repo = AirtableMappingRepository(pool)
    connection_repo = AirtableConnectionRepository(pool)
    # Modello ufficiale Airtable thin-ping: il processing asincrono recupera i cambiamenti
    # da GET /v0/bases/{baseId}/webhooks/{webhookId}/payloads con il cursore del tenant.
    payload_fetcher = AirtableWebhookPayloadFetcher(connection_repo=connection_repo)
    svc = AirtableWebhookService(
        repo=webhook_repo,
        mapping_repo=mapping_repo,
        payload_fetcher=payload_fetcher,
    )
    request.app.state.airtable_webhook_service = svc
    return svc


def get_booking_service(request: Request) -> Any:
    """Restituisce il servizio prenotazioni BookingService."""
    svc = getattr(request.app.state, "booking_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Booking service non disponibile")
    return svc


def get_orchestrator(request: Request) -> Any:
    """Restituisce il ConversationOrchestrator per la gestione AI unificata (Fase 2)."""
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        repo = getattr(request.app.state, "repo", None)
        from src.core.receptionist.conversation_orchestrator import ConversationOrchestrator
        try:
            from src.integrations.airtable.wiring import build_airtable_tool_factory
            pool = get_pool(request)
            airtable_tool_factory = build_airtable_tool_factory(pool, repo)
        except Exception:
            airtable_tool_factory = None
        orch = ConversationOrchestrator(
            org_repo=getattr(repo, "org_repo", repo) if repo else None,
            doc_repo=getattr(repo, "doc_repo", repo) if repo else None,
            billing_repo=getattr(repo, "billing_repo", repo) if repo else None,
            conv_repo=getattr(repo, "conv_repo", repo) if repo else None,
            booking_service=getattr(request.app.state, "booking_service", None),
            airtable_tool_factory=airtable_tool_factory,
        )
        request.app.state.orchestrator = orch
    return orch



def get_current_org_id(user: dict = Depends(get_organization_context)) -> str:
    """Estrae e valida l'organization_id dal contesto utente autenticato.
    
    Garantisce l'Invariante 1 (Tenant Isolation): non accetta mai l'org_id
    da input non autenticato o query parameter arbitrario.
    """
    org_id = user.get("organization_id")
    if not org_id:
        raise HTTPException(
            status_code=401,
            detail="Nessuna organizzazione collegata: inserisci credenziali valide.",
        )
    return str(org_id)


__all__ = [
    "get_repo",
    "get_pool",
    "get_external_booking_repo",
    "get_airtable_service",
    "get_airtable_webhook_service",
    "get_booking_service",
    "get_orchestrator",
    "get_current_org_id",
    "get_organization_context",
    "get_current_user",
    "require_ruolo",
]
