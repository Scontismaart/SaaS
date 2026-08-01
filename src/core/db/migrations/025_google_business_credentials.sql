-- 025_google_business_credentials.sql
-- Token OAuth Google Business Profile per-organization, criptati con Fernet.
-- Stesso pattern di 019_google_calendar_credentials: RLS attiva fin dalla
-- creazione, ON DELETE CASCADE per il GDPR erasure dell'org.

CREATE TABLE IF NOT EXISTS google_business_credentials (
    organization_id  UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    access_token     TEXT NOT NULL,        -- Fernet-encrypted
    refresh_token    TEXT NOT NULL,        -- Fernet-encrypted
    token_expiry     TIMESTAMPTZ NOT NULL,
    account_name     TEXT NOT NULL DEFAULT '',
    location_name    TEXT NOT NULL DEFAULT '',
    last_sync_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE google_business_credentials ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'google_business_credentials_org_member') THEN
        CREATE POLICY google_business_credentials_org_member ON google_business_credentials
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
