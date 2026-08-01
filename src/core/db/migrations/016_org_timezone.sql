-- 016_org_timezone.sql
-- Aggiunge timezone per-tenant per calcoli reminder localizzati.
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'Europe/Rome';
