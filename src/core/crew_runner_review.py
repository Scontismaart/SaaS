from src.agents.review_agent import crea_review_crew
from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, route_llm
from src.models.schemas import RispostaRecensioneOutput


def genera_risposta_recensione(
    testo: str,
    stelle: int | None = None,
    autore: str = "",
    billing: dict | None = None,
) -> RispostaRecensioneOutput:
    route = route_llm(
        LLMRouteRequest(
            task_type="review",
            user_text=testo,
            remaining_budget_ratio=budget_ratio_from_billing(billing),
        )
    )
    errors: list[str] = []
    for model in [route.model, *route.fallback_models]:
        try:
            crew = crea_review_crew(testo, stelle, autore, model=model)
            risultato = crew.kickoff()
            break
        except Exception as exc:
            errors.append(f"{model}: {exc}")
    else:
        raise RuntimeError(
            "Tutti i modelli configurati hanno fallito. " + " | ".join(errors)
        )

    output = risultato.pydantic
    if output is None or not isinstance(output, RispostaRecensioneOutput):
        raise RuntimeError(
            "Il modello non ha restituito un output conforme a "
            "RispostaRecensioneOutput."
        )

    return output
