"""
llm_config.py
-------------
Punto unico dove configuriamo quale modello LLM usare e con quale
provider. Oggi supportiamo tre provider, TUTTI con policy no-training
sui dati (requisito per la privacy dei clienti):
  - openrouter:  parametro `provider.data_collection='deny'` (fail-closed)
  - groq:        via LiteLLM, chiave GROQ_API_KEY (policy: no training)
  - cerebras:    provider nativo CrewAI, chiave CEREBRAS_API_KEY (no training)

CrewAI usa LiteLLM sotto il cofano: basta prefissare il model id con il
provider ("openrouter/", "groq/", "cerebras/") e passare la chiave della
variabile d'ambiente del provider. Non aggiungere provider che addestrano
sui dati senza prima verificare la policy.
"""

import asyncio
import os
from crewai import LLM
from src.core.llm_routing import (
    LLMRoute,
    LLMRouteRequest,
    budget_ratio_from_billing,
    get_route_fallback_models,
    route_llm,
)

# Modello di default (usato da crea_llm() quando chi chiama non passa ne'
# model ne' route_request). NON usare endpoint ":free": i modelli gratuiti
# possono addestrare sui dati (incluse le conversazioni reali dei clienti
# inviate nei prompt). Il default e' un modello paid economico.
MODELLO_DEFAULT = os.getenv(
    "OPENROUTER_MODEL",
    "openai/gpt-4o-mini"
)

# Numero di tentativi in caso di errore/rate limit del modello free.
MAX_RETRY = int(os.getenv("LLM_MAX_RETRY", "3"))

# Audit 3.3: senza un limite di concorrenza, un tenant (o piu' tenant
# insieme) puo' saturare il budget/rate-limit condiviso su OpenRouter.
# Semaforo globale asyncio: usato solo nel percorso async reale
# (genera_risposta_async, il flusso WhatsApp che scala col volume di
# messaggi). I percorsi sync (crew_runner_review.py, crew_runner_report.py)
# sono a basso volume (dashboard/scheduler) e non lo usano.
LLM_CONCURRENCY_SEM = asyncio.Semaphore(int(os.getenv("LLM_MAX_CONCURRENT", "3")))

# Prefissi provider riconosciuti nei model id. I provider sono whitelistati:
# solo quelli che NON addestrano sui dati possono stare nella chain.
_PROVIDER_PREFIXES = ("openrouter/", "groq/", "cerebras/")

_KEY_ENV_BY_PROVIDER = {
    "openrouter": "OPENROUTER_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}


def _provider_of(model: str) -> str:
    """Riconosce il prefisso provider di un model id. Un id senza prefisso
    noto (es. "openai/gpt-4o-mini") e' un id OpenRouter (backwards compat)."""
    for prefix in _PROVIDER_PREFIXES:
        if model.startswith(prefix):
            return prefix[:-1]  # "openrouter/"(->"openrouter"), "groq/"->"groq"
    return "openrouter"


def crea_llm(
    model: str | None = None,
    temperature: float = 0.4,
    route_request: LLMRouteRequest | None = None,
) -> LLM:
    """Restituisce un'istanza LLM configurata sul provider indicato dal
    prefisso del model id (default OpenRouter), pronta per un Agent CrewAI.

    temperature bassa (0.4) di proposito: per un assistente che
    risponde a clienti reali vogliamo risposte più prevedibili,
    non creative.

    Privacy (sempre attiva): su OpenRouter viene negato l'uso dei dati per
    training (extra_body provider.data_collection='deny'): se un endpoint
    servisse solo provider che addestrano, la richiesta fallisce invece di
    "perdere" i dati. Groq e Cerebras non addestrano per policy, quindi non
    ricevono il parametro (specifico di OpenRouter) e sono ammessi solo per
    questa garanzia. Nessun interruttore per disattivare la protezione.
    """
    selected_model = model
    if selected_model is None and route_request is not None:
        selected_model = route_llm(route_request).model
    selected_model = selected_model or MODELLO_DEFAULT

    provider = _provider_of(selected_model)
    key_env = _KEY_ENV_BY_PROVIDER[provider]
    api_key = os.getenv(key_env)
    if not api_key:
        raise RuntimeError(
            f"{key_env} non trovata. Copia .env.example in .env e inserisci "
            f"la chiave API per il provider '{provider}'."
        )

    llm_params: dict[str, object] = {
        "model": selected_model,
        "api_key": api_key,
        "temperature": temperature,
    }

    if provider == "openrouter":
        if not selected_model.startswith("openrouter/"):
            llm_params["model"] = f"openrouter/{selected_model}"
        llm_params["base_url"] = "https://openrouter.ai/api/v1"
        llm_params["additional_params"] = {
            "extra_body": {"provider": {"data_collection": "deny"}},
        }

    return LLM(**llm_params)


__all__ = [
    "LLM_CONCURRENCY_SEM",
    "LLMRoute",
    "LLMRouteRequest",
    "MAX_RETRY",
    "MODELLO_DEFAULT",
    "budget_ratio_from_billing",
    "crea_llm",
    "get_route_fallback_models",
    "route_llm",
]
