-- 023_fix_review_priority_trigger.sql
-- Allinea il trigger log_review_event alla logica Python di
-- calcola_priorita_recensione(): considera sentiment e
-- richiede_revisione_urgente, non solo valutazione_stelle.
-- Cosi' event_log e _storico_eventi condividono la stessa priorita'.
-- Aggiunge sentiment e richiede_revisione_urgente ai dettagli evento.

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
                           testo_originale, gestito_da_ai, dettagli)
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
        )
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
