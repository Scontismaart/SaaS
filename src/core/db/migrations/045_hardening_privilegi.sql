-- 045: hardening privilegi su schema public (audit Supabase 2026-09-01).
--
-- Contesto: gli anon/authenticated ereditano dai default Supabase i grant
-- su tutte le tabelle di public, TRUNCATE incluso. TRUNCATE non è coperto
-- da RLS: una policy org-scoped non lo blocca. PostgREST non lo espone,
-- ma il grant è inutile per i client e va revocato (advisor Supabase
-- segnala questo pattern).
--
-- NOTA: il ruolo usato dall'app (postgres) NON è toccato da questa
-- migration, né qualsiasi ruolo bypassrls esistente.

-- 1. Revoca TRUNCATE ai ruoli client su tutte le tabelle dello schema public.
REVOKE TRUNCATE ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

-- 2. I futuri oggetti in public nascono senza TRUNCATE per i client.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE TRUNCATE ON TABLES FROM anon, authenticated;

-- 3. outbound_dedup: RLS attiva ma SENZA policy = invisibile a ogni ruolo
-- non-bypass (comportamento voluto: tabella di dedup scritta solo dal
-- backend con privilegi elevati). Rendiamo l'intento esplicito con una
-- policy deny-all nominata, come già fatto per webhook_idempotency
-- (migration 013): leggibile dagli auditor, non un "dimenticato".
DROP POLICY IF EXISTS outbound_dedup_deny_all ON outbound_dedup;
CREATE POLICY outbound_dedup_deny_all ON outbound_dedup
    FOR ALL
    TO anon, authenticated
    USING (false)
    WITH CHECK (false);
