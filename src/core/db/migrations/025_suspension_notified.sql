-- 025: traccia quando l'email di sospensione org e' stata inviata.
-- NULL = mai notificata. Impostata a NOW() da subscription.deleted e dal job
-- trial scaduto (UPDATE atomico con WHERE suspension_notified_at IS NULL),
-- riportata a NULL alla riattivazione (subscription.updated/checkout).
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS suspension_notified_at TIMESTAMPTZ;
