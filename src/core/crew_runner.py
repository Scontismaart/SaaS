"""
crew_runner.py
--------------
Punto d'ingresso unico verso la logica agente. Il backend (FastAPI, prossimo
step) chiama SOLO questa funzione — non conosce CrewAI, non conosce prompt,
non conosce OpenRouter. Questo disaccoppiamento è quello che ci permette
di cambiare tutto il resto (UI, canale, provider LLM) senza toccare i
moduli a monte.
"""

import time

from src.agents.responder_agent import crea_crew
from src.core.llm_config import (
    LLM_CONCURRENCY_SEM,
    LLMRouteRequest,
    budget_ratio_from_billing,
    route_llm,
)
from src.models.schemas import MessaggioInput, ProfiloAttivita, RispostaOutput


def _riempi_sink(sink: dict | None, model: str, fallback_usato: bool, inizio: float, crew) -> None:
    """Invariante 8: metriche reali della chiamata LLM (modello effettivo,
    token, latenza). Fail-soft: qualunque problema nelle metriche non deve
    mai rompere la generazione risposta."""
    if sink is None:
        return
    try:
        sink["model_effettivo"] = model
        sink["fallback_usato"] = fallback_usato
        sink["latenza_ms"] = int((time.monotonic() - inizio) * 1000)
        metrics = getattr(crew, "usage_metrics", None)
        sink["prompt_tokens"] = getattr(metrics, "prompt_tokens", None)
        sink["completion_tokens"] = getattr(metrics, "completion_tokens", None)
        sink["total_tokens"] = getattr(metrics, "total_tokens", None)
    except Exception:
        pass


def _route_request_for_message(
    messaggio: MessaggioInput, billing: dict | None = None, intent: str | None = None
) -> LLMRouteRequest:
    return LLMRouteRequest(
        task_type="customer_message",
        user_text=messaggio.testo,
        remaining_budget_ratio=budget_ratio_from_billing(billing),
        intent=intent,
    )


def _validate_output(risultato) -> RispostaOutput:
    output = risultato.pydantic
    if output is None or not isinstance(output, RispostaOutput):
        raise RuntimeError(
            "Il modello non ha restituito un output conforme a RispostaOutput. "
            "Riprova, o verifica che il modello configurato in llm_config.py "
            "sia ancora disponibile su OpenRouter."
        )
    return output


def genera_risposta(
    messaggio: MessaggioInput,
    profilo: ProfiloAttivita,
    cronologia: list[tuple[str, str]] | None = None,
    billing: dict | None = None,
    intent: str | None = None,
    variante: str = "control",
    contesto_disponibilita: str = "",
    tentativi_falliti: int = 0,
    usage_sink: dict | None = None,
    tools: list | None = None,
) -> RispostaOutput:
    """Esegue la crew su un singolo messaggio e restituisce l'output
    strutturato e validato.

    Se `usage_sink` (dict) è fornito, viene riempito con le metriche reali
    della chiamata: model_effettivo, fallback_usato, latenza_ms, token.

    Solleva eccezione se, dopo i retry interni di CrewAI/LiteLLM, il
    modello non restituisce un output conforme allo schema: meglio
    un errore esplicito che una risposta silenziosamente sbagliata
    mandata a un cliente reale.
    """
    route_request = _route_request_for_message(messaggio, billing, intent)
    route = route_llm(route_request)
    errors: list[str] = []
    inizio = time.monotonic()
    for idx, model in enumerate([route.model, *route.fallback_models]):
        try:
            crew = crea_crew(profilo, messaggio, cronologia, route_request=route_request,
                             model=model, variante=variante,
                             contesto_disponibilita=contesto_disponibilita,
                             tentativi_falliti=tentativi_falliti, tools=tools)
            out = _validate_output(crew.kickoff())
            _riempi_sink(usage_sink, model, idx > 0, inizio, crew)
            return out
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("Tutti i modelli configurati hanno fallito. " + " | ".join(errors))


async def genera_risposta_async(
    messaggio: MessaggioInput,
    profilo: ProfiloAttivita,
    cronologia: list[tuple[str, str]] | None = None,
    billing: dict | None = None,
    contesto_documenti: str = "",
    intent: str | None = None,
    variante: str = "control",
    contesto_disponibilita: str = "",
    tentativi_falliti: int = 0,
    usage_sink: dict | None = None,
    tools: list | None = None,
) -> RispostaOutput:
    """Versione asincrona di genera_risposta per essere usata da route
    FastAPI che girano in un event loop già attivo.

    Se `usage_sink` (dict) è fornito, viene riempito con le metriche reali
    della chiamata: model_effettivo, fallback_usato, latenza_ms, token.

    Audit 3.3: limitata dal semaforo globale LLM_CONCURRENCY_SEM per non
    saturare il rate-limit/budget condiviso su OpenRouter quando piu'
    tenant generano risposte in parallelo."""
    route_request = _route_request_for_message(messaggio, billing, intent)
    route = route_llm(route_request)
    errors: list[str] = []
    inizio = time.monotonic()
    async with LLM_CONCURRENCY_SEM:
        for idx, model in enumerate([route.model, *route.fallback_models]):
            try:
                crew = crea_crew(profilo, messaggio, cronologia=cronologia,
                                 route_request=route_request, model=model,
                                 contesto_documenti=contesto_documenti, variante=variante,
                                 contesto_disponibilita=contesto_disponibilita,
                                 tentativi_falliti=tentativi_falliti, tools=tools)
                out = _validate_output(await crew.kickoff_async())
                _riempi_sink(usage_sink, model, idx > 0, inizio, crew)
                return out
            except Exception as exc:
                errors.append(f"{model}: {exc}")
    raise RuntimeError("Tutti i modelli configurati hanno fallito. " + " | ".join(errors))
