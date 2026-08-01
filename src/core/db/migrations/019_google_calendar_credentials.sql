-- 019_google_calendar_credentials.sql
-- Token OAuth Google Calendar per-organization, criptati con Fernet.
-- RLS + policy WITH CHECK fin dalla creazione (stesso standard di 008/009).
-- ON DELETE CASCADE: token = dato cliente, segue il GDPR erasure dell'org
-- (stessa decisione di 015_org_fk_strategy.sql per dati cliente).

CREATE TABLE IF NOT EXISTS google_calendar_credentials (
    organization_id  UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    access_token     TEXT NOT NULL,        -- Fernet-encrypted
    refresh_token    TEXT NOT NULL,        -- Fernet-encrypted
    token_expiry     TIMESTAMPTZ NOT NULL,
    calendar_id      TEXT NOT NULL DEFAULT 'primary',
    sync_enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: difesa in profondita'. Il backend gira con service_role (bypass RLS),
-- ma queste policy proteggono da query dirette Supabase Studio / client
-- futuro con anon|authenticated key, o bug nel codice Python che dimentica
-- il filtro organization_id.
ALTER TABLE google_calendar_credentials ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'google_calendar_credentials_org_member') THEN
        CREATE POLICY google_calendar_credentials_org_member ON google_calendar_credentials
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
