-- 021_oauth_nonces.sql
-- Nonce one-time per OAuth2 flow Google Calendar (CSRF protection).
-- Tabella effimera: righe vive al max ~10min (TTL logico), cleanup via
-- job scheduler (scheduler.py). RLS + ON DELETE CASCADE come 019.

CREATE TABLE IF NOT EXISTS oauth_nonces (
    nonce            TEXT PRIMARY KEY,
    organization_id  UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_nonces_created ON oauth_nonces(created_at);

ALTER TABLE oauth_nonces ENABLE ROW LEVEL SECURITY;

-- Policy mirata: solo owner dell'org puo' SCRIVERE nonces (avvia OAuth flow);
-- SELECT/DELETE servono al callback (gestito da service_role, bypassa RLS).
-- Owner-only INSERT e' la guardia effettiva: impedisce a staff/manager di
-- avviare connect OAuth (in linea con i ruoli dei calendar routes).
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'oauth_nonces_owner_insert') THEN
        CREATE POLICY oauth_nonces_owner_insert ON oauth_nonces
            FOR INSERT WITH CHECK (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                      AND om.ruolo = 'owner'
                )
            );
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'oauth_nonces_org_member_select') THEN
        CREATE POLICY oauth_nonces_org_member_select ON oauth_nonces
            FOR SELECT USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;
