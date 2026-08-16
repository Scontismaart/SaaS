"""
rag_context.py
--------------
Retrieval RAG org-scoped condiviso tra i path che alimentano il responder:
la preview del wizard onboarding e il flusso WhatsApp reale. Produce il
testo di contesto da iniettare nel prompt (parametro `contesto_documenti`
di genera_risposta_async) e i chunk strutturati che il guardrail post-LLM
usa per verificare il grounding dei prezzi (task 12).

Mai bloccante per il path di produzione: su errore O timeout restituisce
contesto vuoto, cosi' un retrieval lento o rotto non lascia mai un
messaggio cliente appeso. Il filtro per organization_id vive nella query
SQL (`WHERE ... organization_id = $1`), quindi il contesto di un tenant non
puo' contenere chunk di un altro.
"""

import asyncio
from dataclasses import dataclass, field

from src.core.documenti.embeddings import vettorizza

DEFAULT_K = 3
DEFAULT_TIMEOUT = 3.0


@dataclass(frozen=True)
class ContestoDocumenti:
    """Esito del retrieval: `testo` e' la forma per il prompt (blocchi
    '-- nome --' concatenati), `chunks` la lista strutturata restituita da
    search_similar (content, metadata, document_name, ...) per i guardrail.
    Falsy quando non c'e' contesto (nessun chunk)."""

    testo: str = ""
    chunks: list[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.chunks)


async def recupera_contesto_documenti(
    organization_id: str,
    testo: str,
    repo,
    k: int = DEFAULT_K,
    timeout: float = DEFAULT_TIMEOUT,
    q_emb: list[float] | None = None,
) -> ContestoDocumenti:
    """Recupera i k chunk piu' simili a `testo` tra i documenti dell'org e
    li formatta per il prompt. Restituisce ContestoDocumenti vuoto se non
    ci sono risultati, in caso di errore o se il retrieval sfora `timeout`
    secondi. `q_emb` permette di riusare un embedding gia' calcolato dal
    chiamante (es. cache FAQ): se assente viene calcolato qui."""
    try:
        if q_emb is None:
            q_emb = (await asyncio.to_thread(vettorizza, [testo], tipo="query"))[0]
        risultati = await asyncio.wait_for(
            repo.search_similar(organization_id, q_emb, k),
            timeout=timeout,
        )
    except Exception as e:
        print(f"[rag_context] retrieval non disponibile org={organization_id}: {e}")
        return ContestoDocumenti()

    if not risultati:
        return ContestoDocumenti()

    blocchi = []
    for r in risultati:
        nome = (
            r.get("document_name")
            or (r.get("metadata") or {}).get("fonte")
            or "documento"
        )
        blocchi.append(f"-- {nome} --\n{r['content']}")
    return ContestoDocumenti(testo="\n\n".join(blocchi), chunks=risultati)
