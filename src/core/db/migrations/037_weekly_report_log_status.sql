-- Migration 037: Stato del claim nel log report settimanale
--
-- Aggiunge la colonna 'stato' a weekly_report_log per supportare il
-- claim atomico dell'invio (FIX 2b del redteam punto 17):
--   - 'pending': claim ottenuto, generazione/invio in corso
--   - 'sent':    invio riuscito (report non rinviato)
--   - 'failed':  invio fallito (il prossimo run puo' reclamare e riprovare)
--
-- Le righe esistenti (create dalla 036 SOLO dopo invio riuscito) vengono
-- migrate a 'sent' retroattivamente.

ALTER TABLE weekly_report_log
    ADD COLUMN IF NOT EXISTS stato TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE weekly_report_log
    ADD COLUMN IF NOT EXISTS motivo_errore TEXT;

-- Il claim INSERT non conosce ancora i destinatari (recuperati dopo la
-- generazione): la colonna diventa opzionale per supportare lo stato
-- 'pending'/'failed' senza destinatari noti.
ALTER TABLE weekly_report_log
    ALTER COLUMN destinatari DROP NOT NULL;

ALTER TABLE weekly_report_log
    DROP CONSTRAINT IF EXISTS weekly_report_log_stato_check;

ALTER TABLE weekly_report_log
    ADD CONSTRAINT weekly_report_log_stato_check
        CHECK (stato IN ('pending', 'sent', 'failed'));

UPDATE weekly_report_log
    SET stato = 'sent'
    WHERE stato = 'pending';