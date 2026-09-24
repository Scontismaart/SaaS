from __future__ import annotations

import os
from src.core.cost_policy import DEFAULT_FREE_MODEL
from dataclasses import dataclass
from typing import Literal


LLMTaskType = Literal[
    "customer_message",
    "review",
    "report",
    "document_qa",
    "onboarding_preview",
]

LLMTier = Literal["cheap", "premium"]

_DEFAULT_CHEAP_MODEL = "groq/llama-3.1-8b-instant"
_DEFAULT_PREMIUM_MODEL = DEFAULT_FREE_MODEL
_DEFAULT_FALLBACK_MODELS = (
    "groq/llama-3.1-8b-instant,"
    "groq/openai/gpt-oss-120b"
)

_FAQ_KEYWORDS = {
    "orari", "orario", "aperti", "aprite", "chiudete", "prezzo", "prezzi",
    "costa", "quanto", "menu", "indirizzo", "dove", "telefono", "prenotare",
    "prenotazione", "tavolo", "disponibile", "disponibilita",
}

_ESCALATION_KEYWORDS = {
    "arrabbiato", "arrabbiata", "reclamo", "lamentela", "responsabile",
    "rimborso", "urgente", "allergia", "allergico", "allergica", "intossicato",
    "intossicata", "avvocato", "denuncia", "pessimo", "vergogna",
}


@dataclass(frozen=True)
class LLMRouteRequest:
    task_type: LLMTaskType
    user_text: str = ""
    remaining_budget_ratio: float | None = None
    force_tier: LLMTier | None = None
    # Intent gia' classificato (guardrail task 12): quando presente vince
    # sulle keyword (non sulla forza di budget/force_tier/task_type premium).
    intent: str | None = None


@dataclass(frozen=True)
class LLMRoute:
    model: str
    tier: LLMTier
    reason: str
    fallback_models: tuple[str, ...]


def _env_model(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _split_models(raw: str) -> tuple[str, ...]:
    models: list[str] = []
    for item in raw.split(","):
        model = item.strip()
        if model and model not in models:
            models.append(model)
    return tuple(models)


def get_route_fallback_models(primary_model: str) -> list[str]:
    # A newly configured provider must never silently fall back to Groq (or a
    # differently billed account). Legacy deployments keep their old chain.
    configured = os.getenv("AI_MODEL", "").strip()
    raw = (
        os.getenv("AI_MODEL_FALLBACKS", "")
        if configured else os.getenv("OPENROUTER_MODEL_FALLBACKS", _DEFAULT_FALLBACK_MODELS)
    )
    return [model for model in _split_models(raw) if model != primary_model]


def _looks_like_simple_faq(text: str) -> bool:
    words = {token.strip("?!.,;:()[]{}\"'").lower() for token in text.split()}
    return bool(words & _FAQ_KEYWORDS) and not bool(words & _ESCALATION_KEYWORDS)


def _looks_like_escalation(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _ESCALATION_KEYWORDS)


def _budget_is_low(ratio: float | None) -> bool:
    if ratio is None:
        return False
    return ratio <= float(os.getenv("LLM_LOW_BUDGET_RATIO", "0.10"))


def route_llm(request: LLMRouteRequest) -> LLMRoute:
    configured = os.getenv("AI_MODEL", "").strip()
    if configured:
        cheap_model = _env_model("AI_MODEL_CHEAP", configured)
        premium_model = _env_model("AI_MODEL_PREMIUM", configured)
    else:
        cheap_model = _env_model("OPENROUTER_MODEL_CHEAP", _DEFAULT_CHEAP_MODEL)
        premium_model = _env_model("OPENROUTER_MODEL_PREMIUM", os.getenv("OPENROUTER_MODEL", _DEFAULT_PREMIUM_MODEL))

    if request.force_tier == "cheap":
        tier: LLMTier = "cheap"
        reason = "forced_cheap"
    elif request.force_tier == "premium":
        tier = "premium"
        reason = "forced_premium"
    elif _budget_is_low(request.remaining_budget_ratio):
        tier = "cheap"
        reason = "budget_low"
    elif request.task_type in {"review", "report"}:
        tier = "premium"
        reason = "premium_task"
    elif request.task_type == "document_qa":
        tier = "cheap"
        reason = "document_qa"
    elif request.intent in {"faq", "chitchat"}:
        # Intent classificato (task 12): domande semplici e small talk non
        # hanno bisogno del modello premium.
        tier = "cheap"
        reason = "intent_classified"
    elif request.intent in {"booking", "complaint", "out_of_scope"}:
        # Prenotazioni (structured output con date relative da risolvere) e
        # reclami meritano il modello piu' capace.
        tier = "premium"
        reason = "intent_classified"
    elif _looks_like_escalation(request.user_text):
        tier = "premium"
        reason = "complex_or_escalation"
    elif _looks_like_simple_faq(request.user_text):
        tier = "cheap"
        reason = "simple_faq"
    else:
        tier = "premium"
        reason = "default_complex"

    model = cheap_model if tier == "cheap" else premium_model
    return LLMRoute(
        model=model,
        tier=tier,
        reason=reason,
        fallback_models=tuple(get_route_fallback_models(model)),
    )


def budget_ratio_from_billing(billing: dict | None) -> float | None:
    if not billing:
        return None
    limit = billing.get("messages_limit")
    used = billing.get("messages_used_this_period")
    if not limit or limit <= 0 or used is None:
        return None
    remaining = max(int(limit) - int(used), 0)
    return remaining / int(limit)


# Prezzi INDICATIVI per 1M token (prompt, completion) in EUR, per la stima
# di costo dell'invariante 8. Non sono fatture: sono stime lato app.
# Chiavi: nome modello senza prefisso provider, incluse le varianti dei
# default di routing (mistral-small-latest, mistral-medium-2508).
_TOKEN_PRICES_EUR_PER_1M: dict[str, tuple[float, float]] = {
    # The launch policy permits these models only on a user-confirmed Groq
    # free account, therefore their application-side estimated spend is zero.
    "llama-3.1-8b-instant": (0.0, 0.0),
    "gpt-oss-20b": (0.0, 0.0),
    "mistral-small": (0.2, 0.6),
    "mistral-small-latest": (0.2, 0.6),
    "mistral-medium": (2.7, 8.1),
    "mistral-medium-2508": (2.7, 8.1),
    "gpt-oss-120b": (0.1, 0.5),
    "gpt-4o-mini": (0.15, 0.6),
}


def stima_costo_eur(model, prompt_tokens, completion_tokens):
    """Stima indicativa di costo EUR per una chiamata, None se il modello
    non e' in tabella o i token mancano."""
    if prompt_tokens is None or completion_tokens is None:
        return None
    nome = (model or "").split("/")[-1].strip().lower()
    prezzi = _TOKEN_PRICES_EUR_PER_1M.get(nome)
    if not prezzi:
        return None
    p, c = prezzi
    return round(prompt_tokens / 1e6 * p + completion_tokens / 1e6 * c, 6)
