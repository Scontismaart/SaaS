-- 048_airtable_connections.sql
-- Connessioni e credenziali per integrazione Airtable (tenant-scoped).
-- Separata dal dominio di booking: supporta pattern 1 credential -> N basi/tabelle.
-- Cifratura simmetrica Fernet at-rest (envelope JSON) conforme a Invariante 10.
-- RLS con policy WITH CHECK conforme a Invariante 1 e 2.
-- ON DELETE CASCADE: segue la cancellazione GDPR dell'organizzazione.

CREATE TABLE IF NOT EXISTS airtable_connections (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    token_type            VARCHAR(20) NOT NULL DEFAULT 'pat' CHECK (token_type IN ('pat', 'oauth')),
    credentials_encrypted TEXT NOT NULL,
    base_id               VARCHAR(100) NOT NULL,
    base_name             VARCHAR(255) NOT NULL DEFAULT '',
    scopes                TEXT[] NOT NULL DEFAULT '{}',
    metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_airtable_connections_org_base UNIQUE (organization_id, base_id)
);

CREATE INDEX IF NOT EXISTS idx_airtable_connections_org_active 
    ON airtable_connections(organization_id, is_active);

ALTER TABLE airtable_connections ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'airtable_connections_org_member') THEN
        CREATE POLICY airtable_connections_org_member ON airtable_connections
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
