"""
responder_agent.py
-------------------
L'agente unico dell'MVP: riceve un messaggio cliente + profilo attività,
restituisce una RispostaOutput strutturata (risposta pronta + flag escalation).

Un solo Agent, un solo Task: niente pipeline multi-agente qui, sarebbe
overengineering per questo step. Se in futuro servirà un secondo agente
(es. per generare il riepilogo dashboard), si aggiunge come modulo a parte.
"""

from crewai import Agent, Crew, Process, Task

from src.agents.prompts import (
    costruisci_system_prompt,
    costruisci_user_prompt,
    formatta_cronologia,
)
from src.core.llm_config import LLMRouteRequest, crea_llm
from src.models.schemas import MessaggioInput, ProfiloAttivita, RispostaOutput


def crea_responder_agent(
    profilo: ProfiloAttivita,
    route_request: LLMRouteRequest | None = None,
    model: str | None = None,
    variante: str = "control",
) -> Agent:
    """Costruisce l'agente con il backstory calibrato sul profilo attività.
    Il backstory in CrewAI funziona come parte del system prompt. La
    variante A/B (task 12) aggiunge istruzioni di stile in coda."""

    return Agent(
        role=f"Assistente clienti di {profilo.nome}",
        goal=(
            "Rispondere ai messaggi dei clienti in modo pertinente e nel tono "
            "corretto, riconoscendo sempre quando un caso va girato a un umano "
            "invece di essere gestito in autonomia."
        ),
        backstory=costruisci_system_prompt(profilo, variante=variante),
        llm=crea_llm(model=model, route_request=route_request),
        verbose=False,
        allow_delegation=False,
    )


def crea_responder_task(agent: Agent, messaggio: MessaggioInput, cronologia: list[tuple[str, str]] | None = None,
                        contesto_documenti: str = "") -> Task:
    """Il task che genera l'output strutturato. output_pydantic forza
    CrewAI a validare/parsare la risposta del modello nello schema
    RispostaOutput — è la nostra rete di sicurezza contro le risposte
    testuali non conformi tipiche dei modelli free."""

    cronologia_testo = formatta_cronologia(cronologia or [])
    descrizione = f"{cronologia_testo}\n\n" if cronologia_testo else ""
    if contesto_documenti.strip():
        descrizione += (
            "Contesto dai documenti dell'attivita' (usa queste informazioni "
            "solo se rilevanti per la domanda del cliente, senza inventare nulla):\n"
            f"{contesto_documenti}\n\n"
        )
    descrizione += (
        costruisci_user_prompt(messaggio)
        + "\n\nAnalizza il messaggio secondo le regole ricevute e "
        "restituisci la risposta strutturata richiesta."
    )
    return Task(
        description=descrizione,
        expected_output=(
            "Un oggetto con: risposta (testo pronto per il cliente), "
            "richiede_umano (bool), motivo (breve spiegazione), "
            "categoria (etichetta del tipo di richiesta)."
        ),
        agent=agent,
        output_pydantic=RispostaOutput,
    )


def crea_crew(
    profilo: ProfiloAttivita,
    messaggio: MessaggioInput,
    cronologia: list[tuple[str, str]] | None = None,
    route_request: LLMRouteRequest | None = None,
    model: str | None = None,
    contesto_documenti: str = "",
    variante: str = "control",
) -> Crew:
    """Assembla agente + task in una Crew pronta per il kickoff.
    Process.sequential è l'unico sensato con un solo task."""

    agent = crea_responder_agent(profilo, route_request=route_request, model=model, variante=variante)
    task = crea_responder_task(agent, messaggio, cronologia, contesto_documenti)

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )
