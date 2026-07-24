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
from src.models.schemas import MessaggioInput, ProfiloAttivita, RispostaOutput


def genera_risposta(messaggio: MessaggioInput, profilo: ProfiloAttivita, cronologia: list[tuple[str, str]] | None = None) -> RispostaOutput:
    """Esegue la crew su un singolo messaggio e restituisce l'output
    strutturato e validato.

    Solleva eccezione se, dopo i retry interni di CrewAI/LiteLLM, il
    modello non restituisce un output conforme allo schema: meglio
    un errore esplicito che una risposta silenziosamente sbagliata
    mandata a un cliente reale.
    """
    crew = crea_crew(profilo, messaggio, cronologia)
    risultato = crew.kickoff()

    output = risultato.pydantic
    if output is None or not isinstance(output, RispostaOutput):
        raise RuntimeError(
            "Il modello non ha restituito un output conforme a RispostaOutput. "
            "Riprova, o verifica che il modello configurato in llm_config.py "
            "sia ancora disponibile su OpenRouter."
        )

    return output


async def genera_risposta_async(messaggio: MessaggioInput, profilo: ProfiloAttivita) -> RispostaOutput:
    """Versione asincrona di genera_risposta per essere usata da route
    FastAPI che girano in un event loop già attivo."""
    crew = crea_crew(profilo, messaggio)
    risultato = await crew.kickoff_async()

    output = risultato.pydantic
    if output is None or not isinstance(output, RispostaOutput):
        raise RuntimeError(
            "Il modello non ha restituito un output conforme a RispostaOutput. "
            "Riprova, o verifica che il modello configurato in llm_config.py "
            "sia ancora disponibile su OpenRouter."
        )

    return output