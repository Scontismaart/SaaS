-- Migration 006: HITL Shared Inbox support
-- Conversation ticket state machine, optimistic locking, idempotent replies

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS ticket_status TEXT NOT NULL DEFAULT 'AI_ACTIVE'
        CHECK (ticket_status IN ('AI_ACTIVE', 'PENDING_STAFF', 'CLAIMED', 'RESOLVED'));

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS assigned_to UUID REFERENCES user_profiles(id);

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS pending_staff_at TIMESTAMPTZ;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_conversations_ticket_status
    ON conversations(organization_id, ticket_status)
    WHERE deleted_at IS NULL;

ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_idempotency_org_key
    ON messages(organization_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
