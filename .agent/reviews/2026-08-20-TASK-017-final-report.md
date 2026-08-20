# Report finale — Task 17: Analytics e report vendibili (redteam punto 17)

- Data: 2026-08-20
- Branch: `task17/analytics-report-vendibili`
- Commit base del task: `52ad54e` "feat(report): implementa report settimanale PDF e export CSV (Task 17)"
- Modifiche successive: working tree sul branch (NON ancora committate)
- Stato suite: **657 passed, 9 skipped, 0 fail**

---

## Contesto

Il commit `52ad54e` ha introdotto la feature "report settimanale vendibile"
(KPI analitici settimanali, PDF con WeasyPrint, export CSV per commercialista,
invio email schedulato). La revisione avversaria (redteam punto 17) ha emesso
i fix **FIX 1, FIX 2a, FIX 2b, FIX 3, FIX 5, FIX 8**, implementati in questa
sessione congiuntamente da opencode e Claude.

Questo report documenta TUTTE le modifiche apportate dopo il commit base,
per la revisione dell'agent reviewer.

---

## FIX 1 — KPI messaggi coerenti col dashboard (fonte unica `event_log`)

### Problema
`calcola_kpi_messaggi` leggeva i conteggi direttamente da `messages`
(`handling_type = 'ai_handled'` / `'escalated'`), mentre il dashboard usa la
proiezione derivata `event_log` (popolata dai trigger). Le due fonti potevano
divergere (es. messaggi inbound gestiti ma mai "handled", campi diversi).

### Modifica — `src/core/analytics/kpi.py`
- `calcola_kpi_messaggi` ora legge i conteggi (`totale`, `gestiti_da_ai`,
  `escalati`) da `event_log` con filtri `source_table='messages'`,
  `tipo_evento='messaggio'`, in **una sola query** con subquery.
- `escalati = NOT gestito_da_ai` (allineato a `calcola_statistiche`:
  `girati_a_umano = totale - gestiti_ai`).
- `avg_risposta_sec` resta su `messages.replied_at` (event_log non espone
  `replied_at`), sempre in subquery nella stessa fetchrow.
- Docstring aggiornata e nota "Fonte unificata degli analytics (FIX 1)".

### Test
- **Equivalenza matematica** in `tests/core/test_kpi_integration.py`
  (`test_equivalenza_kpi_statistiche_su_stessi_dati`): su STESSI dati reali,
  `kpi.totale == stats.totale_messaggi`, `kpi.gestiti_da_ai == stats.gestiti_da_ai`,
  `kpi.escalati_a_umano == stats.girati_a_umano`. Entrambe le funzioni leggono
  dalla stessa `event_log`.
- `tests/core/test_kpi.py` (mock) invariato e passante: il contratto fetchrow
  è preservato.

---

## FIX 2a — Invio sincrono e concorrenza reale

### Problema
L'invio email passava da `_enqueue` (coda in RAM) e `genera_report_tutte_le_org`
iterava le org **in sequenza**.

### Modifica — `src/core/report/weekly_report.py`
- `_genera_e_invia` usa `await _send_with_retry(EmailEvent(...))` (invio
  sincrono con retry tenacity interno 3x) al posto di `_enqueue`.
- `_enqueue` rimane in `email_service.py` per escalation/suspension
  (usati da `inbound_processor.py`/`scheduler.py`): NON rimossa.
- `genera_report_tutte_le_org` ora usa `asyncio.gather(..., return_exceptions=True)`
  con `asyncio.Semaphore(5)`.
- **Pool allineato**: produzione `src/api/main.py:109` →
  `asyncpg.create_pool(min_size=1, max_size=5)`, quindi `Semaphore(5)` non
  crea colli di bottiglia.
- **Discriminazione esplicita** delle eccezioni restituite da gather (FIX 2a):
  `if isinstance(ris, Exception)` → `{"esito": "errore", "errore": str(ris)}`;
  `elif isinstance(ris, dict)` → esito reale; `else` → `repr(ris)`. Nessun
  errore perso nell'array; mapping per indice al tenant (ordine preservato).

### Test
- `tests/core/test_weekly_report.py::test_invio_riuscito_marca_sent` (mock).
- `tests/core/test_weekly_report_integration.py::test_due_esecuzioni_concorrenti_non_doppio_invio`
  (Docker): 2 `genera_e_invia_report_settimanale` concorrenti via `asyncio.gather`
  → `sent_count == 1`, esiti `{"inviato", "gia_inviato"}`, stato finale `sent`.

---

## FIX 2b — Claim atomico single-step con colonna `stato`

