CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL,
    business_profile JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS whatsapp_accounts (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    phone_number_id TEXT NOT NULL UNIQUE,
    waba_id         TEXT NOT NULL,
    access_token    TEXT NOT NULL,
    verify_token    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_whatsapp_accounts_org ON whatsapp_accounts(organization_id);

CREATE TABLE IF NOT EXISTS contacts (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    phone_number    TEXT NOT NULL,
    marketing_opt_out BOOLEAN NOT NULL DEFAULT FALSE,
    opted_out_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, phone_number)
);
CREATE INDEX IF NOT EXISTS idx_contacts_org ON contacts(organization_id);

CREATE TABLE IF NOT EXISTS conversations (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    contact_id      UUID NOT NULL REFERENCES contacts(id),
    status          TEXT NOT NULL DEFAULT 'active',
    last_message_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, contact_id)
);
CREATE INDEX IF NOT EXISTS idx_conversations_org ON conversations(organization_id);

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    wam_id          TEXT UNIQUE,
    direction       TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    message_type    TEXT NOT NULL,
    content         JSONB NOT NULL,
    content_text    TEXT,
    status          TEXT NOT NULL,
    handling_type   TEXT,
    error_code      TEXT,
    error_title     TEXT,
    error_details   JSONB,
    sent_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    read_at         TIMESTAMPTZ,
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_status_by_direction CHECK (
        (direction = 'inbound'  AND status IN ('received_pending_ai','processing','handled'))
        OR
        (direction = 'outbound' AND status IN ('queued','processing','sent','delivered','read','failed','sending_ambiguous'))
    )
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_wam_id ON messages(wam_id) WHERE wam_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_org_created ON messages(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_org_status ON messages(organization_id, status) WHERE status != 'read';
CREATE INDEX IF NOT EXISTS idx_messages_org_inbound_pending ON messages(organization_id)
    WHERE direction='inbound' AND status='received_pending_ai';
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS message_delivery_attempts (
    id              UUID PRIMARY KEY,
    message_id      UUID NOT NULL REFERENCES messages(id),
    attempt_number  INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    next_retry_at   TIMESTAMPTZ,
    error_details   JSONB,
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_message ON message_delivery_attempts(message_id);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_retry
    ON message_delivery_attempts(status, next_retry_at)
    WHERE status = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_attempt_per_message
    ON message_delivery_attempts(message_id)
    WHERE status IN ('pending', 'processing');

CREATE TABLE IF NOT EXISTS contact_consent_log (
    id              UUID PRIMARY KEY,
    contact_id      UUID NOT NULL REFERENCES contacts(id),
    event_type      TEXT NOT NULL CHECK (event_type IN ('opt_out', 'opt_in')),
    method          TEXT NOT NULL CHECK (method IN ('keyword_match', 'button_reply', 'manual_staff')),
    triggering_message_id UUID REFERENCES messages(id),
    matched_text    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_consent_log_contact ON contact_consent_log(contact_id);

CREATE TABLE IF NOT EXISTS whatsapp_templates (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name            TEXT NOT NULL,
    language        TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')),
    status          TEXT NOT NULL DEFAULT 'PENDING',
    components      JSONB NOT NULL,
    rejected_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, name, language)
);
CREATE INDEX IF NOT EXISTS idx_templates_org ON whatsapp_templates(organization_id);
