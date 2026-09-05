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
        raise HTTPException(status_code=503, detail="Database non disponibile")
    return pool


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
        orch = ConversationOrchestrator(
            org_repo=getattr(repo, "org_repo", repo) if repo else None,
            doc_repo=getattr(repo, "doc_repo", repo) if repo else None,
            billing_repo=getattr(repo, "billing_repo", repo) if repo else None,
            conv_repo=getattr(repo, "conv_repo", repo) if repo else None,
            booking_service=getattr(request.app.state, "booking_service", None),
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
    "get_booking_service",
    "get_orchestrator",
    "get_current_org_id",
    "get_organization_context",
    "get_current_user",
    "require_ruolo",
]
