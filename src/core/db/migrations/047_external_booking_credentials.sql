-- 047_external_booking_credentials.sql
-- Credenziali e sync tracking per gestionali di prenotazione esterni (per-organization).
-- Cifratura simmetrica Fernet per envelope JSON di credenziali a riposo (flessibile per API key, login, o token OAuth).
-- RLS con policy WITH CHECK fin dalla creazione (stesso standard di 019/026).
-- ON DELETE CASCADE: segue il GDPR erasure dell'organizzazione.

CREATE TABLE IF NOT EXISTS external_booking_credentials (
    organization_id       UUID PRIMARY KEY REFERENCES organizations(id) ON DELETE CASCADE,
    provider              TEXT NOT NULL,
    credentials_encrypted TEXT NOT NULL,
    config                JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active             BOOLEAN NOT NULL DEFAULT TRUE,
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ext_booking_creds_org_active 
    ON external_booking_credentials(organization_id, is_active);

ALTER TABLE external_booking_credentials ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'external_booking_credentials_org_member') THEN
        CREATE POLICY external_booking_credentials_org_member ON external_booking_credentials
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

CREATE TABLE IF NOT EXISTS external_booking_sync (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    idempotency_key     VARCHAR(255) NOT NULL,
    internal_booking_id UUID REFERENCES bookings(id) ON DELETE SET NULL,
    external_booking_id TEXT,
    provider            TEXT NOT NULL,
    sync_status         VARCHAR(50) NOT NULL DEFAULT 'pending',
    sync_error          TEXT,
    retry_count         INT NOT NULL DEFAULT 0,
    last_attempt_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_ext_booking_sync_org_key UNIQUE (organization_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_ext_booking_sync_org_status 
    ON external_booking_sync(organization_id, sync_status);
CREATE INDEX IF NOT EXISTS idx_ext_booking_sync_internal 
    ON external_booking_sync(organization_id, internal_booking_id);
CREATE INDEX IF NOT EXISTS idx_ext_booking_sync_external 
    ON external_booking_sync(organization_id, external_booking_id);

ALTER TABLE external_booking_sync ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'external_booking_sync_org_member') THEN
        CREATE POLICY external_booking_sync_org_member ON external_booking_sync
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
