-- Durable simulator idempotency and atomic message quota reservation.
CREATE TABLE IF NOT EXISTS simulation_requests (
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    auth_user_id UUID NOT NULL,
    request_id UUID NOT NULL,
    payload_hash CHAR(64) NOT NULL,
    claim_token UUID NOT NULL DEFAULT gen_random_uuid(),
    status TEXT NOT NULL DEFAULT 'reserved'
        CHECK (status IN ('reserved', 'completed', 'failed')),
    response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    PRIMARY KEY (organization_id, auth_user_id, request_id),
    CONSTRAINT simulation_requests_state_consistent
    CHECK ((status = 'reserved' AND response IS NULL AND completed_at IS NULL)
        OR (status = 'completed' AND response IS NOT NULL AND completed_at IS NOT NULL)
        OR (status = 'failed' AND response IS NULL AND completed_at IS NOT NULL))
);
ALTER TABLE simulation_requests
    ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE simulation_requests
    ADD COLUMN IF NOT EXISTS claim_token UUID NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE simulation_requests DROP CONSTRAINT IF EXISTS simulation_requests_status_check;
ALTER TABLE simulation_requests DROP CONSTRAINT IF EXISTS simulation_requests_check;
ALTER TABLE simulation_requests DROP CONSTRAINT IF EXISTS simulation_requests_status_allowed;
ALTER TABLE simulation_requests ADD CONSTRAINT simulation_requests_status_allowed
    CHECK (status IN ('reserved', 'completed', 'failed'));
ALTER TABLE simulation_requests DROP CONSTRAINT IF EXISTS simulation_requests_state_consistent;
ALTER TABLE simulation_requests ADD CONSTRAINT simulation_requests_state_consistent
    CHECK ((status = 'reserved' AND response IS NULL AND completed_at IS NULL)
        OR (status = 'completed' AND response IS NOT NULL AND completed_at IS NOT NULL)
        OR (status = 'failed' AND response IS NULL AND completed_at IS NOT NULL));
CREATE INDEX IF NOT EXISTS idx_simulation_requests_created
    ON simulation_requests (organization_id, created_at);

ALTER TABLE simulation_requests ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS simulation_requests_deny_clients ON simulation_requests;
CREATE POLICY simulation_requests_deny_clients
    ON simulation_requests TO anon, authenticated USING (false) WITH CHECK (false);
REVOKE ALL ON simulation_requests FROM PUBLIC, anon, authenticated;
