-- 032_search_path_hardening_new_triggers.sql
-- Stesso intervento della 011 per le funzioni (ri)create da 023 e 028:
-- CREATE OR REPLACE di log_review_event e la nuova log_onboarding_event
-- non fissano il search_path, e il Supabase linter le segnala come
-- "Function Search Path Mutable" (rischio di schema-shadowing).

ALTER FUNCTION log_review_event() SET search_path = public, pg_temp;
ALTER FUNCTION log_onboarding_event() SET search_path = public, pg_temp;
