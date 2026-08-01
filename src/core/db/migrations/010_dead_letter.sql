-- 010_dead_letter.sql
-- Supporto dead-letter per messaggi inbound bloccati in reclaim loop:
-- reap_stale_claims oggi rimette lo status a 'received_pending_ai' ogni
-- volta che un claim scade, ma se un messaggio continua a far crashare
-- il worker (payload malformato, bug nel processing) resta in loop
-- infinito reclaim -> crash -> reclaim. dead_letter_count conta i
-- re-claim consecutivi; oltre soglia il supervisor lo marca 'dead' e lo
-- toglie dalla coda attiva invece di ritentare all'infinito.

ALTER TABLE messages ADD COLUMN IF NOT EXISTS dead_letter_count INT NOT NULL DEFAULT 0;

ALTER TABLE messages DROP CONSTRAINT IF EXISTS chk_status_by_direction;
ALTER TABLE messages ADD CONSTRAINT chk_status_by_direction CHECK (
    (direction = 'inbound'  AND status IN ('received_pending_ai','processing','handled','dead'))
    OR
    (direction = 'outbound' AND status IN ('queued','processing','sent','delivered','read','failed','sending_ambiguous'))
);

CREATE INDEX IF NOT EXISTS idx_messages_dead ON messages(organization_id)
    WHERE status = 'dead';
