"""Shared route helpers, billing governance, and mock-safe symbol resolvers (Invarianti 1, 8, 10).

Fornisce helper centralizzati riutilizzati dai router modulari per:
- Audit log org-scoped
- Snapshot billing & accounting consumi AI
- Blocco feature in base al piano
- Storico eventi condiviso per la modalità demo senza DB
- Risoluzione dinamica dei simboli per piena compatibilità con patch("src.api.main.*")
"""

import logging
import sys
from datetime import datetime
from typing import Any
from fastapi import Request

logger = logging.getLogger(__name__)

# Storico condiviso per la modalità demo in-memory
_storico_eventi: list[Any] = []
_prossimo_id_evento: int = 0


def get_shared_event_history() -> list[Any]:
    """Restituisce la lista globale degli eventi demo in-memory."""
    return _storico_eventi


def next_event_id(tipo: str) -> str:
    """Genera un identificatore univoco formattato per gli eventi demo."""
    global _prossimo_id_evento
    _prossimo_id_evento += 1
    return f"{tipo}-{datetime.now().strftime('%Y%m%d')}-{_prossimo_id_evento}"


async def audit_event(
    request: Request,
    user: dict,
    action: str,
    target_table: str | None = None,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Registra un'azione sensibile in audit_log.
    
    No-op sicuro se il repo o l'organization_id non sono disponibili.
    Non fa mai fallire la richiesta chiamante in caso di errore di audit.
    """
    repo = getattr(request.app.state, "repo", None)
    organization_id = user.get("organization_id")
    if repo is None or not organization_id:
        return
    try:
        from src.core.auth.audit import audit_log
        await audit_log(
            repo,
            organization_id=organization_id,
            action=action,
            user_id=user.get("user_id"),
            auth_user_id=user.get("auth_user_id"),
            target_table=target_table,
            target_id=target_id,
            details=details,
        )
    except Exception as e:
        logger.warning("[audit_log] scrittura fallita per action=%s: %s", action, e)


async def get_billing_snapshot(repo, organization_id: str | None) -> dict | None:
    """Recupera lo stato di billing del tenant per il routing AI budget-aware (Invariante 8)."""
    if repo is None or not organization_id:
        return None
    try:
        return await repo.get_organization_billing(organization_id)
    except Exception as e:
        logger.warning("[llm_routing] billing snapshot non disponibile org=%s: %s", organization_id, e)
        return None


async def record_ai_usage(
    repo,
    organization_id: str | None,
    task_type: str,
    user_text: str,
    billing: dict | None,
    metadata: dict | None = None,
) -> None:
    """Traccia il consumo e il costo stimato della generazione AI su database (Invariante 8)."""
    if repo is None or not organization_id:
        return
    try:
        from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, route_llm
        route = route_llm(
            LLMRouteRequest(
                task_type=task_type,
                user_text=user_text,
                remaining_budget_ratio=budget_ratio_from_billing(billing),
            )
        )
        await repo.record_usage(
            organization_id,
            "ai_response",
            quantity=1,
            metadata={
                "task_type": task_type,
                "model": route.model,
                "tier": route.tier,
                "reason": route.reason,
                **(metadata or {}),
            },
        )
    except Exception as e:
        logger.warning("[llm_routing] usage logging fallito org=%s: %s", organization_id, e)


async def check_feature_blocked_by_plan(repo, org_id: str | None, feature: str) -> str | None:
    """Verifica se il piano corrente dell'organizzazione include la feature richiesta.

    Regole di accesso:
    1. Sospensione / Cancellazione: se l'abbonamento e' 'canceled', 'unpaid' o il trial e' scaduto,
       l'accesso alle feature a pagamento e' bloccato (fail-closed, Invariante 8).
    2. Trial attivo: se l'org e' in prova gratuita valida, opera con il tier 'pro' (Crescita).
    3. Piano sconosciuto / anomalo: se plan_slug e' valorizzato ma non corrisponde a una chiave
       in PLANS, blocca l'accesso e logga un warning (fail-closed contro drift di naming).
    4. Fail-open solo su transient failure di repo/org_id/billing.
    """
    if not repo or not org_id:
        return None
    billing = await get_billing_snapshot(repo, org_id)
    if not billing:
        return None

    status = billing.get("subscription_status")
    trial_end = billing.get("trial_end")

    # 1. Verifica sospensione abbonamento / scadenza trial (Invariante 8)
    from src.core.billing.suspension import is_org_suspended
    if is_org_suspended(status, trial_end) or status in ("canceled", "unpaid", "incomplete_expired"):
        return "Abbonamento sospeso o scaduto. Rinnova l'abbonamento per accedere a questa funzionalità."

    # 2. Risoluzione piano effettivo
    plan_slug = billing.get("plan")
    if not plan_slug or status == "trialing":
        if not plan_slug:
            plan_slug = "pro"

    # 3. Mappatura piano e blocco fail-closed su plan_slug inatteso
    from src.core.billing.plans import PLANS
    plan = PLANS.get(plan_slug)
    if not plan:
        logger.warning(
            "[feature_gating] piano sconosciuto '%s' per org=%s (status=%s): blocco prudenziale fail-closed",
            plan_slug, org_id, status,
        )
        return f"Configurazione piano '{plan_slug}' non riconosciuta. Contatta l'assistenza per verificare l'abbonamento."

    # 4. Verifica capabilities del piano
    if feature == "rag" and not plan.has_rag:
        return f"Il piano {plan.name} non include la Knowledge Base AI. Effettua l'upgrade al piano Scala per caricare documenti."
    if feature == "recensioni" and not plan.has_reviews:
        return f"Il piano {plan.name} non include la gestione delle recensioni. Effettua l'upgrade per abilitarla."
    return None


# ── Risolutori Dinamici per la Backward Compatibility dei Mock di Test ─────

def resolve_vettorizza():
    """Risolve vettorizza garantendo che i patch su src.api.main.vettorizza abbiano effetto."""
    main_mod = sys.modules.get("src.api.main")
    if main_mod and hasattr(main_mod, "vettorizza"):
        return getattr(main_mod, "vettorizza")
    from src.core.documenti.embeddings import vettorizza
    return vettorizza


def resolve_estrai_da_url():
    """Risolve estrai_da_url garantendo che i patch su src.api.main.estrai_da_url abbiano effetto."""
    main_mod = sys.modules.get("src.api.main")
    if main_mod and hasattr(main_mod, "estrai_da_url"):
        return getattr(main_mod, "estrai_da_url")
    from src.core.documenti.web_extractor import estrai_da_url
    return estrai_da_url


def resolve_genera_risposta_recensione():
    """Risolve genera_risposta_recensione garantendo che i patch su src.api.main abbiano effetto."""
    main_mod = sys.modules.get("src.api.main")
    if main_mod and hasattr(main_mod, "genera_risposta_recensione"):
        return getattr(main_mod, "genera_risposta_recensione")
    from src.core.crew_runner_review import genera_risposta_recensione
    return genera_risposta_recensione
