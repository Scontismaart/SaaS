-- 017_advisor_followup.sql
-- Due warning nuovi dal Supabase Security Advisor, comparsi dopo le
-- migrazioni 013/015 (non coperti dalla 011, scritta prima che queste
-- funzioni/tabelle esistessero).

-- 1. webhook_idempotency ha RLS abilitato (probabilmente da un trigger
--    automatico di Supabase su ogni tabella nuova) ma nessuna policy.
--    Non ha organization_id: e' un registro interno di deduplica webhook,
--    mai interrogato da utenti finali via PostgREST/client autenticato,
--    solo dal backend con service_role (che bypassa RLS comunque). Scrivere
--    policy per-tenant qui non avrebbe senso; disattiviamo RLS esplicitamente
--    cosi' l'intento e' chiaro invece di un "dimenticato a meta'".
ALTER TABLE webhook_idempotency DISABLE ROW LEVEL SECURITY;

-- 2. Stesso fix di search_path della 011, esteso alle 2 funzioni trigger
--    create in 014/015 (GDPR cascade), non coperte allora perche' non
--    esistevano ancora quando la 011 e' stata scritta.
ALTER FUNCTION mask_pii_before_contact_delete() SET search_path = public, pg_temp;
ALTER FUNCTION propagate_contact_soft_delete() SET search_path = public, pg_temp;
