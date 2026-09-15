"""Fail-closed controls for the zero-euro launch profile.

An API key does not reveal whether an account is paid. The operator must verify
the Groq FREE organization in its console before explicitly confirming it here.
Exhaustion must yield an error/escalation; it must never select a paid fallback.
"""

import os

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
    if model not in FREE_MODELS:
        raise RuntimeError("Budget EUR 0: modello non autorizzato dal profilo free_only")
    if os.getenv("GROQ_FREE_ACCOUNT_CONFIRMED", "").lower() != "true":
        raise RuntimeError("Verificare il piano FREE Groq e impostare GROQ_FREE_ACCOUNT_CONFIRMED=true")

