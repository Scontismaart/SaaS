from src.agents.review_agent import crea_review_crew
from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, route_llm
from src.models.schemas import LINGUA_DEFAULT, RispostaRecensioneOutput
import time


def genera_risposta_recensione(
    testo: str,
    stelle: int | None = None,
    autore: str = "",
    billing: dict | None = None,
    lingue_supportate: list[str] | None = None,
    lingua_default: str = LINGUA_DEFAULT,
    profilo_attivita: dict | None = None,
    contesto_documenti: str = "",
    usage_sink: dict | None = None,
) -> RispostaRecensioneOutput:
    route = route_llm(
        LLMRouteRequest(
            task_type="review",
            user_text=testo,
            remaining_budget_ratio=budget_ratio_from_billing(billing),
        )
    )
    errors: list[str] = []
    # Review drafts use one authorized provider invocation. A fallback would be
    # a second billable call beyond the single org-scoped rate-limit reservation.
    for attempt_index, model in enumerate([route.model]):
        crew = None
        attempt_started = time.monotonic()
        try:
            crew = crea_review_crew(
                testo, stelle, autore, model=model,
                lingue_supportate=lingue_supportate,
                lingua_default=lingua_default,
                profilo_attivita=profilo_attivita,
                contesto_documenti=contesto_documenti,
            )
            risultato = crew.kickoff()
            break
        except Exception as exc:
            errors.append(model)
        finally:
            if usage_sink is not None and crew is not None:
                metrics = getattr(crew, "usage_metrics", None)
                attempts = usage_sink.setdefault("attempts", [])
                attempts.append({
                    "model": model,
                    "reason": route.reason,
                    "prompt_tokens": getattr(metrics, "prompt_tokens", None),
                    "completion_tokens": getattr(metrics, "completion_tokens", None),
                    "total_tokens": getattr(metrics, "total_tokens", None),
                    "latency_ms": int((time.monotonic() - attempt_started) * 1000),
                    "fallback": attempt_index > 0,
                })
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
