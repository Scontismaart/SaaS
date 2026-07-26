ALTER TABLE bookings ADD COLUMN IF NOT EXISTS tipo_evento            TEXT NOT NULL DEFAULT '';
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS richiede_deposito      BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_link           TEXT NOT NULL DEFAULT '';
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_link_created_at TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_status         TEXT NOT NULL DEFAULT 'none'
    CHECK (payment_status IN ('none','pending','paid','refunded','expired'));
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_sent_at       TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_status        TEXT NOT NULL DEFAULT 'none'
    CHECK (reminder_status IN ('none','sent','confirmed','rejected','cancelled','flagged'));
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_responded_at  TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS completata_at          TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS no_show_at             TIMESTAMPTZ;

ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_stato_check;
ALTER TABLE bookings ADD CONSTRAINT bookings_stato_check
    CHECK (stato IN ('in_attesa','confermata','rifiutata','cancellata','no_show','completata','da_verificare'));

ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}';
