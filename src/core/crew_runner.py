"""
crew_runner.py
--------------
Punto d'ingresso unico verso la logica agente. Il backend (FastAPI, prossimo
step) chiama SOLO questa funzione — non conosce CrewAI, non conosce prompt,
non conosce OpenRouter. Questo disaccoppiamento è quello che ci permette
di cambiare tutto il resto (UI, canale, provider LLM) senza toccare i
moduli a monte.
"""

from src.agents.responder_agent import crea_crew
from src.core.llm_config import (
    LLM_CONCURRENCY_SEM,
    LLMRouteRequest,
    budget_ratio_from_billing,
    route_llm,
)
from src.models.schemas import MessaggioInput, ProfiloAttivita, RispostaOutput


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
) -> RispostaOutput:
    """Esegue la crew su un singolo messaggio e restituisce l'output
    strutturato e validato.

    Solleva eccezione se, dopo i retry interni di CrewAI/LiteLLM, il
    modello non restituisce un output conforme allo schema: meglio
    un errore esplicito che una risposta silenziosamente sbagliata
    mandata a un cliente reale.
    """
    route_request = _route_request_for_message(messaggio, billing, intent)
    route = route_llm(route_request)
    errors: list[str] = []
    for model in [route.model, *route.fallback_models]:
        try:
            crew = crea_crew(profilo, messaggio, cronologia, route_request=route_request, model=model)
            return _validate_output(crew.kickoff())
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    raise RuntimeError("Tutti i modelli configurati hanno fallito. " + " | ".join(errors))


async def genera_risposta_async(
    messaggio: MessaggioInput,
    profilo: ProfiloAttivita,
    billing: dict | None = None,
    contesto_documenti: str = "",
    intent: str | None = None,
) -> RispostaOutput:
    """Versione asincrona di genera_risposta per essere usata da route
    FastAPI che girano in un event loop già attivo.

    Audit 3.3: limitata dal semaforo globale LLM_CONCURRENCY_SEM per non
    saturare il rate-limit/budget condiviso su OpenRouter quando piu'
    tenant generano risposte in parallelo."""
    route_request = _route_request_for_message(messaggio, billing, intent)
    route = route_llm(route_request)
    errors: list[str] = []
    async with LLM_CONCURRENCY_SEM:
        for model in [route.model, *route.fallback_models]:
            try:
                crew = crea_crew(profilo, messaggio, route_request=route_request, model=model,
                                 contesto_documenti=contesto_documenti)
                return _validate_output(await crew.kickoff_async())
            except Exception as exc:
                errors.append(f"{model}: {exc}")
    raise RuntimeError("Tutti i modelli configurati hanno fallito. " + " | ".join(errors))
