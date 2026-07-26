-- 008_rls_hardening.sql
-- RLS su tutte le tabelle organization_id-scoped che ne erano prive.
-- Prima di questa migration: solo user_profiles, organization_memberships,
-- audit_log avevano enforcement a livello Postgres. Tutte le altre
-- dipendevano solo dal filtro applicativo (WHERE organization_id = $1 nel
-- codice Python) senza rete di sicurezza dal DB.
--
-- NOTA: il backend usa la service_role key per tutte le operazioni via
-- CoreRepository/WhatsAppRepository, che bypassa RLS by design in Supabase.
-- Queste policy sono difesa in profondita': proteggono da query dirette
-- (Supabase Studio, client futuro con anon/authenticated key, bug che
-- dimentica il filtro org nel codice) senza cambiare il comportamento del
-- backend attuale.

-- Helper concettuale riusato in ogni policy (non e' una vera funzione SQL,
-- solo per leggibilita' del commento): un utente vede/scrive solo righe
-- della/e organizzazione/i di cui e' membro, tramite
-- organization_memberships + user_profiles.auth_user_id = auth.uid().

-- ============================================================
-- organizations (self: solo le organizzazioni di cui sei membro)
-- ============================================================
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'organizations_member_select') THEN
        CREATE POLICY organizations_member_select ON organizations
            FOR SELECT USING (
                id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- whatsapp_accounts
-- ============================================================
ALTER TABLE whatsapp_accounts ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'whatsapp_accounts_org_member') THEN
        CREATE POLICY whatsapp_accounts_org_member ON whatsapp_accounts
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- contacts
-- ============================================================
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'contacts_org_member') THEN
        CREATE POLICY contacts_org_member ON contacts
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- conversations
-- ============================================================
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'conversations_org_member') THEN
        CREATE POLICY conversations_org_member ON conversations
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- messages
-- ============================================================
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'messages_org_member') THEN
        CREATE POLICY messages_org_member ON messages
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- message_delivery_attempts (indiretta: nessuna organization_id propria,
-- eredita l'isolamento dal messaggio genitore)
-- ============================================================
ALTER TABLE message_delivery_attempts ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'delivery_attempts_via_message_org') THEN
        CREATE POLICY delivery_attempts_via_message_org ON message_delivery_attempts
            FOR ALL USING (
                message_id IN (
                    SELECT m.id FROM messages m
                    WHERE m.organization_id IN (
                        SELECT om.organization_id FROM organization_memberships om
                        JOIN user_profiles up ON up.id = om.user_id
                        WHERE up.auth_user_id = auth.uid()
                    )
                )
            );
    END IF;
END $$;

-- ============================================================
-- contact_consent_log (indiretta: eredita dal contatto genitore)
-- ============================================================
ALTER TABLE contact_consent_log ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'consent_log_via_contact_org') THEN
        CREATE POLICY consent_log_via_contact_org ON contact_consent_log
            FOR ALL USING (
                contact_id IN (
                    SELECT c.id FROM contacts c
                    WHERE c.organization_id IN (
                        SELECT om.organization_id FROM organization_memberships om
                        JOIN user_profiles up ON up.id = om.user_id
                        WHERE up.auth_user_id = auth.uid()
                    )
                )
            );
    END IF;
END $$;

-- ============================================================
-- whatsapp_templates
-- ============================================================
ALTER TABLE whatsapp_templates ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'whatsapp_templates_org_member') THEN
        CREATE POLICY whatsapp_templates_org_member ON whatsapp_templates
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- bookings
-- ============================================================
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'bookings_org_member') THEN
        CREATE POLICY bookings_org_member ON bookings
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- booking_settings
-- ============================================================
ALTER TABLE booking_settings ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'booking_settings_org_member') THEN
        CREATE POLICY booking_settings_org_member ON booking_settings
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- reviews
-- ============================================================
ALTER TABLE reviews ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'reviews_org_member') THEN
        CREATE POLICY reviews_org_member ON reviews
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- documents
-- ============================================================
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'documents_org_member') THEN
        CREATE POLICY documents_org_member ON documents
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- document_chunks
-- ============================================================
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'document_chunks_org_member') THEN
        CREATE POLICY document_chunks_org_member ON document_chunks
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- email_configs
-- ============================================================
ALTER TABLE email_configs ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'email_configs_org_member') THEN
        CREATE POLICY email_configs_org_member ON email_configs
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- usage_events
-- ============================================================
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'usage_events_org_member') THEN
        CREATE POLICY usage_events_org_member ON usage_events
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- event_log
-- ============================================================
ALTER TABLE event_log ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'event_log_org_member') THEN
        CREATE POLICY event_log_org_member ON event_log
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;

-- ============================================================
-- processed_stripe_events (dedup webhook Stripe: organization_id nullable
-- per gli eventi non ancora associati a un'org, es. errori di lookup)
-- ============================================================
ALTER TABLE processed_stripe_events ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'processed_stripe_events_org_member') THEN
        CREATE POLICY processed_stripe_events_org_member ON processed_stripe_events
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;
