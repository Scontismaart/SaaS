ALTER TABLE bookings ADD COLUMN source_message_id VARCHAR(255);
CREATE UNIQUE INDEX idx_bookings_source_message ON bookings (organization_id, source_message_id) WHERE source_message_id IS NOT NULL;
