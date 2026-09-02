"""
dati_struttura.py
-----------------
Gestione e indicizzazione unificata dei Dati Struttura (Priorità 1 - Massima autorevolezza):
Listino servizi tipizzato e orari di apertura ufficiali.
"""

from __future__ import annotations

import logging
from typing import Any
import uuid

from src.core.documenti.chunking import chunk_testo
from src.core.documenti.embeddings import vettorizza

logger = logging.getLogger(__name__)


async def indicizza_dati_struttura(
    repo: Any,
    organization_id: str,
    orari: str,
    servizi_dicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Indicizza i dati struttura ufficiali (servizi e orari) come fonte a Priorità 1
    e sincronizza organizations.business_profile."""
    if servizi_dicts is None:
        bp_curr = await repo.get_org_business_profile(organization_id) or {}
        servizi_dicts = bp_curr.get("servizi_strutturati") or []

    righe_servizi: list[str] = []
    for s in servizi_dicts:
        prezzo = float(s.get("prezzo", 0.0))
        durata = s.get("durata_minuti", 30)
        op = s.get("operatore", "")
        op_str = f" | Operatore: {op}" if op else ""
        righe_servizi.append(
            f"- {s.get('nome', '')}: Prezzo {prezzo:.2f}€ | Durata {durata} min{op_str}"
        )

    testo_servizi = "\n".join(righe_servizi) if righe_servizi else "Nessun servizio specifico configurato."
    testo_completo = (
        "DATI STRUTTURA AUTOREVOLI DELL'ATTIVITÀ (PRIORITÀ 1 - MASSIMA):\n"
        "Listino Servizi Ufficiale:\n"
        f"{testo_servizi}\n\n"
        f"Orari di Apertura Ufficiali:\n{orari or 'Orari non specificati'}\n"
    )

    existing_docs = await repo.list_sources(organization_id, tipo="dati_struttura")
    if existing_docs:
        doc_id = existing_docs[0]["id"]
        await repo.update_document(
            organization_id,
            doc_id,
            nome="Dati struttura e listino servizi",
            is_active=True,
            stato="indicizzata",
            errore="",
            metadata={"servizi": servizi_dicts, "orari": orari},
        )
        await repo.delete_document_chunks(organization_id, doc_id)
    else:
        record = await repo.create_document(
            organization_id,
            nome="Dati struttura e listino servizi",
            tipo="dati_struttura",
            fonte="dati_struttura",
            is_active=True,
            stato="indicizzata",
            metadata={"servizi": servizi_dicts, "orari": orari},
        )
        doc_id = record["id"]

    chunks = chunk_testo(testo_completo)
    if chunks:
        embeds = vettorizza(chunks, tipo="passage")
        for i, (chunk, emb) in enumerate(zip(chunks, embeds)):
            await repo.add_chunk(
                organization_id,
                doc_id,
                i,
                chunk,
                emb,
                {"fonte": "Dati struttura", "tipo": "dati_struttura", "document_id": str(doc_id)},
            )

    bp = await repo.get_org_business_profile(organization_id) or {}
    bp["servizi_strutturati"] = servizi_dicts
    if servizi_dicts:
        bp["servizi_principali"] = [f"{s.get('nome')} ({float(s.get('prezzo', 0)):.2f}€)" for s in servizi_dicts]
    if orari:
        bp["orari"] = orari
    await repo.update_org_business_profile(organization_id, bp)

    if orari and hasattr(repo, "pool"):
        try:
            async with repo.pool.acquire() as conn:
                await conn.execute(
                    "UPDATE onboarding_profiles SET orari = $2 WHERE organization_id = $1",
                    organization_id, orari
                )
        except Exception as exc:
            logger.warning("update onboarding_profiles orari failed: %s", exc)

    try:
        await repo.faq_cache_invalidate(organization_id)
    except Exception as exc:
        logger.warning("faq_cache invalidation failed org=%s: %s", organization_id, exc)

    return {
        "doc_id": str(doc_id),
        "orari": orari,
        "servizi": servizi_dicts,
    }
