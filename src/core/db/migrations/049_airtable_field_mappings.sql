-- 049_airtable_field_mappings.sql
-- Configurazione dei mapping tra modello interno del SaaS e colonne Airtable (tenant-scoped).
-- Conforme a:
-- - Invariante 1: Tenant Isolation con RLS attiva e policy WITH CHECK basata su organization_memberships.
-- - Invariante 2: organization_id esplicito con vincolo di foreign key e ON DELETE CASCADE.
-- - Invariante 10: Nessun segreto memorizzato in questa tabella.

CREATE TABLE IF NOT EXISTS airtable_field_mappings (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    base_id               VARCHAR(100) NOT NULL,
    table_id_or_name      VARCHAR(255) NOT NULL,
    entity_type           VARCHAR(50) NOT NULL DEFAULT 'customer',
    field_mappings        JSONB NOT NULL DEFAULT '{}'::jsonb,
    required_fields       TEXT[] NOT NULL DEFAULT '{}',
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_airtable_mappings_org_base_table_entity 
        UNIQUE (organization_id, base_id, table_id_or_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_airtable_mappings_org_base
    ON airtable_field_mappings(organization_id, base_id, entity_type);

ALTER TABLE airtable_field_mappings ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'airtable_field_mappings_org_member') THEN
        CREATE POLICY airtable_field_mappings_org_member ON airtable_field_mappings
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
