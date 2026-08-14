-- Migration 028: profili onboarding org-scoped
-- Sostituisce data/onboarding_profiles.json (store globale della demo) con una
-- tabella per-organizzazione. Ogni salvataggio sincronizza
-- organizations.business_profile, il profilo letto dal responder WhatsApp reale
-- (load_tenant_config -> organizations.business_profile), cosi' il flusso di
-- produzione usa subito la configurazione fatta dal wizard.
--
-- L'audit utilizza event_log, lo stesso feed org-scoped gia' usato da task13
-- per SLA/HITL. event_log non e' mai scritto dal codice applicativo (invariante
-- documentata in schema.sql: "proiezione derivata da trigger"): per coerenza la
-- riga la scrive un TRIGGER su questa tabella, come gia' accade per messages e
-- reviews in triggers.sql.

CREATE TABLE IF NOT EXISTS onboarding_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) UNIQUE,
    verticale           TEXT NOT NULL,
    nome_attivita       TEXT NOT NULL,
    orari               TEXT NOT NULL DEFAULT '',
    tono                TEXT NOT NULL DEFAULT '',
    servizi             JSONB NOT NULL DEFAULT '[]',
    regole_escalation   JSONB NOT NULL DEFAULT '[]',
    whatsapp_collegato  BOOLEAN NOT NULL DEFAULT FALSE,
    documenti_importati BOOLEAN NOT NULL DEFAULT FALSE,
    profilo             JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_profiles_org ON onboarding_profiles(organization_id);

-- RLS org-scoped (pattern 008_rls_hardening + 009_rls_write_check: FOR ALL
-- con USING e WITH CHECK, altrimenti un UPDATE potrebbe spostare la riga
-- sotto un'altra org).
ALTER TABLE onboarding_profiles ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'onboarding_profiles_org_member') THEN
        CREATE POLICY onboarding_profiles_org_member ON onboarding_profiles
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

-- event_log derivato da trigger (stesso pattern di messages/reviews):
-- ogni salvataggio profilo genera un evento "onboarding" visibile nello
-- stesso feed org-scoped di inbox/dashboard.
CREATE OR REPLACE FUNCTION log_onboarding_event() RETURNS trigger AS $$
BEGIN
  INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                         testo_originale, gestito_da_ai, dettagli)
  VALUES (
    NEW.organization_id, 'onboarding_profiles', NEW.id, 'onboarding',
    'bassa',
    NEW.nome_attivita,
    TRUE,
    jsonb_build_object(
      'verticale', NEW.verticale,
      'whatsapp_collegato', NEW.whatsapp_collegato,
      'documenti_importati', NEW.documenti_importati
    )
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_onboarding_event ON onboarding_profiles;
CREATE TRIGGER trg_log_onboarding_event
    AFTER INSERT OR UPDATE ON onboarding_profiles
    FOR EACH ROW EXECUTE FUNCTION log_onboarding_event();