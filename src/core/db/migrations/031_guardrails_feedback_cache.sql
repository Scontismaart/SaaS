-- Migration 031: guardrails (roadmap task 12)
--
-- 1) faq_cache: cache semantica delle risposte FAQ piu' frequenti, per
--    risparmiare token/latenza sulle domande ripetute (orari, prezzi del
--    menu, ...). Org-scoped: il lookup filtra per organization_id nella
--    query SQL, stessa barriera del RAG (document_chunks). L'embedding e'
--    lo stesso MiniLM multilingue del RAG (384 dim), cosi' il processor
--    calcola un solo embedding per messaggio e lo riusa per cache + RAG.
--    Scadenza (expires_at, default 72h) e invalidazione esplicita quando
--    l'org carica un nuovo documento (i prezzi potrebbero essere cambiati).
--
-- 2) message_feedback: log 👍/👎 sulle risposte AI (task 12 "feedback loop
--    con log per iterare sui prompt"). Due sorgenti: emoji del cliente
--    (un feedback per messaggio) e pulsanti dello staff nell'inbox (uno
--    per operatore per messaggio). FK su messages ON DELETE CASCADE per
--    rispettare la retention/GDPR.

CREATE TABLE IF NOT EXISTS faq_cache (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    question_text       TEXT NOT NULL,
    question_hash       TEXT NOT NULL,
    question_embedding  vector(384) NOT NULL,
    answer_text         TEXT NOT NULL,
    prompt_variant      TEXT NOT NULL DEFAULT 'control',
    hit_count           INT NOT NULL DEFAULT 0,
    last_used_at        TIMESTAMPTZ,
    expires_at          TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_faq_cache_org ON faq_cache(organization_id);
CREATE INDEX IF NOT EXISTS idx_faq_cache_org_expires ON faq_cache(organization_id, expires_at);
-- Dedup per testo identico della stessa org (hash sha256 del testo
-- normalizzato): la stessa domanda re-insertita aggiorna risposta/scadenza.
CREATE UNIQUE INDEX IF NOT EXISTS uq_faq_cache_org_question
    ON faq_cache(organization_id, question_hash);
-- Niente indice vettoriale: la cache di un locale resta piccola (decine di
-- righe), l'ordinamento <=> sequenziale e' trascurabile. Se cresce, si
-- aggiunge hnsw come per document_chunks (024).

CREATE TABLE IF NOT EXISTS message_feedback (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    message_id          UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id     UUID NOT NULL,
    source              TEXT NOT NULL CHECK (source IN ('customer_emoji', 'staff_ui')),
    value               TEXT NOT NULL CHECK (value IN ('up', 'down')),
    created_by_user_id  UUID,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_message_feedback_org ON message_feedback(organization_id);
CREATE INDEX IF NOT EXISTS idx_message_feedback_message ON message_feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_message_feedback_conversation ON message_feedback(conversation_id);
-- Un solo feedback cliente per messaggio; per lo staff uno per operatore.
CREATE UNIQUE INDEX IF NOT EXISTS uq_message_feedback_customer
    ON message_feedback(message_id) WHERE source = 'customer_emoji';
CREATE UNIQUE INDEX IF NOT EXISTS uq_message_feedback_staff
    ON message_feedback(message_id, created_by_user_id) WHERE source = 'staff_ui';

-- RLS org-scoped (pattern 008_rls_hardening + 009_rls_write_check).
ALTER TABLE faq_cache ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'faq_cache_org_member') THEN
        CREATE POLICY faq_cache_org_member ON faq_cache
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

ALTER TABLE message_feedback ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'message_feedback_org_member') THEN
        CREATE POLICY message_feedback_org_member ON message_feedback
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;
