from src.agents.review_agent import crea_review_crew
from src.models.schemas import RispostaRecensioneOutput


def genera_risposta_recensione(
    testo: str,
    stelle: int | None = None,
    autore: str = "",
) -> RispostaRecensioneOutput:
    crew = crea_review_crew(testo, stelle, autore)
    risultato = crew.kickoff()

    output = risultato.pydantic
    if output is None or not isinstance(output, RispostaRecensioneOutput):
        raise RuntimeError(
            "Il modello non ha restituito un output conforme a "
            "RispostaRecensioneOutput."
        )

    return output
