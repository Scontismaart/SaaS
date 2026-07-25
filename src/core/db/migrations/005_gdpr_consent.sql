-- 005_gdpr_consent.sql
-- Consent status on contacts for fast lookup + security audit log table

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS consent_status TEXT CHECK (consent_status IN ('granted', 'withdrawn', 'unknown')) DEFAULT 'unknown';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS consent_updated_at TIMESTAMPTZ;
