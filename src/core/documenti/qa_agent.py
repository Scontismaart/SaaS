from src.core.llm_config import crea_llm
from src.core.documenti.vector_store import cerca


def rispondi(domanda: str, k: int = 5) -> dict:
    risultati = cerca(domanda, k=k)

    if not risultati:
        return {
            "risposta": "Non ho trovato documenti rilevanti per rispondere alla domanda.",
            "fonti": [],
        }

    contesto = "\n\n".join(f"-- Documento --\n{doc}" for doc, _, _ in risultati)

    fonti_dict = {}
    for doc, meta, score in risultati:
        nome = (meta.get("fonte") or "documento").strip()
        if not nome:
            nome = "documento"
        if nome not in fonti_dict or score < fonti_dict[nome]["score"]:
            fonti_dict[nome] = {"documento": nome, "score": round(score, 4)}
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
        llm = crea_llm(temperature=0.15)
        risposta_raw = llm.call(prompt)
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
