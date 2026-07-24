import os
import uuid

import chromadb
from chromadb.config import Settings

from src.core.documenti.embeddings import vettorizza

_COLLECTION = None


def _collezione():
    global _COLLECTION
    if _COLLECTION is None:
        persist = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "chroma")
        client = chromadb.PersistentClient(
            path=os.path.abspath(persist),
            settings=Settings(anonymized_telemetry=False),
        )
        _COLLECTION = client.get_or_create_collection(name="documenti_locale")
    return _COLLECTION


def aggiungi(chunks: list[str], metadati: list[dict] | None = None, on_progress: callable = None) -> int:
    if not chunks:
        return 0
    ids = [str(uuid.uuid4()) for _ in chunks]
    if metadati is None:
        metadati = [{} for _ in chunks]
    elif len(metadati) != len(chunks):
        metadati = metadati + [{}] * (len(chunks) - len(metadati))
        metadati = metadati[: len(chunks)]

    BATCH = 100
    tutti_embeds = []
    for start in range(0, len(chunks), BATCH):
        end = start + BATCH
        batch_chunks = chunks[start:end]
        batch_metas = metadati[start:end] if metadati else [{}] * len(batch_chunks)
        batch_ids = ids[start:end]
        batch_emb = vettorizza(batch_chunks, tipo="passage")
        tutti_embeds.extend(batch_emb)
        _collezione().add(ids=batch_ids, embeddings=batch_emb, documents=batch_chunks, metadatas=batch_metas)
        if on_progress:
            on_progress(end, len(chunks))

    return len(chunks)


def cerca(query: str, k: int = 5) -> list[tuple[str, dict, float]]:
    q_emb = vettorizza([query], tipo="query")[0]
    results = _collezione().query(
        query_embeddings=[q_emb],
        n_results=k,
        where={"tipo": {"$in": ["upload", "documento"]}},
    )
    out: list[tuple[str, dict, float]] = []
    if results["documents"] and results["metadatas"] and results["distances"]:
        for doc, meta, dist in zip(
            results["documents"][0], results["metadatas"][0], results["distances"][0]
        ):
            out.append((doc, meta, float(dist)))
    return out


def conteggio() -> int:
    return _collezione().count()


def elenco_fonti() -> list[dict]:
    """Restituisce i documenti presenti nella knowledge base, raggruppati per fonte."""
    try:
        metadatas = _collezione().get(include=["metadatas"]).get("metadatas") or []
    except Exception:
        return []

    fonti: dict[str, dict] = {}
    for metadata in metadatas:
        nome = (metadata or {}).get("fonte") or "documento"
        tipo = (metadata or {}).get("tipo") or "upload"
        if tipo == "email":
            continue
        documento_id = (metadata or {}).get("document_id") or f"legacy:{nome}"
        entry = fonti.setdefault(documento_id, {
            "id": documento_id,
            "nome": nome,
            "tipo": tipo,
            "chunk": 0,
            "caricato_il": (metadata or {}).get("caricato_il", ""),
        })
        entry["chunk"] += 1
    return sorted(fonti.values(), key=lambda fonte: fonte["caricato_il"] or fonte["nome"].lower(), reverse=True)


def elimina_documento(documento_id: str) -> int:
    if documento_id.startswith("legacy:"):
        deleted = _collezione().get(where={"fonte": documento_id.removeprefix("legacy:")})
        ids = deleted.get("ids") or []
    else:
        deleted = _collezione().get(where={"document_id": documento_id})
        ids = deleted.get("ids") or []
    if ids:
        _collezione().delete(ids=ids)
    return len(ids)


def msg_ids_indicizzati() -> set[str]:
    """Restituisce l'insieme dei msg_id (email) già presenti nella collezione,
    usato per l'indicizzazione incrementale (evita di riscaricare e
    ri-embeddare email già indicizzate ad ogni run)."""
    try:
        risultato = _collezione().get(where={"tipo": "email"}, include=["metadatas"])
    except Exception:
        return set()
    metadatas = risultato.get("metadatas") or []
    return {m.get("msg_id") for m in metadatas if m.get("msg_id")}


def resetta():
    global _COLLECTION
    _COLLECTION = None
    import gc
    gc.collect()
    persist = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "chroma")
    persist = os.path.abspath(persist)
    import shutil
    if os.path.exists(persist):
        shutil.rmtree(persist)
