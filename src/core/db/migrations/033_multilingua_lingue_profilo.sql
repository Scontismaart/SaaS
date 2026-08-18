-- Migration 033: multilingua nel profilo onboarding
-- Task 14: il bot rileva la lingua del cliente e risponde nella stessa lingua.
-- Il Titolare configura le lingue supportate e la lingua di default nel wizard
-- onboarding; la lingua di default (e il ramo best-effort/escalation) vivono
-- nel system prompt costruito da costruisci_system_prompt.
--
-- Default prudenti: solo "it" supportata, default "it" -> il comportamento
-- dei profili gia' salvati resta identico a prima della migration.

ALTER TABLE onboarding_profiles
    ADD COLUMN IF NOT EXISTS lingue_supportate JSONB NOT NULL DEFAULT '["it"]',
    ADD COLUMN IF NOT EXISTS lingua_default   TEXT   NOT NULL DEFAULT 'it';

-- Arricchisce l'audit event_log con le lingue configurate, nello stesso
-- pattern del trigger gia' esistente (dettagli JSONB per l'analisi).
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
      'documenti_importati', NEW.documenti_importati,
      'lingue_supportate', NEW.lingue_supportate,
      'lingua_default', NEW.lingua_default
    )
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_onboarding_event ON onboarding_profiles;
CREATE TRIGGER trg_log_onboarding_event
    AFTER INSERT OR UPDATE ON onboarding_profiles
    FOR EACH ROW EXECUTE FUNCTION log_onboarding_event();
