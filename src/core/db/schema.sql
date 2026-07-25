-- ============================================================
-- EXTENSION
-- ============================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- 1. BOOKINGS (sostituisce Airtable + _prenotazioni_demo)
-- ============================================================
CREATE TABLE IF NOT EXISTS bookings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    contact_id          UUID REFERENCES contacts(id),
    nome_cliente        TEXT NOT NULL,
    telefono            TEXT NOT NULL DEFAULT '',
    data                DATE NOT NULL,
    ora                 TIME NOT NULL,
    coperti             INT CHECK (coperti > 0),
    note                TEXT NOT NULL DEFAULT '',
    stato               TEXT NOT NULL DEFAULT 'in_attesa'
                        CHECK (stato IN ('in_attesa','confermata','cancellata','no_show','completata')),
    origine             TEXT NOT NULL DEFAULT 'Dashboard',
    richiede_intervento BOOLEAN NOT NULL DEFAULT FALSE,
    id_conversazione    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bookings_org_data ON bookings(organization_id, data);

-- ============================================================
-- 2. BOOKING_SETTINGS (sostituisce capienze orarie in RAM)
-- ============================================================
CREATE TABLE IF NOT EXISTS booking_settings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) UNIQUE,
    slot_minutes        INT NOT NULL DEFAULT 60,
    fasce_orarie        JSONB,
    capienze_orarie     JSONB,
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id)
);

-- ============================================================
-- 3. REVIEWS
-- ============================================================
CREATE TABLE IF NOT EXISTS reviews (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    contact_id          UUID REFERENCES contacts(id),
    testo               TEXT NOT NULL,
    valutazione_stelle  INT CHECK (valutazione_stelle BETWEEN 1 AND 5),
    fonte               TEXT NOT NULL DEFAULT 'manuale',
    autore              TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reviews_org ON reviews(organization_id);

-- ============================================================
-- 4. DOCUMENTS (metadati)
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    nome                TEXT NOT NULL,
    tipo                TEXT NOT NULL DEFAULT 'upload',
    fonte               TEXT NOT NULL DEFAULT '',
    caricato_il         TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_documents_org ON documents(organization_id);

-- ============================================================
-- 5. DOCUMENT_CHUNKS (pgvector, sostituisce ChromaDB)
-- ============================================================
CREATE TABLE IF NOT EXISTS document_chunks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    document_id         UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index         INT NOT NULL,
    content             TEXT NOT NULL,
    embedding           vector(384) NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chunks_org_doc ON document_chunks(organization_id, document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_org_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops);

-- Trigger: garantisce coerenza organization_id tra chunk e documento
CREATE OR REPLACE FUNCTION check_chunk_org_consistency() RETURNS trigger AS $$
BEGIN
  IF NEW.organization_id != (SELECT organization_id FROM documents WHERE id = NEW.document_id) THEN
    RAISE EXCEPTION
      'organization_id mismatch: chunk belongs to org %, document belongs to org %',
      NEW.organization_id,
      (SELECT organization_id FROM documents WHERE id = NEW.document_id);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_chunk_org ON document_chunks;
CREATE CONSTRAINT TRIGGER trg_check_chunk_org
    AFTER INSERT OR UPDATE ON document_chunks
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_chunk_org_consistency();

-- ============================================================
-- 6. EMAIL_CONFIGS (sostituisce email_config.json)
-- ============================================================
CREATE TABLE IF NOT EXISTS email_configs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    indirizzo           TEXT NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, indirizzo)
);

-- ============================================================
-- 7. USAGE_EVENTS (billing)
-- ============================================================
CREATE TABLE IF NOT EXISTS usage_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    event_type          TEXT NOT NULL,
    quantity            INT NOT NULL DEFAULT 1,
    metadata            JSONB NOT NULL DEFAULT '{}',
    billing_month       DATE GENERATED ALWAYS AS
                        (date_trunc('month', created_at AT TIME ZONE 'UTC')::date) STORED,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_usage_events_org_month ON usage_events(organization_id, billing_month);

-- ============================================================
-- 8. EVENT_LOG (proiezione derivata da trigger, mai scritta dal codice)
-- ============================================================
CREATE TABLE IF NOT EXISTS event_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    source_table        TEXT NOT NULL,
    source_id           UUID NOT NULL,
    tipo_evento         TEXT NOT NULL,
    priorita            TEXT NOT NULL,
    testo_originale     TEXT NOT NULL DEFAULT '',
    risposta_ai         TEXT NOT NULL DEFAULT '',
    gestito_da_ai       BOOLEAN NOT NULL DEFAULT TRUE,
    dettagli            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_event_log_org_created ON event_log(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_org_priorita ON event_log(organization_id, priorita)
    WHERE priorita != 'bassa';
