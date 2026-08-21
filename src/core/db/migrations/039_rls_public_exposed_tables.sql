-- 039_rls_public_exposed_tables.sql
-- Defense-in-depth: ensure every public, organization-scoped table created
-- after the first RLS pass has RLS enabled with org-member policies.

DO $$
DECLARE
    table_name text;
    policy_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'google_calendar_credentials',
        'oauth_nonces',
        'google_business_credentials',
        'instagram_accounts',
        'faq_cache',
        'message_feedback',
        'weekly_report_log'
    ]
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', table_name);
        policy_name := table_name || '_org_member';
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = table_name
              AND policyname = policy_name
        ) THEN
            EXECUTE format(
                'CREATE POLICY %I ON %I FOR ALL
                 USING (
                    organization_id IN (
                        SELECT om.organization_id
                        FROM organization_memberships om
                        JOIN user_profiles up ON up.id = om.user_id
                        WHERE up.auth_user_id = auth.uid()
                    )
                 )
                 WITH CHECK (
                    organization_id IN (
                        SELECT om.organization_id
                        FROM organization_memberships om
                        JOIN user_profiles up ON up.id = om.user_id
                        WHERE up.auth_user_id = auth.uid()
                    )
                 )',
                policy_name,
                table_name
            );
        END IF;
    END LOOP;
END $$;
