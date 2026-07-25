-- 004_gdpr.sql
-- Data retention: soft-delete columns + configurable retention per org

ALTER TABLE messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS message_retention_days INTEGER DEFAULT 90;
