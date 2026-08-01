-- 022_reviews_ext.sql
-- Estende tabella reviews con colonne per bozza AI, stato, dedup, GDPR.
-- Nessun enum PG: stato validato a livello applicativo (Pydantic).
-- RLS difesa in profondità (stesso pattern di 019_google_calendar_credentials).
-- UNIQUE(organization_id, external_id) multi-tenant per dedup.

ALTER TABLE reviews ADD COLUMN IF NOT EXISTS bozza_risposta              TEXT NOT NULL DEFAULT '';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS sentiment                   TEXT NOT NULL DEFAULT '';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS categoria                   TEXT NOT NULL DEFAULT '';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS richiede_revisione_urgente  BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS stato                       TEXT NOT NULL DEFAULT 'nuova';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS external_id                 TEXT;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS published_at                TIMESTAMPTZ;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS is_anonymized               BOOLEAN NOT NULL DEFAULT FALSE;

-- Unique index per dedup multi-tenant (solo righe con external_id valorizzato)
CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_org_external_id
    ON reviews(organization_id, external_id)
    WHERE external_id IS NOT NULL;

-- RLS: difesa in profondità (backend usa service_role, ma protegge da
-- query dirette Supabase Studio / bug Python che dimenticano filtro org)
ALTER TABLE reviews ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'reviews_org_member') THEN
        CREATE POLICY reviews_org_member ON reviews
            FOR ALL USING (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            )
            WITH CHECK (
                organization_id IN (
                    SELECT om.organization_id FROM organization_memberships om
                    JOIN user_profiles up ON up.id = om.user_id
                    WHERE up.auth_user_id = auth.uid()
                )
            );
    END IF;
END $$;
