ALTER TABLE organizations ADD COLUMN IF NOT EXISTS stripe_customer_id TEXT UNIQUE;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS subscription_id TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS subscription_status TEXT NOT NULL DEFAULT 'incomplete';
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS plan TEXT;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS messages_used_this_period INT NOT NULL DEFAULT 0;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS messages_limit INT;  -- NULL = illimitato
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS users_limit INT;          -- NULL = illimitato
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS whatsapp_numbers_limit INT; -- NULL = illimitato
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS current_period_start TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS current_period_end TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_start TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS trial_end TIMESTAMPTZ;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'organizations_subscription_status_check') THEN
        ALTER TABLE organizations ADD CONSTRAINT organizations_subscription_status_check
            CHECK (subscription_status IN ('incomplete','trialing','active','past_due','canceled'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'organizations_plan_check') THEN
        ALTER TABLE organizations ADD CONSTRAINT organizations_plan_check
            CHECK (plan IN ('starter','pro','business'));
    END IF;
END $$;

DROP TABLE IF EXISTS processed_stripe_events;
CREATE TABLE IF NOT EXISTS processed_stripe_events (
    event_id TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (event_id, organization_id)
);

CREATE INDEX IF NOT EXISTS idx_org_stripe_customer ON organizations(stripe_customer_id);
