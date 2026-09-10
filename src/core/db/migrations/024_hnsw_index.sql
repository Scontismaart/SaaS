-- 024_hnsw_index.sql
-- Separato da schema.sql perche' richiede pgvector con supporto hnsw
-- (non presente in tutti gli ambienti Docker di test).
-- Se fallisce, le semantic search via HNSW non sono disponibili,
-- ma il resto del sistema funziona (ivfflat rimane come fallback).

DO $$
BEGIN
    BEGIN
        CREATE INDEX IF NOT EXISTS idx_chunks_org_embedding ON document_chunks
            USING hnsw (embedding vector_cosine_ops);
    EXCEPTION WHEN undefined_object THEN
        RAISE NOTICE 'HNSW / vector_cosine_ops non disponibile su questa versione di pgvector, indice saltato';
    END;
END $$;

