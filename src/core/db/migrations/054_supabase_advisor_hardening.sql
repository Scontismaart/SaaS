-- Supabase advisor remediation after the durable webhook/billing rollout.
-- Keep this migration additive and safe for databases with existing rows.

-- The inbox is service-role only. An explicit deny policy documents that
-- boundary and keeps PostgREST clients fail-closed (service_role bypasses RLS).
DROP POLICY IF EXISTS meta_webhook_inbox_deny_clients ON meta_webhook_inbox;
CREATE POLICY meta_webhook_inbox_deny_clients ON meta_webhook_inbox
    TO anon, authenticated USING (false) WITH CHECK (false);
REVOKE ALL ON meta_webhook_inbox FROM anon, authenticated;

-- Migration 033 replaced this function after the earlier search-path pass.
ALTER FUNCTION public.log_onboarding_event()
    SET search_path = public, pg_temp;

-- Migration 039 added a broad ALL policy after the purpose-built OAuth
-- policies. Because permissive policies are OR-ed, it unintentionally let any
-- organization member insert a nonce. Keep member SELECT and owner INSERT only.
DROP POLICY IF EXISTS oauth_nonces_org_member ON oauth_nonces;

-- Evaluate stable auth helpers once per statement instead of once per row.
-- Policy predicates and authorization semantics remain otherwise unchanged.
DO $$
DECLARE
    policy_row record;
    optimized_qual text;
    optimized_check text;
BEGIN
    FOR policy_row IN
        SELECT schemaname, tablename, policyname, qual, with_check
        FROM pg_policies
        WHERE schemaname = 'public'
          AND (qual LIKE '%auth.%' OR with_check LIKE '%auth.%')
    LOOP
        optimized_qual := policy_row.qual;
        optimized_check := policy_row.with_check;

        IF optimized_qual IS NOT NULL THEN
            IF position('(select auth.uid())' IN lower(optimized_qual)) = 0 THEN
                optimized_qual := replace(optimized_qual, 'auth.uid()', '(select auth.uid())');
            END IF;
            IF position('(select auth.jwt())' IN lower(optimized_qual)) = 0 THEN
                optimized_qual := replace(optimized_qual, 'auth.jwt()', '(select auth.jwt())');
            END IF;
        END IF;

        IF optimized_check IS NOT NULL THEN
            IF position('(select auth.uid())' IN lower(optimized_check)) = 0 THEN
                optimized_check := replace(optimized_check, 'auth.uid()', '(select auth.uid())');
            END IF;
            IF position('(select auth.jwt())' IN lower(optimized_check)) = 0 THEN
                optimized_check := replace(optimized_check, 'auth.jwt()', '(select auth.jwt())');
            END IF;
        END IF;

        IF optimized_qual IS DISTINCT FROM policy_row.qual
           OR optimized_check IS DISTINCT FROM policy_row.with_check THEN
            EXECUTE format(
                'ALTER POLICY %I ON %I.%I%s%s',
                policy_row.policyname,
                policy_row.schemaname,
                policy_row.tablename,
                CASE WHEN optimized_qual IS NULL THEN ''
                     ELSE format(' USING (%s)', optimized_qual) END,
                CASE WHEN optimized_check IS NULL THEN ''
                     ELSE format(' WITH CHECK (%s)', optimized_check) END
            );
        END IF;
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id
    ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_consent_log_triggering_message_id
    ON contact_consent_log(triggering_message_id);
CREATE INDEX IF NOT EXISTS idx_conversations_assigned_to
    ON conversations(assigned_to);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id
    ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_external_booking_sync_internal_booking_id
    ON external_booking_sync(internal_booking_id);
CREATE INDEX IF NOT EXISTS idx_governance_outbox_organization_id
    ON governance_outbox(organization_id);
CREATE INDEX IF NOT EXISTS idx_oauth_nonces_organization_id
    ON oauth_nonces(organization_id);
CREATE INDEX IF NOT EXISTS idx_processed_stripe_events_organization_id
    ON processed_stripe_events(organization_id);

-- Both indexes cover contact_id identically. Keep the original canonical one.
DROP INDEX IF EXISTS idx_fk_consent_log_contact;
