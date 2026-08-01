-- 018_advisor_followup_2.sql

-- 1. webhook_idempotency: la 017 aveva disattivato RLS, ma Supabase segnala
--    "RLS Disabled in Public" per qualsiasi tabella nello schema public
--    esposta via PostgREST senza RLS (chiunque abbia anche solo la anon key
--    potrebbe altrimenti tentare query dirette via REST). La combinazione
--    che soddisfa il linter ED e' davvero sicura: RLS acceso + policy
--    esplicita che nega tutto a anon/authenticated. service_role bypassa
--    comunque RLS, quindi il backend continua a funzionare invariato.
ALTER TABLE webhook_idempotency ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'webhook_idempotency' AND policyname = 'webhook_idempotency_deny_all'
    ) THEN
        CREATE POLICY webhook_idempotency_deny_all ON webhook_idempotency
            FOR ALL USING (false) WITH CHECK (false);
    END IF;
END $$;

-- 2. pgvector fuori da public, verso uno schema dedicato. Segue l'approccio
--    ufficiale Supabase per questo esatto avviso: le colonne "vector" gia'
--    create restano valide (Postgres le traccia per OID, non per nome
--    schema-qualificato), e aggiungendo "extensions" al search_path del
--    database, operatori (<->, <=>, <#>) e il tipo "vector" continuano a
--    risolvere senza qualificazione anche nel codice/migrazioni futuri.
CREATE SCHEMA IF NOT EXISTS extensions;
ALTER EXTENSION vector SET SCHEMA extensions;
ALTER DATABASE postgres SET search_path TO public, extensions;
