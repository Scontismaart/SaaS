-- 015_org_fk_strategy.sql
-- Sostituisce l'approccio della vecchia 014 (mai applicata in produzione):
-- quella metteva CASCADE su TUTTE le FK verso organizations(id) senza
-- distinguere dati-cliente da record di audit/billing. Qui separiamo:
--
-- CASCADE  -> dati cliente, giusto sparire con l'org (GDPR erasure)
-- SET NULL -> storico billing/audit, deve sopravvivere alla cancellazione
--             dell'org (dispute Stripe, obblighi fiscali, indagini)

-- ============================================================
-- 1. INDICI (B-tree) su FK contatti coinvolte nella cascata
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_fk_conversations_contact ON conversations(contact_id);
CREATE INDEX IF NOT EXISTS idx_fk_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_fk_bookings_contact ON bookings(contact_id);
CREATE INDEX IF NOT EXISTS idx_fk_reviews_contact ON reviews(contact_id);
CREATE INDEX IF NOT EXISTS idx_fk_consent_log_contact ON contact_consent_log(contact_id);

-- ============================================================
-- 2a. CASCADE da organizations -> dati cliente
-- ============================================================
ALTER TABLE whatsapp_accounts
    DROP CONSTRAINT IF EXISTS whatsapp_accounts_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE contacts
    DROP CONSTRAINT IF EXISTS contacts_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE conversations
    DROP CONSTRAINT IF EXISTS conversations_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE messages
    DROP CONSTRAINT IF EXISTS messages_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE whatsapp_templates
    DROP CONSTRAINT IF EXISTS whatsapp_templates_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE bookings
    DROP CONSTRAINT IF EXISTS bookings_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE booking_settings
    DROP CONSTRAINT IF EXISTS booking_settings_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE reviews
    DROP CONSTRAINT IF EXISTS reviews_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE documents
    DROP CONSTRAINT IF EXISTS documents_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE document_chunks
    DROP CONSTRAINT IF EXISTS document_chunks_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE email_configs
    DROP CONSTRAINT IF EXISTS email_configs_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE;

-- ============================================================
-- 2b. SET NULL da organizations -> storico billing/audit
--     Questi record devono sopravvivere alla cancellazione dell'org
--     (dispute Stripe, obblighi fiscali, indagini post-mortem).
--     Va tolto NOT NULL da organization_id per permettere SET NULL.
-- ============================================================
ALTER TABLE usage_events ALTER COLUMN organization_id DROP NOT NULL;
ALTER TABLE usage_events
    DROP CONSTRAINT IF EXISTS usage_events_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL;

ALTER TABLE event_log ALTER COLUMN organization_id DROP NOT NULL;
ALTER TABLE event_log
    DROP CONSTRAINT IF EXISTS event_log_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL;

ALTER TABLE audit_log ALTER COLUMN organization_id DROP NOT NULL;
ALTER TABLE audit_log
    DROP CONSTRAINT IF EXISTS audit_log_organization_id_fkey,
    ADD FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE SET NULL;

-- processed_stripe_events NON viene toccata qui: organization_id fa parte
-- della PRIMARY KEY (event_id, organization_id), quindi non puo' essere
-- NULL per definizione (i PK non ammettono NULL). Serve una migrazione
-- separata che ridisegna la chiave primaria (es. PK solo su event_id,
-- organization_id nullable con indice UNIQUE separato) prima di poter
-- fare SET NULL li'. Per ora resta ON DELETE CASCADE come gia' era da
-- prima di qualsiasi modifica di oggi (migrazione 003) -- stesso rischio
-- che avevo segnalato, ma e' un fix piu' invasivo, va fatto a parte e con
-- calma, non incastrato qui.

-- ============================================================
-- 3. TRIGGER BEFORE DELETE su contacts — anonimizzazione PII
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
-- 5. FK per catena contatti
--    conversations/messages/consent_log -> CASCADE
--    bookings/reviews -> SET NULL (PII gia' anonimizzata dal trigger sopra)
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
