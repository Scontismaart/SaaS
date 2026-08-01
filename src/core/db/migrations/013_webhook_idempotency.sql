CREATE TABLE IF NOT EXISTS webhook_idempotency (
    wam_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    status_value TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (wam_id, resource_type, status_value)
);

CREATE INDEX IF NOT EXISTS idx_webhook_idempotency_created_at
    ON webhook_idempotency (created_at);
