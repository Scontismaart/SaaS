-- ============================================================
-- EVENT_LOG trigger functions
-- Popolato solo da trigger DB, mai dal codice applicativo
-- ============================================================

-- messages → event_log (inbound handled)
CREATE OR REPLACE FUNCTION log_message_event() RETURNS trigger AS $$
BEGIN
  IF NEW.direction = 'inbound' AND NEW.status = 'handled' THEN
    INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                           testo_originale, gestito_da_ai, dettagli)
    VALUES (
      NEW.organization_id, 'messages', NEW.id, 'messaggio',
      CASE WHEN NEW.handling_type = 'escalated' THEN 'alta' ELSE 'media' END,
      NEW.content_text,
      NEW.handling_type = 'ai_handled',
      jsonb_build_object('conversation_id', NEW.conversation_id, 'handling_type', NEW.handling_type)
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_message_event ON messages;
CREATE TRIGGER trg_log_message_event
    AFTER INSERT OR UPDATE OF status ON messages
    FOR EACH ROW EXECUTE FUNCTION log_message_event();

-- reviews → event_log
CREATE OR REPLACE FUNCTION log_review_event() RETURNS trigger AS $$
BEGIN
  INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                         testo_originale, gestito_da_ai, dettagli)
  VALUES (
    NEW.organization_id, 'reviews', NEW.id, 'recensione',
    CASE WHEN NEW.valutazione_stelle IS NOT NULL AND NEW.valutazione_stelle <= 2 THEN 'alta' ELSE 'bassa' END,
    NEW.testo,
    TRUE,
    jsonb_build_object('valutazione_stelle', NEW.valutazione_stelle, 'fonte', NEW.fonte)
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_review_event ON reviews;
CREATE TRIGGER trg_log_review_event
    AFTER INSERT ON reviews
    FOR EACH ROW EXECUTE FUNCTION log_review_event();
