-- Migration 034: GDPR export token persistiti su database.
--
-- Prima i token vivevano in un dict in-memory (src/core/gdpr/routes.py):
-- persi al restart del processo e non condivisi tra i worker Docker
-- (api, worker-inbound, worker-retry, supervisor). Ogni token e' ora una
-- riga in DB: sopravvive ai restart, e' visibile da qualunque replica e
-- il consumo e' atomico via DELETE ... RETURNING (sicuro con piu' worker
-- concorrenti: una sola replica puo' consumare lo stesso token).

CREATE TABLE IF NOT EXISTS gdpr_export_tokens (
    token       TEXT PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    data        JSONB NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Cleanup efficiente dei token scaduti (pulizia piggyback su ogni accesso
-- e su ogni nuova richiesta di export).
CREATE INDEX IF NOT EXISTS idx_gdpr_export_tokens_expires_at
    ON gdpr_export_tokens(expires_at);
