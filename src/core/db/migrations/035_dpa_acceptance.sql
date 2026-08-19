-- Migration 035: accettazione DPA/ToS per organizzazione.
--
-- Il prodotto serviva un template DPA statico ma non registrava MAI
-- l'accettazione da parte del Titolare: la compliance GDPR richiede
-- evidenza di consenso (chi, quando, quale versione del documento).
-- Aggiungiamo timestamp di accettazione e versione del documento:
-- quando il DPA cambia (nuovo sub-processor, retention diversa) basta
-- bumpare la versione -> i tenant con dpa_version < nuova versione
-- vengono di nuovo bloccati fino a ri-accettazione (HTTP 428).

ALTER TABLE organizations
    ADD COLUMN IF NOT EXISTS dpa_accepted_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tos_accepted_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS dpa_version      TEXT NOT NULL DEFAULT '2026-07';
