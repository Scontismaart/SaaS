-- 050_airtable_webhooks.sql
-- Registrazione webhook e log eventi ricevuti da Airtable (tenant-scoped).
-- Conforme a:
-- - Invariante 1: Tenant Isolation con RLS attiva e policy WITH CHECK.
-- - Invariante 2: organization_id esplicito con vincolo di foreign key e ON DELETE CASCADE.
-- - Invariante 4: Idempotenza su ogni evento esterno ricevuto (uq_airtable_webhook_events_dedup).
-- - Invariante 10: Secret MAC cifrato a riposo con Fernet.

CREATE TABLE IF NOT EXISTS airtable_webhooks (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    base_id               VARCHAR(100) NOT NULL,
    webhook_id            VARCHAR(100) NOT NULL,
    mac_secret_encrypted  TEXT NOT NULL,
    cursor                BIGINT NOT NULL DEFAULT 1,
    notification_url      TEXT NOT NULL DEFAULT '',
    specification         JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_airtable_webhooks_webhook_id UNIQUE (webhook_id),
    CONSTRAINT uq_airtable_webhooks_org_base UNIQUE (organization_id, base_id)
);

CREATE INDEX IF NOT EXISTS idx_airtable_webhooks_org_base
    ON airtable_webhooks(organization_id, base_id);

ALTER TABLE airtable_webhooks ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'airtable_webhooks_org_member') THEN
        CREATE POLICY airtable_webhooks_org_member ON airtable_webhooks
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


CREATE TABLE IF NOT EXISTS airtable_webhook_events (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    base_id               VARCHAR(100) NOT NULL,
    webhook_id            VARCHAR(100) NOT NULL,
    external_event_id     VARCHAR(255) NOT NULL,
    event_type            VARCHAR(100) NOT NULL DEFAULT 'table_data_changed',
    payload               JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                VARCHAR(30) NOT NULL DEFAULT 'pending' 
                          CHECK (status IN ('pending', 'processing', 'completed', 'failed', 'ignored')),
    error_message         TEXT,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    processed_at          TIMESTAMPTZ,
    CONSTRAINT uq_airtable_webhook_events_dedup UNIQUE (organization_id, webhook_id, external_event_id)
);

CREATE INDEX IF NOT EXISTS idx_airtable_webhook_events_org_status
    ON airtable_webhook_events(organization_id, status);

ALTER TABLE airtable_webhook_events ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'airtable_webhook_events_org_member') THEN
        CREATE POLICY airtable_webhook_events_org_member ON airtable_webhook_events
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
