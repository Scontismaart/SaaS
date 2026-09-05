# FASE 5: REPORT ARCHITETTURALE E COMPLETAMENTO

**Sistemi Coinvolti:**
- Sicurezza Webhook Unificata Meta (WhatsApp & Instagram)
- Retry Worker Multi-Canale
- Background Jobs Distribuiti con PostgreSQL Session Advisory Lock
- Health Probes di Produzione (`/api/health/live`, `/api/health/ready`)

---

## 1. Obiettivi e Perimetro della Fase 5

La Fase 5 chiude la standardizzazione del layer di ingresso, consegna e schedulazione del sistema:

1. **Unificazione della Sicurezza Webhook Meta**: Centralizzazione di HMAC-SHA256, handshake GET (`hub.challenge`), replay protection (`X-Timestamp`) e streaming DoS limits in un componente riusabile (`MetaWebhookSecurity`).
2. **Decoupling Architetturale Netto**: Rimozione dell'import anomalo di funzioni private da `whatsapp/router.py` a `instagram/router.py`.
3. **Multi-Channel Retry Resiliency**: Spostamento del retry worker da modulo specifico WhatsApp a worker multi-canale di core (`MultiChannelRetryWorker`), con routing dinamico via `OutboundChannelRouter`.
4. **Schedulazione Distribuita Multi-Istanza**: Protezione dei background job contro esecuzioni sovrapposte o concorrenti tramite session-level PostgreSQL advisory locks (`pg_try_advisory_lock`).
5. **Data Retention & Bounded Storage**: Eliminazione programmata dei record di dedup webhook più vecchi di 7 giorni (`webhook_idempotency`).
6. **Osservabilità di Produzione**: Introduzione di probe separate per Kubernetes/Docker (`/api/health/live` e `/api/health/ready`).

---

## 2. Matrice di Conformità agli 11 Invarianti di Sicurezza

| Invariante | Requisito di Progetto | Implementazione in Fase 5 |
| :--- | :--- | :--- |
| **1. Tenant Isolation** | Nessun accesso cross-tenant consentito | AST check superato con 0 violazioni. Repository methods esplicitamente tenant-scoped. |
| **2. Data Scope** | Scope dell'organizzazione obbligatorio | Query di repository e retry payload verificano `organization_id` deterministico. |
| **3. Webhook Latency** | ACK rapido a Meta (HTTP 200 immediato) | L'ingestione valida la sicurezza e persiste `received_pending_ai`. Zero chiamate sincrone a LLM. |
| **4. Idempotency** | Ogni side effect esterno deve essere idempotente | `webhook_idempotency` all'ingresso; deduplicazione tentativi e SKIP LOCKED nei worker. |
| **5. No Privileged AI Actions** | Nessuna mutazione diretta decisa dall'LLM | Tutti i side-effect (invii, prenotazioni, retry) passano per validation deterministic service layer. |
| **6. Fail-Closed Opt-Out** | Blocco marketing e gestione rigorosa opt-out | **0 invii outbound nel layer webhook.** La ricezione marca il payload; downstream il service applica l'opt-out. |
| **7. Guardrail Pipeline** | Validazione e moderazione dei messaggi generati | Pipeline invariata; i retry multi-canale inviano esclusivamente messaggi già validati. |
| **8. Cost & Budget Gov** | Quota hard-cap e attribuzione costi per tenant | Invariato; nessuna chiamata LLM eseguita nei componenti toccati in Fase 5. |
| **9. Observability** | Tracciamento strutturato con trace/org/message ID | Log strutturati JSON per eventi di sicurezza webhook (`webhook_hmac_rejected`, `webhook_timestamp_rejected`, ecc.). |
| **10. Secrets** | Nessun segreto esposto o loggato | Token di verifica e secret Meta passati via configurazione/env; mascheramento nei log. |
| **11. Human Escalation** | Escalation a operatore umano sempre preservata | Invariata e garantita dal flusso di orchestrazione. |

---

## 3. Dettaglio Implementativo per Task

### Task 1: Layer di Sicurezza Webhook Unificato (`MetaWebhookSecurity`)
- **File**: `src/core/channels/inbound/meta_security.py`
- **Responsabilità**:
  - `verify_challenge()`: Risponde al handshake GET iniziale di Meta con verifica a tempo costante (`hmac.compare_digest`).
  - `verify_timestamp()`: Protezione da replay attack su header `X-Timestamp` (tolleranza ±300s).
  - `read_limited_body()`: Streaming chunk-by-chunk per limitare la memoria a 5 MB contro attacchi DoS/OOM.
  - `verify_hmac()`: Validazione della firma `X-Hub-Signature-256` con `hmac.compare_digest`.
  - `authenticate_and_read()`: Orchestrazione pipeline completa di sicurezza pre-parsing.

