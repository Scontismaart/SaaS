-- Migration 046: Knowledge Base Upgrade (FAQ, Web, Dati struttura, stato e toggle)
-- Aggiunge campi per tracciare lo stato della fonte (indicizzata, elaborazione, errore),
-- il flag is_active (per attivazione/disattivazione senza cancellazione),
-- il messaggio di errore esplicito e i metadati tipizzati.

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS stato TEXT NOT NULL DEFAULT 'indicizzata',
    ADD COLUMN IF NOT EXISTS errore TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_documents_org_active_stato ON documents(organization_id, is_active, stato);
CREATE INDEX IF NOT EXISTS idx_documents_org_tipo ON documents(organization_id, tipo);
