-- Billing state, retryable checkout intents and durable governance accounting.
ALTER TABLE organizations DROP CONSTRAINT IF EXISTS organizations_subscription_status_check;
ALTER TABLE organizations ADD CONSTRAINT organizations_subscription_status_check
  CHECK (subscription_status IN ('incomplete','incomplete_expired','trialing','active','past_due','unpaid','canceled','paused'));
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_event_created BIGINT NOT NULL DEFAULT 0;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_event_id TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS ai_accounting_blocked BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS billing_checkout_intents (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  request_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  payload JSONB NOT NULL,
  session_id TEXT,
  session_url TEXT,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (organization_id, request_key)
);
CREATE INDEX IF NOT EXISTS billing_checkout_intents_active ON billing_checkout_intents(organization_id, expires_at);
ALTER TABLE billing_checkout_intents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS billing_checkout_intents_deny_clients ON billing_checkout_intents;
CREATE POLICY billing_checkout_intents_deny_clients ON billing_checkout_intents TO anon, authenticated USING (false) WITH CHECK (false);
REVOKE ALL ON billing_checkout_intents FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS governance_outbox (
  id UUID PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  event_kind TEXT NOT NULL CHECK (event_kind IN ('audit','usage')),
  payload JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE governance_outbox ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS governance_outbox_deny_clients ON governance_outbox;
CREATE POLICY governance_outbox_deny_clients ON governance_outbox TO anon, authenticated USING (false) WITH CHECK (false);
REVOKE ALL ON governance_outbox FROM anon, authenticated;

-- Server-owned expected payment facts; older links without these fail closed.
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS deposit_amount_minor BIGINT;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS deposit_currency TEXT;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS deposit_session_id TEXT;