### Problema
`_registra_invio` scriveva il log SOLO dopo l'invio; non esisteva un meccanismo
di lock per impedire che due worker inviassero lo stesso report.

### Modifica — migration `037_weekly_report_log_status.sql` (NUOVO)
- `ALTER TABLE weekly_report_log ADD COLUMN stato TEXT NOT NULL DEFAULT 'pending'`.
- `ADD COLUMN motivo_errore TEXT`.
- `ALTER COLUMN destinatari DROP NOT NULL` (il claim INSERT non conosce ancora
  i destinatari; recuperati dopo la generazione).
- Constraint `weekly_report_log_stato_check CHECK (stato IN ('pending','sent','failed'))`.
- Backfill: `UPDATE weekly_report_log SET stato='sent' WHERE stato='pending'`
  (le righe esistenti, create dalla 036 SOLO dopo invio, migrano a `sent`).

### Modifica — `src/core/report/weekly_report.py`
- `_claim_periodo` — **claim atomico single-step**:
  ```sql
  INSERT INTO weekly_report_log (organization_id, periodo_inizio, periodo_fine, stato)
  VALUES ($1, $2, $3, 'pending')
  ON CONFLICT (organization_id, periodo_inizio, periodo_fine)
  DO UPDATE SET stato = 'pending'
  WHERE weekly_report_log.stato = 'failed'
  RETURNING id
  ```
  Semantica: **1 riga** = claim ottenuto (nuovo o re-claim da `failed`);
  **0 righe** = già `pending` (in corso) o `sent` (inviato) → il chiamante
  esce con `"gia_inviato"`. Il lock è garantito dal row-lock dell'UPDATE;
  nessuna race tra worker.
- `_segna_stato` — update per-id: `sent` aggiorna `destinatari`/`inviato_at`;
  `failed` li lascia invariati (il prossimo run può reclamare e riprovare).
- `_is_report_gia_inviato` aggiunge `AND stato = 'sent'`.
- Flusso `genera_e_invia_report_settimanale`: claim → `_genera_e_invia` →
  `_segna_stato('sent')`. Su `no_destinatari` il claim viene rilasciato
  (`failed`, motivo "nessun destinatario") per permettere retry futuro.
- Su errore definitivo: `_segna_stato('failed', motivo=str(ultimo_errore))` +
  alert + re-raise. Il record non resta mai bloccato in `pending`.

### Test
- Unit (mock): `test_invio_idempotente_non_reinvia`, `test_invio_senza_owner_non_invia`
  (verifica rilascio claim → `failed`), `test_invio_riuscito_marca_sent`,
  `test_errore_permanente_marca_failed_e_raise`, `test_errore_transiente_retry_poi_failed`.
- Integration (Docker) in `tests/core/test_weekly_report_integration.py`:
  `test_claim_nuovo_ottiene_lock`, `test_claim_pending_non_reclamabile`,
  `test_claim_sent_non_reclamabile`, `test_claim_failed_reclamabile`,
  `test_crash_a_meta_invio_non_marca_sent` (patch `_genera_e_invia` →
  `MemoryError`; claim fatto dal flusso reale, senza pre-claim; verifica
  `stato != 'sent'`), `test_due_esecuzioni_concorrenti_non_doppio_invio`.

### Migrazione `036_weekly_report_log.sql` — idempotenza
- Il `CREATE POLICY weekly_report_log_org_member` è stato avvolto in
  `DO $$ ... IF NOT EXISTS (SELECT 1 FROM pg_policies ...)` (pattern già usato
  dalla 008). Necessario perché il fixture `pg_pool` è function-scoped e
  riesegue le migrazioni ad ogni test; senza guard, il 2° test falliva con
  `DuplicateObjectError`.

---

## FIX 3 — Allowlist eccezioni transienti + alert Sentry

### Problema
Il flusso ritentava qualsiasi eccezione (o non ritentava affatto), senza
distinzione transitorio/permanente e senza alert.

### Modifica — `src/core/report/weekly_report.py`
- `TRANSIENT_EXCEPTIONS = (smtplib.SMTPException, ConnectionError, TimeoutError, asyncio.TimeoutError)`.
- `MAX_TENTATIVI_TRANSIENTI = 3` (1 iniziale + 2 retry esterni; sommati ai 3
  interni di `_send_with_retry`).
- Loop di retry: transiente esaurito → `_segna_stato('failed')` + `_allerta_sentry`
  + raise. Qualsiasi altra eccezione (permanente) → `failed` + alert immediato
  + raise, **nessun retry**.
