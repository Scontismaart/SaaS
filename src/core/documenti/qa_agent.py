from src.core.llm_config import LLMRouteRequest, budget_ratio_from_billing, crea_llm, route_llm
from src.core.documenti.embeddings import vettorizza


async def rispondi(
    organization_id: str,
    domanda: str,
    repo,
    k: int = 5,
    billing: dict | None = None,
) -> dict:
    q_emb = vettorizza([domanda], tipo="query")[0]
    risultati = await repo.search_similar(organization_id, q_emb, k)

    if not risultati:
        return {
            "risposta": "Non ho trovato documenti rilevanti per rispondere alla domanda.",
            "fonti": [],
        }

    contesto = "\n\n".join(f"-- Documento --\n{r['content']}" for r in risultati)

    fonti_dict = {}
    for r in risultati:
        nome = (r.get("document_name") or (r.get("metadata") or {}).get("fonte") or "documento").strip()
        if not nome:
            nome = "documento"
        if nome not in fonti_dict or r["distance"] < fonti_dict[nome]["score"]:
            fonti_dict[nome] = {"documento": nome, "score": round(r["distance"], 4)}
    fonti = sorted(fonti_dict.values(), key=lambda f: f["score"])

    prompt = (
        "Sei l'assistente knowledge base di un ristorante. Il tuo compito e' estrarre "
        "informazioni operative da menu, lista allergeni, carta vini e documenti simili, "
        "basandoti esclusivamente sui documenti forniti qui sotto.\n\n"
        "Linee guida:\n"
        "- Rispondi nella stessa lingua della domanda\n"
        "- Basati SOLO sui documenti forniti di seguito\n"
        "- Se i documenti non contengono la risposta, dillo chiaramente\n"
        "- Per allergie o intolleranze, fornisci solo informazioni presenti nei documenti e invita sempre a confermare con lo staff\n"
        "- Organizza la risposta in modo chiaro e leggibile\n"
        "- Alla fine, elenca le fonti che hai usato\n\n"
        f"Documenti disponibili:\n{contesto}\n\n"
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
        print(f"[qa_agent] Errore LLM: {e}")
        risposta = (
            "Non ho potuto analizzare i documenti in questo momento. "
            "Riprova più tardi."
        )

    return {"risposta": risposta, "fonti": fonti}
