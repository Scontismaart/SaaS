-- Migration: Add messaging state tracking and idempotency 
ALTER TABLE messages
  ADD COLUMN billed_at TIMESTAMPTZ,
  ADD COLUMN ai_reply_cache TEXT,
  ADD COLUMN ai_reply_generated_at TIMESTAMPTZ,
  ADD COLUMN sent_at TIMESTAMPTZ,
  ADD COLUMN meta_message_id VARCHAR(255),
  ADD COLUMN quota_exceeded_at TIMESTAMPTZ,
  ADD COLUMN processing_at TIMESTAMPTZ;

-- Note: Ensure that bookings table has source_message_id if not already present
-- ALTER TABLE bookings ADD COLUMN source_message_id VARCHAR(255);
