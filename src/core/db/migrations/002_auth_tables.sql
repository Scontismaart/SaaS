-- 002_auth_tables.sql

CREATE TABLE IF NOT EXISTS user_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id    UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    nome            TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organization_memberships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    ruolo           TEXT NOT NULL CHECK (ruolo IN ('owner', 'manager', 'staff')),
    invited_at      TIMESTAMPTZ DEFAULT NOW(),
    joined_at       TIMESTAMPTZ,
    UNIQUE(organization_id, user_id)
);

CREATE OR REPLACE FUNCTION sync_auth_user_profile()
RETURNS trigger AS $$
BEGIN
    INSERT INTO user_profiles (id, auth_user_id, email)
    VALUES (gen_random_uuid(), NEW.id, NEW.email)
    ON CONFLICT (auth_user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_sync_auth_user ON auth.users;
CREATE TRIGGER trg_sync_auth_user
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION sync_auth_user_profile();

CREATE INDEX IF NOT EXISTS idx_memberships_user ON organization_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_org ON organization_memberships(organization_id);

-- RLS: user_profiles
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'user_profiles_self') THEN
        CREATE POLICY user_profiles_self ON user_profiles
            FOR ALL USING (auth_user_id = auth.uid());
    END IF;
END $$;

-- RLS: organization_memberships
ALTER TABLE organization_memberships ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'memberships_self') THEN
        CREATE POLICY memberships_self ON organization_memberships
            FOR SELECT USING (
                user_id IN (SELECT id FROM user_profiles WHERE auth_user_id = auth.uid())
            );
    END IF;
END $$;

-- ============================================================
-- AUDIT_LOG (tabella separata da event_log)
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    user_id         UUID REFERENCES user_profiles(id),
    auth_user_id    TEXT,
    action          TEXT NOT NULL,
    target_table    TEXT,
    target_id       UUID,
    details         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_org ON audit_log(organization_id, created_at DESC);
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

-- RLS: audit_log
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'audit_log_org_member') THEN
        CREATE POLICY audit_log_org_member ON audit_log
            FOR SELECT USING (
                organization_id IN (
                    SELECT organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'audit_log_service_insert') THEN
        -- WITH CHECK (true) sarebbe equivalente a nessuna RLS in scrittura:
        -- qualunque ruolo autenticato potrebbe forgiare audit_log per org altrui.
        -- Permettiamo l'insert solo al service_role (backend) o a un utente
        -- che sta scrivendo per un'organizzazione di cui e' effettivamente membro.
        CREATE POLICY audit_log_service_insert ON audit_log
            FOR INSERT WITH CHECK (
                auth.jwt() ->> 'role' = 'service_role'
                OR organization_id IN (
                    SELECT organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;
