-- 009_rls_write_check.sql
-- Fix audit 1.1: tutte le policy FOR ALL create in 008_rls_hardening.sql
-- (e user_profiles_self in 002_auth_tables.sql) avevano solo USING, senza
-- WITH CHECK. Senza WITH CHECK, un utente autenticato con accesso diretto
-- (RLS, non tramite backend service_role) puo' fare UPDATE su
-- organization_id di una riga per "spostarla" sotto un'altra org, perche'
-- Postgres valuta WITH CHECK sulla riga NUOVA scritta, non su quella letta.
-- ALTER POLICY su Postgres permette di aggiungere/sostituire USING e
-- WITH CHECK di una policy esistente senza droppare/ricrearla.

ALTER POLICY user_profiles_self ON user_profiles
    WITH CHECK (auth_user_id = auth.uid());

ALTER POLICY whatsapp_accounts_org_member ON whatsapp_accounts
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY contacts_org_member ON contacts
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );
ALTER POLICY conversations_org_member ON conversations
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY messages_org_member ON messages
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY delivery_attempts_via_message_org ON message_delivery_attempts
    WITH CHECK (
        message_id IN (
            SELECT m.id FROM messages m
            WHERE m.organization_id IN (
                SELECT om.organization_id FROM organization_memberships om
                JOIN user_profiles up ON up.id = om.user_id
                WHERE up.auth_user_id = auth.uid()
            )
        )
    );
ALTER POLICY consent_log_via_contact_org ON contact_consent_log
    WITH CHECK (
        contact_id IN (
            SELECT c.id FROM contacts c
            WHERE c.organization_id IN (
                SELECT om.organization_id FROM organization_memberships om
                JOIN user_profiles up ON up.id = om.user_id
                WHERE up.auth_user_id = auth.uid()
            )
        )
    );

ALTER POLICY whatsapp_templates_org_member ON whatsapp_templates
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY bookings_org_member ON bookings
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );
ALTER POLICY booking_settings_org_member ON booking_settings
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY reviews_org_member ON reviews
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY documents_org_member ON documents
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );
ALTER POLICY document_chunks_org_member ON document_chunks
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY email_configs_org_member ON email_configs
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY usage_events_org_member ON usage_events
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );
ALTER POLICY event_log_org_member ON event_log
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

ALTER POLICY processed_stripe_events_org_member ON processed_stripe_events
    WITH CHECK (
        organization_id IN (
            SELECT om.organization_id FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = auth.uid()
        )
    );

-- Fix audit 1.6: organization_memberships aveva solo SELECT (memberships_self
-- in 002_auth_tables.sql). Aggiunge INSERT: un membro esistente con ruolo
-- owner/manager di un'organizzazione puo' invitare nuovi membri per QUELLA
-- organizzazione. Non permette self-invite arbitrario ne' invito su org di
-- cui non si e' gia' owner/manager.
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'memberships_insert_by_admin') THEN
        CREATE POLICY memberships_insert_by_admin ON organization_memberships
            FOR INSERT WITH CHECK (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                    AND om.ruolo IN ('owner', 'manager')
                )
            );
    END IF;
END $$;

-- Fix audit 1.7: sync_auth_user_profile e' SECURITY DEFINER in schema
-- public. E' pensata per essere invocata SOLO dal trigger su auth.users
-- (trg_sync_auth_user): i trigger eseguono con i privilegi della funzione
-- a prescindere dai GRANT dell'utente che ha causato l'evento, quindi
-- revocare EXECUTE a PUBLIC/anon/authenticated non rompe il trigger, ma
-- impedisce a un utente autenticato di chiamarla direttamente via RPC
-- Supabase (supabase.rpc('sync_auth_user_profile')), cosa che oggi e'
-- permessa di default su ogni funzione in schema public.
REVOKE EXECUTE ON FUNCTION sync_auth_user_profile() FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION sync_auth_user_profile() FROM anon;
REVOKE EXECUTE ON FUNCTION sync_auth_user_profile() FROM authenticated;
