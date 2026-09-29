-- Team invitations are pending grants, never memberships. Apply only after the
-- release containing the new acceptance route is ready; this file is not run
-- by the Phase 1 implementation work.
CREATE TABLE IF NOT EXISTS team_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL CHECK (email = lower(btrim(email))),
    ruolo TEXT NOT NULL CHECK (ruolo IN ('manager', 'staff')),
    token_hash CHAR(64) NOT NULL UNIQUE,
    invited_by UUID NOT NULL REFERENCES user_profiles(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > created_at),
    CHECK (consumed_at IS NULL OR revoked_at IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_fk_team_invitations_invited_by
    ON team_invitations (invited_by);
CREATE INDEX IF NOT EXISTS idx_team_invitations_org_pending
    ON team_invitations (organization_id, created_at DESC)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_team_invitations_one_pending_email
    ON team_invitations (organization_id, email)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;
ALTER TABLE team_invitations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS team_invitations_deny_clients ON team_invitations;
CREATE POLICY team_invitations_deny_clients ON team_invitations
    TO anon, authenticated USING (false) WITH CHECK (false);
REVOKE ALL ON team_invitations FROM PUBLIC, anon, authenticated;

-- A signed-in Supabase client must never grant itself or another user a role.
DROP POLICY IF EXISTS memberships_insert_by_admin ON organization_memberships;
REVOKE INSERT, UPDATE, DELETE ON organization_memberships FROM PUBLIC, anon, authenticated;

-- Earlier direct-add flows may have left rows with no acceptance timestamp.
-- Existing auth lookups can still treat those rows as memberships, so stop the
-- migration for an explicit, reviewed cleanup instead of silently preserving
-- a pending grant as active access.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM organization_memberships WHERE joined_at IS NULL
    ) THEN
        RAISE EXCEPTION 'organization_memberships rows with joined_at IS NULL require security review before migration 057';
    END IF;
END $$;

-- STOP event replay must not create duplicate consent records. Abort with an
-- explicit diagnostic if historical duplicates need reconciliation first.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM contact_consent_log
        WHERE triggering_message_id IS NOT NULL
        GROUP BY triggering_message_id HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'duplicate contact_consent_log.triggering_message_id values require review before migration 057';
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS idx_contact_consent_message_once
    ON contact_consent_log (triggering_message_id)
    WHERE triggering_message_id IS NOT NULL;