### Task 2: Refactoring dei Router Webhook e Disaccoppiamento
- **File**: `src/whatsapp/router.py`, `src/instagram/router.py`
- **Cambiamenti**:
  - Eliminato: `from src.whatsapp.router import _read_limited_body, _verify_hmac` in `src/instagram/router.py`.
  - Entrambi i router ora iniettano `MetaWebhookSecurity` tramite `create_router(..., security=...)`.
  - `src/whatsapp/router.py` mantiene gli alias `_read_limited_body` e `_verify_hmac` come deleghe trasparenti a `MetaWebhookSecurity` per preservare la piena retrocompatibilità.

### Task 3: Retry Worker Multi-Canale
- **File**: `src/core/workers/retry_worker.py`, `src/whatsapp/retry_worker.py`
- **Cambiamenti**:
  - `MultiChannelRetryWorker` gestisce i retry distinguendo il canale di destinazione (`whatsapp` vs `instagram`).
  - Per Instagram: delega a `channel_router.get_adapter("instagram").send_reply(...)`.
  - Per WhatsApp: delega a `service.attempt_delivery(...)` o `channel_router.get_adapter("whatsapp")`.
  - Reaping dei lock pendenti con `reap_stale_claims()`.
  - Backoff esponenziale su fallimento transitorio; marcatura a `failed` (dead-letter) dopo superamento di `max_retry_attempts`.
  - `src/whatsapp/retry_worker.py` convertito in Facade pura che delega ogni invocazione a `MultiChannelRetryWorker`.

### Task 4: Schedulazione Distribuita e Bonifica Data Access
- **File**: `src/core/jobs/base.py`, `src/core/scheduler.py`, `src/core/bookings/reminder_job.py`, `src/core/db/repositories/booking_repo.py`, `src/whatsapp/idempotency.py`, `src/core/retention_job.py`
- **Cambiamenti**:
  - `execute_with_advisory_lock(pool, lock_name, job_coro)`: acquisisce una connessione dedicata e invoca `pg_try_advisory_lock($1)`. Se occupato, salta l'esecuzione senza bloccare. Nel `finally` esegue sempre `pg_advisory_unlock($1)`.
  - Dimensione pool effimero dello scheduler portata a `_JOB_POOL_MIN = 2`, `_JOB_POOL_MAX = 5` per prevenire la starvation da connessione lockata.
  - Sostituite le query raw SQL in `reminder_job.py` con i metodi dedicati `mark_reminder_sent` e `list_reminders_timed_out` su `BookingRepository`.
  - Implementata funzione `purge_webhook_idempotency(pool, days=7)` integrata nel ciclo di `run_retention()`.

### Task 5: Health Probes di Produzione
- **File**: `src/api/main.py`, `src/core/auth/csrf.py`
- **Endpoint**:
  - `GET /api/health/live`: Rileva lo stato del processo e l'eventuale terminazione anomala dei loop asincroni in background (`inbound_task`, `retry_task`). Ritorna 503 se un task è fallito con eccezione non gestita.
  - `GET /api/health/ready` (e alias `/api/health`): Esegue `SELECT 1` sul connection pool del database e valida la configurazione delle API key. Ritorna 503 se il DB non risponde.
  - Aggiornati middleware di rate-limiting e filtri CSRF per escludere tutte le route `/api/health*`.

---

## 4. Risoluzione dei Punti Architetturali Sollevati

### Punto 1: Invariante 6 (Fail-Closed Opt-Out)
Nel layer webhook non viene mai generato alcun messaggio verso l'esterno.
- Il webhook esegue solo: verifica firma HMAC -> controllo deduplicazione atomico -> salvataggio messaggio con stato `received_pending_ai` -> ritorno HTTP 200 a Meta.
- La decisione e l'applicazione dell'opt-out avvengono nel worker di background (`InboundProcessingService`), dove ogni contatto con opt-out attivo viene isolato deterministicamente prima di qualsiasi elaborazione AI o invio outbound.
- I reminder schedulati controllano lo stato di consenso del contatto prima di effettuare l'invio.

### Punto 2: Session-Level vs Transactional Advisory Lock
È stato scelto **`pg_try_advisory_lock` (Session-Level)** e NON `pg_try_advisory_xact_lock`:
- Un lock transazionale imporrebbe di tenere aperta una transazione SQL per l'intera durata del job, inclusi i tempi di I/O verso le API esterne (chiamate WhatsApp/Meta).
- Tenere transazioni lunghe aperte causa `idle in transaction`, esaurimento delle connessioni del pool e problemi di autovacuum in PostgreSQL.
- Il lock di sessione acquisito su una connessione dedicata del pool (`async with pool.acquire() as conn:`) persiste attraverso sub-query e sub-transazioni indipendenti, e si rilascia deterministicamente nel blocco `finally` o automaticamente in caso di caduta della connessione TCP.

