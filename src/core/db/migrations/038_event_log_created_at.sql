-- Migration 038: event_log.created_at deve riflettere il timestamp
-- dell'evento sorgente (NEW.created_at), non l'istante di insert.
--
-- Bug: log_message_event/log_review_event non passavano created_at,
-- quindi event_log usava il DEFAULT NOW() della tabella. I KPI
-- settimanali (src/core/analytics/kpi.py) filtrano event_log per
-- periodo storico e con NOW() risultavano sempre vuoti per dati
-- retroattivi/importati.
--
-- IMPORTANTE: log_review_event mantiene la logica priorita' introdotta
-- da 023_fix_review_priority_trigger.sql (sentiment + richiede_revisione_
-- urgente, non solo valutazione_stelle) — qui si aggiunge solo created_at.
-- Dopo ogni CREATE OR REPLACE va rifissato il search_path (hardening
-- 011/032), altrimenti il linter segnala "Function Search Path Mutable".

CREATE OR REPLACE FUNCTION log_message_event() RETURNS trigger AS $$
BEGIN
  IF NEW.direction = 'inbound' AND NEW.status = 'handled' THEN
    INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                           testo_originale, gestito_da_ai, dettagli, created_at)
    VALUES (
      NEW.organization_id, 'messages', NEW.id, 'messaggio',
      CASE WHEN NEW.handling_type = 'escalated' THEN 'alta' ELSE 'media' END,
      NEW.content_text,
      NEW.handling_type = 'ai_handled',
      jsonb_build_object('conversation_id', NEW.conversation_id, 'handling_type', NEW.handling_type),
      NEW.created_at
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER FUNCTION log_message_event() SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION log_review_event() RETURNS trigger AS $$
DECLARE
    _priorita TEXT;
BEGIN
    IF NEW.valutazione_stelle IS NOT NULL AND NEW.valutazione_stelle <= 2 THEN
        _priorita := 'alta';
    ELSIF NEW.richiede_revisione_urgente THEN
        _priorita := 'alta';
    ELSIF NEW.sentiment = 'negativa' THEN
        _priorita := 'media';
    ELSIF NEW.valutazione_stelle IS NOT NULL AND NEW.valutazione_stelle = 3 AND NEW.sentiment != 'positiva' THEN
        _priorita := 'media';
    ELSE
        _priorita := 'bassa';
    END IF;

    INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                           testo_originale, gestito_da_ai, dettagli, created_at)
    VALUES (
        NEW.organization_id, 'reviews', NEW.id, 'recensione',
        _priorita,
        NEW.testo,
        TRUE,
        jsonb_build_object(
            'valutazione_stelle', NEW.valutazione_stelle,
            'fonte', NEW.fonte,
            'sentiment', NEW.sentiment,
            'richiede_revisione_urgente', NEW.richiede_revisione_urgente
        ),
        NEW.created_at
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

ALTER FUNCTION log_review_event() SET search_path = public, pg_temp;
