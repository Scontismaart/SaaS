"""
llm_config.py
-------------
Punto unico dove configuriamo quale modello OpenRouter usare.
Quando un modello free viene ritirato o saturi i rate limit,
tocchi SOLO questo file.

CrewAI usa LiteLLM sotto il cofano: OpenRouter è compatibile,
basta prefissare il model id con "openrouter/" e passare la
chiave API tramite variabile d'ambiente.
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

# Modello di default: buon compromesso reasoning/costo per validazione
# e generazione risposta. Cambialo qui se il modello viene ritirato
# o vuoi provare un'alternativa (es. "qwen/qwen3-235b-a22b:free").
MODELLO_DEFAULT = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
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


def crea_llm(
    model: str | None = None,
    temperature: float = 0.4,
    route_request: LLMRouteRequest | None = None,
) -> LLM:
    """Restituisce un'istanza LLM configurata su OpenRouter, pronta
    per essere assegnata a un Agent CrewAI.

    temperature bassa (0.4) di proposito: per un assistente che
    risponde a clienti reali vogliamo risposte più prevedibili,
    non creative.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY non trovata. Copia .env.example in .env "
            "e inserisci la tua chiave da openrouter.ai/keys"
        )

    selected_model = model
    if selected_model is None and route_request is not None:
        selected_model = route_llm(route_request).model

    return LLM(
        model=f"openrouter/{selected_model or MODELLO_DEFAULT}",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature,
    )


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