- `_allerta_sentry`: `sentry_sdk.capture_exception` in try/except (mai rompe
  il flusso) + `logger.error`.
- **Guardia SMTP**: in `_genera_e_invia`, se `_get_smtp_config() is None`
  → `raise RuntimeError("configurazione SMTP assente")`. Senza guardia,
  `_send_with_retry` tornerebbe silenziosamente e si marcerebbe `sent` un
  report mai spedito.
- Flag `inviato` nel loop: evita la rispedizione dell'email se il fallimento
  avviene DOPO l'invio (es. mark `sent` con DB irraggiungibile).

### Test
- `test_errore_permanente_marca_failed_e_raise` — un solo tentativo,
  `mock_segna('failed')`, `mock_alert` chiamata.
- `test_errore_transiente_retry_poi_failed` — 3 tentativi, poi `failed` + alert.

---

## FIX 5 — Test di integrazione KPI e report (nuovi file)

### `tests/core/test_kpi_integration.py` (NUOVO, marker `integration`)
- Boundary messaggi: dentro/fuori periodo, al confine, AI vs escalated,
  risposti/non risposti, cross-org.
- Prenotazioni: stati + periodo + origine WhatsApp.
- Recensioni: stato risposta + media stelle.
- **Equivalenza FIX 1** (kpi ↔ statistiche su stessi dati).
- Aggregato settimanale reale (tutti i sotto-KPI popolati).

### `tests/core/test_weekly_report_integration.py` (NUOVO, marker `integration`)
- 6 test di claim/rilascio/concorrenza (vedi FIX 2b/2a).

### `pytest.ini`
- Registrato marker `integration`.

### `tests/core/conftest.py`
- Carica le migrazioni 036, 037 e **038** (in ordine dopo la 033; la 038 è
  `CREATE OR REPLACE` dei trigger, idempotente).
- `weekly_report_log` aggiunto alla TRUNCATE di `reset_db`.
- I contenuti di 036/037 letti a livello di modulo (fuori dalle funzioni async)
  per non aggiungere errori ASYNC230 al fixture `pg_pool`.

---

## FIX 8 — Note di processo / hardening futuro

- **Benchmark di settore**: il roadmap Task 17 prevede il benchmark
  ("i tuoi tempi sono migliori del 40% della media"), rimandato a fase 2.
  Il template `weekly_report.html:161-167` mantiene il placeholder
  "Disponibile prossimamente — fase 2". **Il placeholder NON è stato
  modificato**: la roadmap chiede esplicitamente di domandare all'utente la
  fonte dei dati (reale/stimato/fase 2) PRIMA di implementarla. In questa
  sessione non c'è evidenza di una risposta "Question 1/5" su benchmark →
  **debito di processo, non un fix da applicare ora**.
- **Hardening futuro (non implementato)**: se un processo muore con
  `kill -9` durante l'invio, il claim resta `pending` (stale). Per la semantica
  attuale è accettabile (mai `sent` falso), ma in futuro è auspicabile un cron
  che sblocchi i `pending` più vecchi di 15-30 min (→ `failed`) per permettere
  il re-claim. Documentato nei commenti di test.

---

## Bug correlati emersi durante i fix (fix di Claude)

### Trigger `log_message_event`/`log_review_event` — `created_at` mancante
- **Bug**: i trigger non passavano `created_at` all'INSERT su `event_log`,
  quindi la colonna usava il `DEFAULT NOW()` della tabella: ogni riga prendeva
  l'istante di inserimento (oggi), non il timestamp del messaggio/recensione.
  I KPI su periodo storico risultavano sempre 0.
- **Fix**: `src/core/db/triggers.sql` ora passa `NEW.created_at` su entrambi i
  trigger.
- **Migration `038_event_log_created_at.sql` (NUOVO)**: `CREATE OR REPLACE`
  dei due trigger. Registrata in `conftest.py`.
  - **Regressione evitata durante il primo giro**: la 038 iniziale riscriveva
    `log_review_event` con la logica priorità vecchia, cancellando il fix della
    migration `023_fix_review_priority_trigger.sql` (sentiment +
    `richiede_revisione_urgente`). Corretto: la 038 preserva quella logica e
    ri-applica l'hardening `search_path` di 011/032.

### Bug timezone nei confini di periodo (off-by-one su fusi non-UTC)
- `created_at >= $2` e `< $3 + INTERVAL '1 day'` con `$2/$3` di tipo `date`
  facevano castare Postgres a `timestamptz` usando il timezone di SESSIONE.
  Su sistemi UTC+2 (es. Rome) i confini slittavano, includendo record del
  giorno prima (visto nei test: 6 invece di 5 prenotazioni, 5 invece di 4
  recensioni).
