-- Durable acceptance boundary: authenticated Meta events are committed before ACK.
CREATE TABLE IF NOT EXISTS meta_webhook_inbox (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('whatsapp', 'instagram', 'whatsapp_template')),
    event_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    trace_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'dead_letter')),
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    UNIQUE (organization_id, channel, event_key)
);
CREATE INDEX IF NOT EXISTS idx_meta_webhook_inbox_pending
    ON meta_webhook_inbox (next_attempt_at) WHERE status IN ('pending', 'processing');
ALTER TABLE meta_webhook_inbox ENABLE ROW LEVEL SECURITY;
-- Worker/service-role access only; no client policies or raw payload exposure.
REVOKE ALL ON meta_webhook_inbox FROM PUBLIC;
