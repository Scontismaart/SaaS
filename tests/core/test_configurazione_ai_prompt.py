from unittest.mock import patch

from src.agents.responder_agent import crea_responder_agent, crea_responder_task
from src.models.schemas import MessaggioInput, ProfiloAttivita


def test_configured_tone_changes_model_context_for_same_customer_message():
    profile = ProfiloAttivita(
        nome="Oasi del Benessere SPA",
        tipo_attivita="Centro estetico",
        verticale="centro_estetico",
        tono="formale_elegante",
        orari="Mar-Sab: 10:00 - 20:00",
        servizi_principali=["Massaggi rilassanti"],
        note_speciali=["Escalare richieste per trattamenti in gravidanza"],
    )
    friendly_profile = profile.model_copy(update={"tono": "informale_amichevole"})
    question = MessaggioInput(testo="Avete disponibilità per un massaggio domani?")

    with patch("src.agents.responder_agent.crea_llm", return_value="openai/mock-model"):
        formal_agent = crea_responder_agent(profile)
        friendly_agent = crea_responder_agent(friendly_profile)

    formal_task = crea_responder_task(formal_agent, question)
    friendly_task = crea_responder_task(friendly_agent, question)

    assert formal_task.description == friendly_task.description
    assert "formale ed elegante" in formal_agent.backstory
    assert "informale e amichevole" in friendly_agent.backstory
    assert formal_agent.backstory != friendly_agent.backstory
