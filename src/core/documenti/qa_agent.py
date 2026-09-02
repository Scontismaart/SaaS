import json
import logging
from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, crea_llm, route_llm
from src.core.documenti.embeddings import vettorizza
from src.core.documenti.priorita import GERARCHIA_REGOLA_PROMPT, formatta_chunk_con_priorita, get_priorita_num
from src.core.verticals import get_vertical_strategy

logger = logging.getLogger(__name__)


async def rispondi(
    organization_id: str,
    domanda: str,
    repo,
    k: int = 5,
    billing: dict | None = None,
) -> dict:
    q_emb = vettorizza([domanda], tipo="query")[0]
    risultati = await repo.search_similar(organization_id, q_emb, k, only_active=True)

    if not risultati:
        return {
            "risposta": "Non ho trovato documenti o fonti rilevanti nella knowledge base per rispondere alla domanda.",
            "fonti": [],
        }

    # Ordina per priorità di fonte poi per distanza semantica
    def _sort_key(r):
        meta = r.get("metadata") or {}
        tipo = meta.get("tipo") or r.get("tipo") or "documento"
        return (get_priorita_num(tipo), r.get("distance", 0.0))

    risultati_ordinati = sorted(risultati, key=_sort_key)
    contesto = "\n\n".join(formatta_chunk_con_priorita(r) for r in risultati_ordinati)

    fonti_dict = {}
    for r in risultati_ordinati:
        meta = r.get("metadata") or {}
        tipo = meta.get("tipo") or r.get("tipo") or "documento"
        nome = (r.get("document_name") or meta.get("fonte") or "documento").strip()
        if not nome:
            nome = "documento"
        score = round(r["distance"], 4)
        stato = r.get("stato") or meta.get("stato") or "indicizzata"
        is_active = r.get("is_active", True)
        if nome not in fonti_dict or score < fonti_dict[nome]["score"]:
            fonti_dict[nome] = {
                "documento": nome,
                "score": score,
                "tipo": tipo,
                "stato": stato,
                "is_active": is_active,
                "priorita": get_priorita_num(tipo),
            }
    fonti = sorted(fonti_dict.values(), key=lambda f: (f["priorita"], f["score"]))

    # Recupera il profilo e il verticale reale dell'organizzazione per il tono corretto
    verticale = None
    nome_attivita = "l'attività"
    try:
        raw_bp = await repo.get_org_business_profile(organization_id)
        if isinstance(raw_bp, str):
            raw_bp = json.loads(raw_bp)
        if isinstance(raw_bp, dict):
            verticale = raw_bp.get("verticale")
            nome_attivita = raw_bp.get("nome") or nome_attivita
    except Exception as e:
        logger.warning("[qa_agent] Recupero business profile fallito per org %s: %s", organization_id, e)

    strategy = get_vertical_strategy(verticale, organization_id=str(organization_id))

    prompt = (
        f"Sei l'assistente virtuale e knowledge base di \"{nome_attivita}\", {strategy.label}.\n"
        "Il tuo compito è rispondere con precisione alle domande basandoti esclusivamente "
        "sulla conoscenza fornita di seguito (Dati struttura, FAQ, Documenti e Pagine web).\n\n"
        f"{GERARCHIA_REGOLA_PROMPT}\n\n"
        "Linee guida:\n"
        "- Rispondi nella stessa lingua della domanda\n"
        "- Basati RIGOROSAMENTE sulle fonti fornite qui sotto\n"
        "- Se le fonti non contengono l'informazione richiesta, dillo chiaramente e con gentilezza senza inventare nulla\n"
        "- Se riscontri informazioni o prezzi in contrasto, applica sempre la fonte a priorità più alta (Dati struttura > FAQ > Documenti > Pagine web)\n"
        "- Organizza la risposta in modo chiaro, sintetico ed elegante\n\n"
        f"Conoscenza disponibile:\n{contesto}\n\n"
        f"Domanda: {domanda}"
    )

    try:
        route = route_llm(
            LLMRouteRequest(
                task_type="document_qa",
                user_text=domanda,
                remaining_budget_ratio=budget_ratio_from_billing(billing),
            )
        )
        errors: list[str] = []
        risposta_raw = None
        for model in [route.model, *route.fallback_models]:
            try:
                llm = crea_llm(model=model, temperature=0.15)
                risposta_raw = llm.call(prompt)
                break
            except Exception as e:
                errors.append(f"{model}: {e}")
        if risposta_raw is None:
            raise RuntimeError("Tutti i modelli configurati hanno fallito. " + " | ".join(errors))
        risposta = str(risposta_raw).strip() if risposta_raw else (
            "Impossibile generare una risposta."
        )
    except Exception as e:
        logger.error("[qa_agent] Errore LLM: %s", e)
        risposta = (
            "Non ho potuto analizzare i documenti in questo momento. "
            "Riprova più tardi."
        )

    return {"risposta": risposta, "fonti": fonti}