### Punto 3: Disaccoppiamento Completo Router Instagram / WhatsApp
L'import anomalo `from src.whatsapp.router import _read_limited_body, _verify_hmac` è stato rimosso.
- Un test di analisi statica AST (`test_no_cross_import_between_instagram_and_whatsapp`) verifica attivamente nel codice sorgente l'assenza di dipendenze tra i due moduli.
- Entrambi i router importano ora la classe comune da `src.core.channels.inbound.meta_security`.

### Punto 4: Politica di Retention e Purge Bounded
La tabella `webhook_idempotency` possiede un indice temporale su `created_at`.
- La funzione `purge_webhook_idempotency(pool, days=7)` esegue:
  ```sql
  DELETE FROM webhook_idempotency WHERE created_at < NOW() - ($1 || ' days')::INTERVAL;
  ```
- L'operazione è inserita nel cron notturno delle 03:00 insieme alle altre operazioni di retention del GDPR, mantenendo il volume della tabella delimitato nel tempo.

### Punto 5: Facade Pattern e Retrocompatibilità dei Test
- `src/whatsapp/retry_worker.py:RetryWorker` è rimasto come Facade di delega identica verso `MultiChannelRetryWorker`.
- L'import dinamico di `load_tenant_config` permette ai mock esistenti (es. `patch("src.whatsapp.config.load_tenant_config")`) di continuare a funzionare senza modifiche ai test esistenti.

---

## 5. Risultati della Validazione e Quality Gates

### Suite di Test Unitaria
- **Baseline Pre-Flight**: 238 test passati.
- **Nuovi Test Introdotti**: +31 test unitari specifici:
  - `test_meta_webhook_security.py`: 9 test.
  - `test_webhook_routers_unified_security.py`: 6 test.
  - `test_retry_worker_multichannel.py`: 6 test.
  - `test_distributed_jobs_advisory_lock.py`: 6 test.
  - `test_health_probes.py`: 4 test.
- **Totale Eseguito**: **269 passati, 0 falliti (100% GREEN)** in 34.85s.

### Tenant Scoping AST Check
- Script: `python scripts/check_tenant_scoping.py`
- Risultato: **0 violazioni di tenant isolation.**

### Knowledge Graph Update
- Script: `graphify update .`
- Risultato: Grafo sincronizzato con successo (30.530 nodi, 51.623 relazioni, 1.852 community).

---

## 6. Cronologia Canonica del Programma di Refactoring (Fasi 1–5)

A futura memoria e per evitare disallineamenti storici, la sequenza cronologica effettiva delle 5 fasi completate è la seguente:

1. **Fase 1 — Decomposizione dei God Repository**:
   Scomposizione di `CoreRepository` e `WhatsAppRepository` in repository specializzati per entità (`BookingRepository`, `OrganizationRepository`, `DocumentRepository`, `BillingRepository`, `ConversationRepository`, `ContactRepository`). Introduzione dell'enforcement AST per il tenant scoping obbligatorio.
2. **Fase 2 — Unificazione dell'Orchestratore Conversazionale**:
   Creazione di `ConversationOrchestrator`, centralizzazione dei flussi di risposta (fast-path, RAG documentale, FAQ cache, booking intent, escalation umana) e introduzione della shadow mode (`SHADOW_ORCHESTRATOR`) e del feature flag `USE_CONVERSATION_ORCHESTRATOR`.
3. **Fase 3 — Scomposizione di `main.py` in Router Dedicati**:
   Modularizzazione dell'API monolitica in 5 router specializzati (`auth`, `organization`, `dashboard`, `knowledge`, `integrations`) con contratti espliciti di dependency injection e rimozione del codice morto/duplicato.
4. **Fase 4 — Processing Inbound a 2 Stadi, Concorrenza Atomica & Quarantena Legacy**:
   Separazione dell'ingestione in 2 stadi (`InboundProcessingService` e `InboundWorker`), risoluzione dei 5 scenari di race condition (claim `SKIP LOCKED`, heartbeat lease, outbox deduplicata pre-invio), quarantena di `LegacyInboundPipeline` con timer di sunset al **2026-09-19**.
5. **Fase 5 — Sicurezza Webhook, Retry Multi-Canale, Scheduling Distribuito & Probes**:
   Centralizzazione della sicurezza Meta in `MetaWebhookSecurity`, eliminazione del cross-import tra WhatsApp e Instagram, worker `MultiChannelRetryWorker`, session advisory lock per cron multi-istanza, retention a 7 giorni di `webhook_idempotency` e health probes (`/api/health/live`, `/api/health/ready`).

