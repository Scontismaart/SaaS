CREATE TABLE IF NOT EXISTS outbound_dedup (
    message_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL,
    response_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
