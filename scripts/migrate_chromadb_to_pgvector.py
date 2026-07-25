#!/usr/bin/env python3
"""One-shot migration: ChromaDB -> documents + document_chunks.

Usage: python scripts/migrate_chromadb_to_pgvector.py <organization_id>

Reads all chunks from ChromaDB `documenti_locale` collection, creates
document records, and inserts chunks with embeddings into pgvector.
"""

import argparse
import asyncio
import json
import os
import uuid
from collections import defaultdict

import asyncpg
import chromadb
from chromadb.config import Settings


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("organization_id", type=uuid.UUID)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))
    args = parser.parse_args()

    persist = os.path.join("data", "chroma")
    client = chromadb.PersistentClient(
        path=os.path.abspath(persist),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(name="documenti_locale")
    all_data = collection.get(include=["documents", "metadatas", "embeddings"])
    if not all_data["ids"]:
        print("No data in ChromaDB collection")
        return

    doc_chunks = defaultdict(list)
    for i, doc_id in enumerate(all_data["ids"]):
        meta = (all_data["metadatas"] or [{}])[i] or {}
        fonte = meta.get("fonte") or "documento"
        doc_key = meta.get("document_id") or f"legacy:{fonte}"
        doc_chunks[doc_key].append({
            "chunk_id": doc_id,
            "content": (all_data["documents"] or [""])[i],
            "embedding": (all_data["embeddings"] or [[]])[i],
            "metadata": meta,
        })

    pool = await asyncpg.create_pool(dsn=args.dsn)
    try:
        async with pool.acquire() as conn:
            for doc_key, chunks in doc_chunks.items():
                fonte = chunks[0]["metadata"].get("fonte") or "documento"
                doc_uuid = uuid.uuid4()
                await conn.execute("""
                    INSERT INTO documents (id, organization_id, nome, tipo, fonte, caricato_il)
                    VALUES ($1, $2, $3, 'upload', $4, NOW())
                """, doc_uuid, args.organization_id, fonte, fonte)

                for chunk in chunks:
                    vec_str = "[" + ",".join(str(v) for v in chunk["embedding"]) + "]"
                    await conn.execute("""
                        INSERT INTO document_chunks (id, organization_id, document_id,
                                                     chunk_index, content, embedding, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
                    """, uuid.uuid4(), args.organization_id, doc_uuid,
                    chunk["chunk_id"], chunk["content"], vec_str,
                    json.dumps({}))

        print(f"Migrated {len(all_data['ids'])} chunks from {len(doc_chunks)} documents")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