---

## 7. Tabella di Marcia Consolidativa: Staging E2E & Sunset Legacy

Prima di valutare ulteriori fasi di refactoring, la priorità è consolidare le fondamenta attraverso due azioni obbligate (entrambe completate e verificate):

### Priorità A: Piano di Staging & Verifica End-to-End Integrata (COMPLETATA)
Realizzato in `tests/integration/test_staging_e2e_integrated_harness.py`, copre i 4 scenari critici sotto concorrenza reale:
1. **Scenario E2E-A (Multi-Tenant Inbound Concurrency & Relational Hierarchy Invariance)**:
   - 50 messaggi concorrenti distribuiti su 3 tenant distinti ($T_A, T_B, T_C$).
   - Audit automatico su tutta la gerarchia: `m.organization_id == c.organization_id == ct.organization_id` su tutte le 50 righe (0 violazioni, 0 cross-tenant leak).
2. **Scenario E2E-B (Worker Race su SKIP LOCKED, Outbox Pre-Dedup & Heartbeat Cancellation)**:
   - 2 InboundWorker concorrenti su 20 messaggi pendenti: zero claim duplicati, insiemi rigorosamente disgiunti ($W_1 \cap W_2 = \emptyset$).
   - Outbox Pre-Dedup: messaggi già inviati ignorati deterministicamente; messaggi ritentati post-crash inviati da dedup cache con **0 chiamate duplicate all'orchestratore LLM**.
   - Heartbeat lease cancellato deterministicamente nel blocco `finally` sia a completamento normale sia su eccezione non gestita (zero zombie task).
3. **Scenario E2E-C (Cron Session Advisory Lock & Pool Safety)**:
   - 2 istanze concorrenti su `execute_with_advisory_lock`: mutua esclusione esatta (1 eseguita, 1 skippata no-op).
   - Rilascio sessione garantito in `finally`: connessioni attive nel pool ritornate a 0 (zero leak `idle in transaction`), successiva esecuzione acquisibile immediatamente.
4. **Scenario E2E-D (Production Health Probes Under Load & Crash Simulation)**:
   - 20 chiamate concorrenti su `/api/health/live` e `/api/health/ready` (HTTP 200 OK).
   - Crash simulation di worker background: `/api/health/live` risponde immediatamente HTTP 503 unhealthy con traceback isolato.
   - DB failure simulation: `/api/health/ready` risponde HTTP 503 degraded.
   - Ripristino dinamico a HTTP 200 OK senza restart del processo.

### Priorità B: Protocollo di Osservazione & Purge Quarantena Legacy (Scadenza: 2026-09-19) (COMPLETATA)
- **Script di Audit Matematico Pre-Sunset**: Realizzato in `scripts/audit_shadow_divergence.py`.
  - Criteri tassativi: Errori comparazione == 0, Troncamenti anomali == 0, Verbosità fuori scala (>4x o >2500c) == 0.
  - Floor protettivo per risposte brevi/FAQ: differenze relative >50% ignorate se $\max(\text{lengths}) < 40$ o $|\Delta| < 25$ caratteri (elimina falsi positivi sistematici).
  - Firma formale di Human Review: divergenze soft (>5.0%) richiedono `--reviewer` e `--rationale`, bloccando categoricamente qualsiasi override in presenza di crash o troncamenti.
- **Suite di Test Unitari Dedicata**: `tests/unit/test_audit_shadow_divergence.py` (10 test passati, 100% green).
- **Checklist di Chiusura Definitiva (da eseguire il 2026-09-19)**:
  1. Esecuzione `python scripts/audit_shadow_divergence.py --log-file prod.log` -> Verdetto GO.
  2. Rimozione di `src/core/inbound/legacy_pipeline.py`.
  3. Rimozione del branch `if not self.use_orchestrator` in `src/core/inbound/service.py`.
  4. Deprecazione del feature flag `USE_CONVERSATION_ORCHESTRATOR` a favore dell'orchestratore come path unico e definitivo.

---

## 8. Riepilogo Quality Gates Finali (Consolidamento Fasi 1–5)

- **Test Suite Totale**: **283 test eseguiti, 283 passati (0 falliti, 100% GREEN)**:
  - 279 test unitari (`pytest tests/unit/`)
  - 4 test di integrazione staging E2E (`pytest tests/integration/`)
- **Tenant Scoping AST Check**: **0 violazioni di tenant isolation** (`scripts/check_tenant_scoping.py`).
- **Knowledge Graph**: Aggiornato con `graphify update .` (30.628 nodi, 51.824 archi, 1.817 community).

