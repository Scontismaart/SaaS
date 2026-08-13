from crewai import Agent, Task, Crew, Process

from src.core.llm_config import LLMRouteRequest, crea_llm
from src.agents.review_prompts import (
    costruisci_system_prompt_review,
    costruisci_user_prompt_review,
)
from src.models.schemas import RispostaRecensioneOutput


def crea_review_agent(model: str | None = None) -> Agent:
    return Agent(
        role="Esperto gestione reputazione online",
        goal=(
            "Analizzare recensioni dei clienti e produrre bozze di risposta "
            "professionali, misurate, mai difensive."
        ),
        backstory=costruisci_system_prompt_review(),
        llm=crea_llm(
            model=model,
            temperature=0.3,
            route_request=LLMRouteRequest(task_type="review"),
        ),
        verbose=False,
        allow_delegation=False,
    )


def crea_review_task(
    agent: Agent,
    testo: str,
    stelle: int | None = None,
    autore: str = "",
) -> Task:
    descrizione = costruisci_user_prompt_review(testo, stelle, autore)

    return Task(
        description=descrizione,
        expected_output=(
            "Un oggetto RispostaRecensioneOutput con: bozza_risposta (stringa), "
            "sentiment (positiva/neutra/negativa), richiede_revisione_urgente "
            "(bool), motivo (stringa), categoria (stringa)."
        ),
        agent=agent,
        output_pydantic=RispostaRecensioneOutput,
    )


def crea_review_crew(
    testo: str,
    stelle: int | None = None,
    autore: str = "",
    model: str | None = None,
) -> Crew:
    agent = crea_review_agent(model=model)
    task = crea_review_task(agent, testo, stelle, autore)

    return Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )
