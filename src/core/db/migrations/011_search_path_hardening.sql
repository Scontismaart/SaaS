-- 011_search_path_hardening.sql
-- Supabase linter: "Function Search Path Mutable" su funzioni nostre, e
-- "Public/Signed-in users can execute SECURITY DEFINER" su una funzione
-- gestita da Supabase stesso (non nostra, non la tocchiamo se non per i
-- permessi).
--
-- Perche' e' un problema reale: una funzione senza search_path fissato
-- risolve i nomi non qualificati (es. una tabella scritta senza schema)
-- cercandoli negli schema del search_path corrente della sessione che la
-- chiama. Se qualcuno crea un oggetto con lo stesso nome in uno schema
-- che precede "public" nel search_path di quella sessione, la funzione
-- puo' finire per eseguire codice/query su un oggetto diverso da quello
-- previsto (schema-shadowing). Fissare search_path = public, pg_temp
-- elimina l'ambiguita': la funzione risolve sempre negli stessi schema,
-- a prescindere da chi la chiama.

ALTER FUNCTION check_chunk_org_consistency() SET search_path = public, pg_temp;
ALTER FUNCTION log_message_event() SET search_path = public, pg_temp;
ALTER FUNCTION log_review_event() SET search_path = public, pg_temp;
ALTER FUNCTION sync_auth_user_profile() SET search_path = public, pg_temp;

-- rls_auto_enable() e' creata da Supabase stesso (event trigger interno
-- del dashboard/table editor, non e' nel nostro codice/migrazioni), quindi
-- non la modifichiamo. Il linter segnala pero' che e' chiamabile via RPC
-- diretto da anon/authenticated: revochiamo l'EXECUTE pubblico, gli event
-- trigger continuano a funzionare (eseguono con i privilegi della
-- funzione indipendentemente dai GRANT dell'utente che ha causato
-- l'evento, stessa logica gia' applicata a sync_auth_user_profile).
DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE p.proname = 'rls_auto_enable' AND n.nspname = 'public'
    ) THEN
        REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM PUBLIC;
        REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon;
        REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM authenticated;
    END IF;
END $$;
