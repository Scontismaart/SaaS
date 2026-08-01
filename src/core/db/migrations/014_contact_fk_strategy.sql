-- 014_contact_fk_strategy.sql
-- Strategia FK per contatti: CASCADE su entita' dipendenti,
-- SET NULL + anonimizzazione PII su bookings/reviews, CASCADE da organizations.
--
-- NOTA: in produzione, anteporre CREATE INDEX CONCURRENTLY per ogni indice
-- per evitare blocchi in scrittura. I CREATE INDEX qui sotto USANO la forma
-- semplice (IF NOT EXISTS) per compatibilita' con ambienti che non supportano
-- CONCURRENTLY in transazione.

-- ============================================================
-- 1. INDICI (B-tree) su tutte le FK coinvolte nella cascata
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_fk_conversations_contact ON conversations(contact_id);
CREATE INDEX IF NOT EXISTS idx_fk_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_fk_bookings_contact ON bookings(contact_id);
CREATE INDEX IF NOT EXISTS idx_fk_reviews_contact ON reviews(contact_id);
CREATE INDEX IF NOT EXISTS idx_fk_consent_log_contact ON contact_consent_log(contact_id);

-- ============================================================
-- 2. CASCADE DA organizations A TUTTE LE FIGLIE
--    Elimina la necessita' di DELETE manuali in delete_organization().
--    Usa DO dinamico per coprire tutte le FK esistenti verso organizations
--    con confdeltype = 'a' (NO ACTION, il default PostgreSQL).
--    string_agg gestisce eventuali FK multi-colonna.
--    %s per regclass evita il doppio quoting.
-- ============================================================
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT con.conname, con.conrelid::regclass AS tbl,
               (SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum)
                FROM pg_attribute a
                WHERE a.attrelid = con.conrelid AND a.attnum = ANY(con.conkey))
               AS col_list
        FROM pg_constraint con
        WHERE con.confrelid = 'organizations'::regclass
          AND con.contype = 'f'
          AND con.confdeltype = 'a'
    ) LOOP
        EXECUTE format(
            'ALTER TABLE %s DROP CONSTRAINT %I, ADD FOREIGN KEY (%s) REFERENCES organizations(id) ON DELETE CASCADE',
            r.tbl, r.conname, r.col_list
        );
    END LOOP;
END;
$$;

-- ============================================================
-- 3. TRIGGER BEFORE DELETE su contacts — anonimizzazione PII
--    Sostituisce nome_cliente/telefono con 'REDACTED' (soppressione,
--    non hash) prima che la FK venga recisa. Si attiva ANCHE durante
--    la cascata da organizations.
-- ============================================================
CREATE OR REPLACE FUNCTION mask_pii_before_contact_delete() RETURNS trigger AS $$
BEGIN
    UPDATE bookings SET
        nome_cliente = 'REDACTED',
        telefono = 'REDACTED',
        contact_id = NULL
    WHERE contact_id = OLD.id;
    UPDATE reviews SET
        autore = 'REDACTED',
        contact_id = NULL
    WHERE contact_id = OLD.id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_mask_pii_before_contact_delete ON contacts;
CREATE TRIGGER trg_mask_pii_before_contact_delete
    BEFORE DELETE ON contacts
    FOR EACH ROW EXECUTE FUNCTION mask_pii_before_contact_delete();

-- ============================================================
-- 4. TRIGGER AFTER UPDATE su contacts — propaga soft-delete
--    Quando deleted_at viene impostato, le conversazioni collegate
--    ricevono deleted_at = NOW(). Bookings/reviews NON vengono toccate:
--    il loro FK rimane valido fino all'hard-delete.
-- ============================================================
CREATE OR REPLACE FUNCTION propagate_contact_soft_delete() RETURNS trigger AS $$
BEGIN
    IF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
        UPDATE conversations SET deleted_at = NOW()
        WHERE contact_id = NEW.id AND deleted_at IS NULL;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_propagate_contact_soft_delete ON contacts;
CREATE TRIGGER trg_propagate_contact_soft_delete
    AFTER UPDATE OF deleted_at ON contacts
    FOR EACH ROW EXECUTE FUNCTION propagate_contact_soft_delete();

-- ============================================================
-- 5. ALTER FK per catena contatti
--    conversations/messages/consent_log → CASCADE
--    bookings/reviews → SET NULL (la PII e' gia' stata anonimizzata
--    dal trigger BEFORE DELETE al passo 3)
-- ============================================================
ALTER TABLE conversations
    DROP CONSTRAINT IF EXISTS conversations_contact_id_fkey,
    ADD FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE messages
    DROP CONSTRAINT IF EXISTS messages_conversation_id_fkey,
    ADD FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE;
ALTER TABLE contact_consent_log
    DROP CONSTRAINT IF EXISTS contact_consent_log_contact_id_fkey,
    ADD FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE;
ALTER TABLE bookings
    DROP CONSTRAINT IF EXISTS bookings_contact_id_fkey,
    ADD FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
ALTER TABLE reviews
    DROP CONSTRAINT IF EXISTS reviews_contact_id_fkey,
    ADD FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL;
