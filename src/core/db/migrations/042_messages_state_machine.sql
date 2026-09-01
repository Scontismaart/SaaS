-- Migration: Add messaging state tracking and idempotency
-- Idempotente: schema.sql crea gia' alcune di queste colonne (es. sent_at);
-- su un DB fresco "schema.sql + tutte le migrazioni" deve applicare pulito.
ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS billed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ai_reply_cache JSONB,
  ADD COLUMN IF NOT EXISTS ai_reply_generated_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS meta_message_id VARCHAR(255),
  ADD COLUMN IF NOT EXISTS quota_exceeded_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS processing_at TIMESTAMPTZ;

-- Note: Ensure that bookings table has source_message_id if not already present
-- ALTER TABLE bookings ADD COLUMN source_message_id VARCHAR(255);
