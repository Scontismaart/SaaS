-- Migration 036: Tabella idempotenza report settimanale
--
-- Traccia quali report settimanali sono stati inviati con successo per
-- evitare invii doppi. Il record viene creato SOLO dopo l'invio email
-- riuscito: se l'email fallisce, il prossimo trigger riprova.

CREATE TABLE IF NOT EXISTS weekly_report_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    periodo_inizio  DATE NOT NULL,
    periodo_fine    DATE NOT NULL,
    inviato_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    destinatari     TEXT[] NOT NULL,
    UNIQUE(organization_id, periodo_inizio, periodo_fine)
);

ALTER TABLE weekly_report_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY weekly_report_log_org_member ON weekly_report_log
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
