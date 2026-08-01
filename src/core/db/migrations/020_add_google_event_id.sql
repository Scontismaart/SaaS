-- 020_add_google_event_id.sql
-- Aggancio evento Google Calendar al booking. TEXT nullable:
-- NULL = mai creato, stringa = ID evento Calendar esistente.

ALTER TABLE bookings ADD COLUMN IF NOT EXISTS google_event_id TEXT;
