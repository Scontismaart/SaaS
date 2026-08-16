-- 030_instagram_channel.sql
-- Punto 10 roadmap: canale Instagram DM accanto a WhatsApp.
-- - conversations.canale: canale di origine della conversazione (dispatch
--   inbound_processor e reply inbox). Default 'whatsapp' per compatibilita'
--   con le righe esistenti.
-- - instagram_accounts: credenziali per-organization (IG professional account
--   id + page token), token Fernet-encrypted. Stesso pattern di
--   026_google_business_credentials: RLS attiva fin dalla creazione,
--   ON DELETE CASCADE per il GDPR erasure dell'org.

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS canale TEXT NOT NULL DEFAULT 'whatsapp'
    CHECK (canale IN ('whatsapp', 'instagram'));

CREATE TABLE IF NOT EXISTS instagram_accounts (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    ig_user_id      TEXT NOT NULL UNIQUE,   -- IG professional account id (recipient.id nei webhook)
    access_token    TEXT NOT NULL,          -- Fernet-encrypted
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (organization_id)
);
CREATE INDEX IF NOT EXISTS idx_instagram_accounts_org ON instagram_accounts(organization_id);

ALTER TABLE instagram_accounts ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'instagram_accounts_org_member') THEN
        CREATE POLICY instagram_accounts_org_member ON instagram_accounts
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
