"""
rag_context.py
--------------
Retrieval RAG org-scoped condiviso tra i path che alimentano il responder:
la preview del wizard onboarding e il flusso WhatsApp reale. Produce il
testo di contesto da iniettare nel prompt (parametro `contesto_documenti`
di genera_risposta_async).

Mai bloccante per il path di produzione: su errore O timeout restituisce
contesto vuoto, cosi' un retrieval lento o rotto non lascia mai un
messaggio cliente appeso. Il filtro per organization_id vive nella query
SQL (`WHERE ... organization_id = $1`), quindi il contesto di un tenant non
puo' contenere chunk di un altro.
"""

import asyncio

from src.core.documenti.embeddings import vettorizza

DEFAULT_K = 3
DEFAULT_TIMEOUT = 3.0


async def recupera_contesto_documenti(
    organization_id: str,
    testo: str,
    repo,
    k: int = DEFAULT_K,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Recupera i k chunk piu' simili a `testo` tra i documenti dell'org e li
    formatta per il prompt. Restituisce '' se non ci sono risultati, in caso
    di errore o se il retrieval sfora `timeout` secondi."""
    try:
        q_emb = await asyncio.to_thread(vettorizza, [testo], tipo="query")
        risultati = await asyncio.wait_for(
            repo.search_similar(organization_id, q_emb[0], k),
            timeout=timeout,
        )
    except Exception as e:
        print(f"[rag_context] retrieval non disponibile org={organization_id}: {e}")
        return ""

    if not risultati:
        return ""

    blocchi = []
    for r in risultati:
        nome = (
            r.get("document_name")
            or (r.get("metadata") or {}).get("fonte")
            or "documento"
        )
        blocchi.append(f"-- {nome} --\n{r['content']}")
    return "\n\n".join(blocchi)
