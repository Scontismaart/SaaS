"""Tenant-scoped fail-closed review generation governance."""

import os
import re
import unicodedata


async def authorize_review_generation(repo, org_id: str):
    from src.api.routes.common import check_feature_blocked_by_plan, get_billing_snapshot
    from src.core.rate_limit import get_rate_limiter

    blocked = await check_feature_blocked_by_plan(repo, org_id, "recensioni")
    if blocked:
        raise RuntimeError("review generation is not authorized")
    billing = await get_billing_snapshot(repo, org_id)
    if not billing or billing.get("ai_accounting_blocked"):
        raise RuntimeError("review billing state unavailable")
    limit = max(1, int(os.getenv("REVIEW_AI_RATE_LIMIT", "10")))
    window = max(1, int(os.getenv("REVIEW_AI_RATE_WINDOW_SECONDS", "3600")))
    limiter = await get_rate_limiter()
    if await limiter.hit(f"review-ai:{org_id}", limit, window):
        raise RuntimeError("review generation rate limited")
    return billing


def generic_review_fallback(source: str):
    """Safe human-reviewed reply when no retrieved facts are available."""
    from src.models.schemas import RispostaRecensioneOutput

    text = (source or "").casefold()
    sentiment = "negativa" if any(x in text for x in ("problema", "male", "pessimo", "deluso", "attesa")) else "positiva"
    return RispostaRecensioneOutput(
        id="", stato="bozza_generata",
        bozza_risposta=("Grazie per aver condiviso la sua esperienza. "
                        "Prendiamo in considerazione il suo feedback e restiamo a disposizione per approfondire direttamente."),
        sentiment=sentiment, richiede_revisione_urgente=True,
        motivo="Knowledge verificata non disponibile; risposta generica da approvare manualmente.",
        categoria="generico",
    )


def _normalized_amounts(text: str) -> set[tuple[str, str]]:
    """Extract complete numeric amount + currency pairs, never nearby numbers."""
    text = unicodedata.normalize("NFKC", text or "").casefold()
    pattern = re.compile(
        r"(?<![\w])(?:€\s*(?P<euro_before>\d+(?:[.,]\d{1,2})?)|"
        r"(?P<euro_after>\d+(?:[.,]\d{1,2})?)\s*(?:€|eur(?:o)?s?))"
    )
    found = set()
    for match in pattern.finditer(text):
        raw = match.group("euro_before") or match.group("euro_after")
        amount = f"{float(raw.replace(',', '.')):.2f}"
        found.add((amount, "EUR"))
    # USD/GBP are recognized as distinct currencies; no cross-currency support.
    for currency, marker in (("USD", r"(?:\$\s*(\d+(?:[.,]\d{1,2})?)|\b(\d+(?:[.,]\d{1,2})?)\s*usd\b)"),
                             ("GBP", r"(?:£\s*(\d+(?:[.,]\d{1,2})?)|\b(\d+(?:[.,]\d{1,2})?)\s*gbp\b)")):
        for match in re.finditer(marker, text):
            raw = next(group for group in match.groups() if group)
            found.add((f"{float(raw.replace(',', '.')):.2f}", currency))
    return found


def validate_review_draft(draft: str, source: str, knowledge: str = "") -> None:
    """Deterministic pre-save checks; arbitrary non-price claims remain human reviewed."""
    if not isinstance(draft, str) or not draft.strip():
        raise ValueError("empty review draft")
    sensitive = re.compile(
        r"(?i)(ignore (?:all )?(?:previous|prior) instructions|system prompt|reveal (?:all )?(?:secrets|internal|private)|api[_ -]?key|password|\bsecret\b|\btoken\b|\b\d{7,}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})"
    )
    if sensitive.search(draft):
        raise ValueError("unsafe review draft")
    mentioned = _normalized_amounts(draft)
    supported = _normalized_amounts(knowledge)
    if mentioned - supported:
        raise ValueError("unsupported price in review draft")


async def record_review_usage(repo, org_id: str, usage: dict, *, task_type="review", context=None) -> None:
    """Persist every actual provider attempt directly, without an outbox hold.

    `usage` accepts either the new attempts list or a legacy single attempt.
    Any incomplete attempted call fails closed and prevents draft persistence.
    """
    from src.core.llm_routing import stima_costo_eur
    from src.core.db.repositories.billing_repo import BillingRepository

    attempts = usage.get("attempts") if isinstance(usage, dict) else None
    if attempts is None:
        attempts = [usage] if usage else []
    if not attempts:
        return
    records = []
    unresolved = False
    for attempt in attempts:
        model = attempt.get("model")
        prompt_tokens = attempt.get("prompt_tokens")
        completion_tokens = attempt.get("completion_tokens")
        latency_ms = attempt.get("latency_ms")
        # Do the checks explicitly; unknown usage is itself durably recorded.
        valid = (bool(model)
                 and isinstance(prompt_tokens, int) and not isinstance(prompt_tokens, bool) and prompt_tokens >= 0
                 and isinstance(completion_tokens, int) and not isinstance(completion_tokens, bool) and completion_tokens >= 0
                 and prompt_tokens + completion_tokens > 0
                 and isinstance(latency_ms, int) and not isinstance(latency_ms, bool) and latency_ms >= 0)
        cost = stima_costo_eur(model, prompt_tokens, completion_tokens) if valid else None
        valid = valid and cost is not None
        common = {
            **(context or {}),
            "task_type": task_type, "model": model,
            "prompt_tokens": prompt_tokens if isinstance(prompt_tokens, int) else None,
            "completion_tokens": completion_tokens if isinstance(completion_tokens, int) else None,
            "total_tokens": attempt.get("total_tokens"),
            "latency_ms": latency_ms if isinstance(latency_ms, int) else None,
            "reason": attempt.get("reason", "review"),
            "fallback": bool(attempt.get("fallback", False)),
        }
        if valid:
            common.update({
                "total_tokens": attempt.get("total_tokens") or prompt_tokens + completion_tokens,
                "estimated_cost_eur": cost,
                "accounting_status": "recorded",
            })
        else:
            unresolved = True
            common.update({"estimated_cost_eur": None, "accounting_status": "unresolved"})
        records.append({"event_type": "ai_response", "quantity": 1, "metadata": common})
    await BillingRepository(repo.pool).record_usage_batch(org_id, records, block_ai=unresolved)
    if unresolved:
        raise RuntimeError("provider usage could not be verified; AI generation blocked")
