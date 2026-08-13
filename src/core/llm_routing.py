from __future__ import annotations

import os
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

_DEFAULT_CHEAP_MODEL = "openai/gpt-4o-mini"
_DEFAULT_PREMIUM_MODEL = "openai/gpt-4.1"
_DEFAULT_FALLBACK_MODELS = (
    "openai/gpt-4o-mini,"
    "anthropic/claude-3.5-haiku,"
    "google/gemini-flash-1.5"
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
    raw = os.getenv("OPENROUTER_MODEL_FALLBACKS", _DEFAULT_FALLBACK_MODELS)
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
