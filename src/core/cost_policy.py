"""Fail-closed controls for the zero-euro launch profile.

An API key does not reveal whether an account is paid. The operator must verify
the Groq FREE organization in its console before explicitly confirming it here.
Exhaustion must yield an error/escalation; it must never select a paid fallback.
"""

import os
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen

FREE_MODELS = frozenset({"groq/llama-3.1-8b-instant", "groq/openai/gpt-oss-20b", "groq/openai/gpt-oss-120b"})
DEFAULT_FREE_MODEL = "groq/openai/gpt-oss-20b"


def free_only() -> bool:
    policy = os.getenv("LLM_COST_POLICY", "free_only").strip().lower()
    if policy not in {"free_only", "standard"}:
        raise RuntimeError("LLM_COST_POLICY non riconosciuta")
    return policy == "free_only"


def assert_model_allowed(model: str) -> None:
    if not free_only():
        return
    if is_openrouter_free_model(model):
        return
    if model not in FREE_MODELS:
        raise RuntimeError("Budget EUR 0: modello non autorizzato dal profilo free_only")
    if os.getenv("GROQ_FREE_ACCOUNT_CONFIRMED", "").lower() != "true":
        raise RuntimeError("Verificare il piano FREE Groq e impostare GROQ_FREE_ACCOUNT_CONFIRMED=true")


def is_openrouter_free_model(model: str) -> bool:
    return bool(re.fullmatch(r"openrouter/[^/:\s]+/[^/:\s]+:free", model))


def assert_openrouter_catalog_free(model: str, api_key: str) -> None:
    """Recheck the official ZDR-filtered catalog before each client is built."""
    if not is_openrouter_free_model(model):
        raise RuntimeError("Budget EUR 0: modello OpenRouter non valido")
    request = Request(
        "https://openrouter.ai/api/v1/models?zdr=true",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
        entries = payload["data"]
        if not isinstance(entries, list):
            raise ValueError("invalid catalog")
        slug = model.removeprefix("openrouter/")
        entry = next(item for item in entries if isinstance(item, dict) and item.get("id") == slug)
        pricing = entry["pricing"]
        if not isinstance(pricing, dict) or not pricing:
            raise ValueError("missing pricing")
        # Request, image and other extras can also incur charges.
        if any(Decimal(str(value)) != 0 for value in pricing.values()):
            raise ValueError("nonzero pricing")
        if "prompt" not in pricing or "completion" not in pricing:
            raise ValueError("missing token pricing")
    except (OSError, ValueError, KeyError, StopIteration, TypeError, InvalidOperation) as exc:
        raise RuntimeError("Budget EUR 0: modello OpenRouter gratuito/ZDR non verificabile") from exc