- **Fix**: `($2::timestamp AT TIME ZONE 'UTC')` e
  `(($3::timestamp + INTERVAL '1 day') AT TIME ZONE 'UTC')` — deterministico
  indipendente dal timezone di sessione. Applicato in **tutte** le query di
  `kpi.py` (messaggi/prenotazioni/recensioni) e nella query raw del test di
  equivalenza in `test_kpi_integration.py`.
- Corregge anche l'`AmbiguousParameterError` di asyncpg (`interval` vs
  `timestamp with time zone`) visto sul primo run: il cast esplicito elimina
  l'ambiguità di inferenza del parametro `$3`.

### Encoding Windows (`conftest.py`)
- `conftest.py` apriva i file `.sql` senza `encoding="utf-8"`: su Windows
  Python usa `cp1252` di default e un apostrofo tipografico in una migration
  faceva `UnicodeDecodeError` in fase di setup.
- **Fix**: `encoding="utf-8"` aggiunto a tutti gli `open(...)` del conftest
  (31 occorrenze, compresi i moduli 036/037/038).

### Test che dipendevano da dettagli non parseati
- `_storico_da_event_log` in `test_kpi_integration.py` usava
  `dict(r["dettagli"])` su una colonna `jsonb` che asyncpg restituisce come
  **stringa** → `ValueError: dictionary update sequence element #0 has length 1`.
  **Fix**: `json.loads(r["dettagli"] or "{}")`, coerente con la convenzione
  del repo (`test_onboarding.py:67-69`).

### Test crash pre-claim
- `test_crash_a_meta_invio_non_marca_sent` pre-claimava il periodo, quindi
  `genera_e_invia_report_settimanale` (che fa il claim da solo) usciva subito
  con `gia_inviato` senza mai chiamare `_genera_e_invia` → `DID NOT RAISE`.
  **Fix**: rimosso il pre-claim; il claim lo fa il flusso reale e la patch
  `MemoryError` colpisce `_genera_e_invia`.

---

## File modificati/creati

### Modificati (rispetto a `52ad54e`)
| File | Modifica |
|---|---|
| `src/core/analytics/kpi.py` | FIX 1 (event_log) + timezone-safe UTC |
| `src/core/report/weekly_report.py` | FIX 2a/2b/3 (claim, semaforo, retry, alert) |
| `src/core/db/migrations/036_weekly_report_log.sql` | policy idempotente |
| `src/core/db/triggers.sql` | `NEW.created_at` nei trigger |
| `tests/core/conftest.py` | encoding utf-8, migrazioni 036/037/038, truncate |
| `tests/core/test_weekly_report.py` | riscritto per nuovo flusso |
| `pytest.ini` | marker `integration` |

### Nuovi
| File | Contenuto |
|---|---|
| `src/core/db/migrations/037_weekly_report_log_status.sql` | colonna `stato` + `motivo_errore` + CHECK + backfill |
| `src/core/db/migrations/038_event_log_created_at.sql` | trigger con `NEW.created_at` (preserva 023) |
| `tests/core/test_kpi_integration.py` | FIX 1/5 integrazione KPI |
| `tests/core/test_weekly_report_integration.py` | FIX 2a/2b/3 integrazione |

---

## Verifiche

- **Suite completa**: `python -m pytest -q` → **657 passed, 9 skipped, 0 fail**.
- **Integrazione dedicata**: `python -m pytest tests/core/test_weekly_report_integration.py tests/core/test_kpi_integration.py -q` → **13 passed**.
- **Ruff** sui file applicativi/test toccati:
  - `kpi.py`, `test_weekly_report.py`: puliti.
  - `weekly_report.py`: 1 `BLE001` (pre-esistente, baseline).
  - `test_kpi_integration.py`: 1 `I001` import non ordinato (fixable).
  - `conftest.py`: 33 errori (1 `I001` + 32 `ASYNC230`): `I001` e 31 `ASYNC230`
    pre-esistenti (baseline 32); +1 `ASYNC230` per l'`open` della 038 nel
    fixture async — stesso pattern già accettato nel file.

---

## Verdetto

Tutti i FIX del redteam punto 17 sono implementati, testati (unit + integrazione
Docker) e la suite è verde. Nessun segreto introdotto, query parametrizzate,
nessuna superficie di injection. Restano solo debiti documentati non-blocking:
1 `I001` fixable in un test nuovo, e l'hardening futuro degli stale `pending`
claims (cron 15-30 min) — da valutare in un task separato.