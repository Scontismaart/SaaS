# Phase 4: Application & Worker Layer Refactoring, Domain Services & Side-Effect Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decomporre l'Application & Worker Layer rifattorizzando il monolite `src/whatsapp/inbound_processor.py` (~795 righe) in componenti specializzati secondo Clean Architecture: disaccoppiare il ciclo di polling del worker (`InboundWorker`) dalla pipeline dei casi d'uso applicativi (`InboundProcessingService`), estrarre gli adapter di canale outbound (`ChannelOutboundPort`, `WhatsAppOutboundAdapter`, `InstagramOutboundAdapter`), iniettare i repository specializzati della Fase 1 nei servizi di dominio (`BookingService`, `email_service`, `scheduler`), consolidare l'idempotenza dei side-effect (P0-1/SEC-001 e P0-2/SEC-002), promuovere `USE_CONVERSATION_ORCHESTRATOR=true` come default con criterio esplicito di sunset per il branch legacy, garantendo il 100% di retrocompatibilità tramite facade.

**Architecture:**
- **Worker Infrastructure (`src/core/workers/`)**:
  - `InboundWorker`: polling loop atomico con `SKIP LOCKED`, gestione heartbeat transazionale, isolation degli errori su batch, disaccoppiato dalla logica di business.
- **Application Layer (`src/core/inbound/`)**:
  - `InboundProcessingService`: implementazione deterministica dei 12 step della pipeline inbound (claim/quota, opt-out fail-closed, richiesta operatore, emoji feedback, reminder reply, sospensione org, ticket claimed, fast-path, outbox dedup, orchestrazione cognitiva via `ConversationOrchestrator`, invio outbound, finalizzazione stato).
  - `LegacyInboundPipeline`: estrazione isolata del branch legacy (~270 righe) attivo solo se `USE_CONVERSATION_ORCHESTRATOR=false`.
- **Infrastructure / Outbound Channel Adapters (`src/core/channels/` o `src/whatsapp/outbound.py`, `src/instagram/outbound.py`)**:
  - `ChannelOutboundPort`: interfaccia unificata per la consegna dei messaggi.
  - `WhatsAppOutboundAdapter`: consegna messaggi WhatsApp Meta Cloud API con gestione disclosure e rate limiting.
  - `InstagramOutboundAdapter`: consegna messaggi Instagram DM con gestione crittografia token e formattazione payload.
- **Domain Services & Specialized Repositories (`src/core/bookings/`, `src/core/notifications/`, `src/core/scheduler.py`)**:
  - Transizione da God Facade (`CoreRepository`, `WhatsAppRepository`) all'iniezione diretta di `BookingRepository`, `OrganizationRepository`, `MessageRepository`, `ConversationRepository`.
- **Backward Compatibility Facade**:
  - `src/whatsapp/inbound_processor.py:InboundProcessor`: mantiene interfaccia, signature, metodi interni e hook per mock (`_send_ai_reply`, `_finalize_message`, `_process_one`) delegando ai nuovi servizi, preservando 100% dei test esistenti senza modifiche ai test caller.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, pgvector, Pydantic v2, pytest, unittest.mock.

**Spec:** Refactoring architetturale SaaS - Fase 4 (Application & Worker Layer, Domain Services, Channel Adapters, Side-Effect Reliability).

---

## Matrice di Duplicazione e Divergenza del Codice

La tabella documenta l'attuale duplicazione tra il legacy branch di `InboundProcessor` e `ConversationOrchestrator`, evidenziando i punti in cui le implementazioni rischiano di divergere silenziosamente:

| Componente / Fase | `InboundProcessor` (Legacy Pipeline, L385-653) | `ConversationOrchestrator` (`src/core/receptionist/`) | Rischio di Divergenza Silenziosa |
|---|---|---|---|
| **Classificazione Intent** | Invocazione manuale `classifica_intent(text)` + scrittura usage su DB | Invocata internamente in step 3 con billing usage attribuito | Disallineamento nei metadati di logging (es. `model_effettivo`, confidence) |
| **FAQ Cache Retrieval** | Invocazione `faq_cache.cerca_in_cache(str(org_id), ...)` con `q_emb` locale | Invocata internamente in step 4 con `doc_repo` e tracciamento `cache_hit` | Possibile mancata sincronizzazione tra embedding query e chiavi cache |
| **Recupero Cronologia Multi-turn** | Query manuale `list_conversation_messages` con loop di parsing tupla `(in, out)` | Eseguita internamente in step 6 con parsing coerente per tutti i canali | Formato della cronologia fornita a `genera_risposta_async` può divergere |
| **Pre-fetch Semaforo Prenotazioni** | Estrazione date da testo corrente e fallback su ultimi 4 messaggi con loop manuale | Eseguita internamente in step 7 con parsing date e semaforo giorno | Date analizzate e slot formattati possono differire tra WhatsApp e Simulatore |
| **Guardrail & Validazione** | `valida_risposta` + `applica_guardrail` + logging manuale `guardrail_block` | Integrato in step 9 con audit strutturato e metadati completi | Azioni di correzione/blocco guardrail non sincronizzate |
| **LLM Routing & Cost Governance** | Chiamata `route_llm` + calcolo metriche reali con stima costo eur | Integrato in step 10 con supporto unificato a `is_simulation` | Metadati di costo e token accounting calcolati con formule diverse |
| **Strategia Verticale & Creazione Booking** | Invocazione `get_vertical_strategy` + `create_booking` con slot_lock | Integrato in step 11 con branch di simulazione (read-only) vs reale | Rischio doppio booking o divergenza nella gestione di `SlotPienoError` |
| **Salvataggio FAQ Cache** | Salva risposta se non bloccata da guardrail e non richiede umano | Integrato in step 12 con validazione identica | Risposte salvate in cache con embedding disallineati |

**Soluzione Fase 4**: La promozione di `USE_CONVERSATION_ORCHESTRATOR=true` come default e l'isolamento del blocco legacy in un adapter dedicato (`LegacyInboundPipeline`) garantisce che **WhatsApp, Instagram e il Simulatore condividano al 100% lo stesso identico percorso cognitivo ed esecutivo**.

---

## Matrice delle Invarianti di Sicurezza (Fase 4)

Tutte le 11 Invarianti Non Negoziabili definite in `AGENTS.md` sono formalmente preservate:

| Invariante | Minaccia durante il Refactoring | Meccanismo di Tutela / Come viene preservata | Verifica Automatica |
|---|---|---|---|
| **1. Tenant Isolation** | Perdita o disallineamento di `organization_id` tra polling worker, pipeline inbound e channel adapters | `msg["organization_id"]` è la radice immutabile passata a ogni metodo di servizio, query repository e adapter di canale. Nessuna operazione viene eseguita senza `org_id` vincolato | `scripts/check_tenant_scoping.py` su tutti i nuovi moduli in `src/core/inbound/` e `src/core/workers/` |
| **2. Data Scope** | Query nel worker che omettono lo scope organizzazione o usano `system_scope` impropriamente | Solo il loop di polling globale usa `@system_scope("worker queue: claim globale SKIP LOCKED")`. Qualsiasi operazione successiva (`claim_message_and_check_quota`, consent, booking, dedup) usa connessioni tenant-scoped | AST check su `src/core/workers/` e `src/core/inbound/` |
| **3. Webhook Latency** | Esecuzione di logica worker o chiamate sincrone all'interno dei webhook Meta/Instagram | I webhook rimangono rigorosamente asincroni: salvano il payload grezzo su `messages` (status `received_pending_ai`) e restituiscono HTTP 200 entro 200ms. Il worker gira in background disaccoppiato | Test `tests/whatsapp/test_webhook.py` e `tests/unit/api/` |
| **4. Idempotency Everywhere (SEC-001, SEC-002)** | Raddoppio invio messaggi a Meta o double-booking in caso di crash worker o retry di rete | 1) `create_booking` riceve `source_message_id=msg["id"]` con clausola `ON CONFLICT (organization_id, source_message_id) DO NOTHING`.<br>2) Invio a Meta precede la marcatura handled (Send-then-mark), con cache di deduplicazione outbound `outbound_dedup` che impedisce reinvii multipli | Test suite `test_inbound_secondary_flows_p0.py` e test dedicati unitari |
| **5. No Direct Privileged AI Actions** | LLM che genera direttamente mutazioni nel DB o crea prenotazioni non validate | `ConversationOrchestrator` estrae la proposta di prenotazione come struttura non privilegiata (`prenotazione`); la persistenza su DB avviene esclusivamente attraverso `BookingService.create_booking` con lock consultivo su fascia e verifica capienza | Test orchestrator parity e unit test `BookingService` |
| **6. Fail-Closed Opt-Out** | Mancato blocco o invio di risposte AI a contatti che hanno revocato il consenso | `check_opt_out` viene eseguito come Step 2 prima di qualsiasi chiamata AI. Se positivo: 1) registra evento di consenso, 2) finalizza subito senza side-effect verso Meta, 3) logga security audit. Fail-closed: nessun messaggio esce mai | Test `test_opt_out_skips_fast_path` e test dedicati |
| **7. Guardrail Pipeline** | Aggiramento dei guardrail nella pipeline estratta | La pipeline inbound delega a `ConversationOrchestrator` che esegue la validazione rigorosa dei guardrail (hallucination check, price consistency, jailbreak filter) prima di restituire il testo | Test guardrails processor parity |
| **8. Billing & Cost Governance (BILL-001)** | Esecuzione di chiamate LLM per tenant sospesi, fuori budget o senza quota | 1) Step 1 esegue `claim_message_and_check_quota` che blocca atomicamente i messaggi oltre `messages_limit`.<br>2) Step 6 blocca l'AI per tenant sospesi (`is_org_suspended`).<br>3) `route_llm` monitora `remaining_budget_ratio` e degrada o blocca i modelli costosi | Test `test_quota_exceeded_meta_failure_does_not_mark_replied` e test billing hard-cap |
| **9. Observability & Tracing** | Perdita di correlazione nei log del worker | Ogni operazione del worker logga con `org_id`, `message_id`, `conversation_id`. La pipeline propaga questi metadati a ogni evento di usage e audit log | Test log correlation |
| **10. Secrets Management** | Esposizione di token Meta o chiavi di crittografia nei worker logs o nelle eccezioni | I token WABA e access token Instagram vengono decifrati in memoria solo al momento della chiamata di rete da `load_tenant_config` e `load_instagram_config` e non sono mai inclusi nei messaggi di log o eccezioni | Verifica statica e test unitari adapter |
| **11. Human Escalation** | Perdita di notifiche o mancata transizione di ticket su richiesta operatore o errore AI | Se l'AI o l'utente richiede operatore: 1) `escalate_to_human` aggiorna lo stato su DB, 2) `enqueue_escalation` inserisce l'alert email, 3) viene inviato il messaggio di attesa standard, 4) il messaggio viene finalizzato con status `escalated` | Test `test_escalation_when_ai_requires_human` |

---

## Analisi dei Rischi e Strategia di Rollback

### Matrice dei Rischi

| Rischio | Probabilità | Impatto | Mitigazione Preventiva | Procedura di Rollback |
|---|---|---|---|---|
| **R1. Rottura dei test esistenti di InboundProcessor dovuta a mocking interno** | Alta | Alto | `InboundProcessor` mantiene i metodi `_send_ai_reply`, `_finalize_message`, `_process_one`, `_handle_feedback_emoji` come facade. I test che usano `patch.object(processor, "_send_ai_reply")` intercettano la chiamata prima del dispatch | Ripristino del commit isolato; le facade preservano la signature esatta |
| **R2. Regressione nel routing multicanale (WhatsApp vs Instagram)** | Media | Alto | `InboundProcessingService` usa `ChannelOutboundPort` per astrarre la consegna del canale. Test dedicati verificano che messaggi con `canale="instagram"` vadano all'adapter Instagram e `canale="whatsapp"` all'adapter WhatsApp | Test suite `TestInstagramDispatch` eseguita a ogni gate |
| **R3. Race condition o doppio invio su retry di messaggi non finalizzati** | Media | Critico | Risolto da SEC-002: `save_outbound_dedup` salva la risposta generata nel DB *prima* dell'invio. Se il worker crasha durante l'invio e re-clama il messaggio, lo Step 9 (`get_outbound_dedup`) riutilizza la risposta salvata invece di reinvocare l'LLM | Revert del componente outbound |
| **R4. Timeout o deadlock nell'acquisizione del lock di slot su Booking** | Bassa | Medio | `slot_lock` in `BookingRepository` usa `pg_advisory_xact_lock` legato alla transazione corrente con timeout deterministico. Fallback trasparente `nullcontext` nei test in-memory | Test di concorrenza lock |
| **R5. Discrepanza di comportamento tra Orchestrator e Legacy** | Bassa | Medio | Shadow mode già implementato in Phase 2 (`SHADOW_ORCHESTRATOR=true`). `USE_CONVERSATION_ORCHESTRATOR` mantiene kill-switch via variabile d'ambiente | Impostare `USE_CONVERSATION_ORCHESTRATOR=false` per ripristinare il branch legacy istantaneamente senza redeploy |

### Ciclo di Vita del Feature Flag `USE_CONVERSATION_ORCHESTRATOR`
1. **Stato iniziale (Fase 2)**: Default `False`, attivabile con `USE_CONVERSATION_ORCHESTRATOR=true`.
2. **Promozione in Fase 4**: Default passa a **`True`** in `AppConfig` e `InboundProcessor`. La logica legacy viene estratta in `LegacyInboundPipeline`.
3. **Kill-Switch di emergenza**: È sufficiente impostare l'environment variable `USE_CONVERSATION_ORCHESTRATOR=false` per forzare l'esecuzione della pipeline legacy.
4. **Criterio esplicito di uscita (Sunset)**: Dopo 14 giorni di esecuzione in staging/produzione con 0 discrepanze registrate nei log di `[SHADOW_ORCHESTRATOR]`, un commit dedicato rimuoverà definitivamente `LegacyInboundPipeline` e il flag, eliminando 270 righe di debito tecnico.

---

## Piano Atomico dei Task di Implementazione

### Task 0: Pre-flight Snapshot e Baseline di Verifica
- [ ] Obiettivo: Eseguire la suite di test unitari completa (167 test), verificare l'assenza di errori di sintassi e salvare lo snapshot di baseline.
- [ ] Comando: `& "C:\Program Files\Python312\python.exe" -m pytest tests/unit/ -q` -> Attesi 167 passati.
- [ ] Verificare `scripts/check_tenant_scoping.py` -> Atteso OK.

### Task 1: Creazione dei Channel Outbound Adapters (`src/core/channels/`)
- [ ] Obiettivo: Isolare la logica di invio messaggi e formattazione outbound per WhatsApp e Instagram in adapter dedicati conformi a `ChannelOutboundPort`.
- [ ] File da creare:
  - `src/core/channels/__init__.py`
  - `src/core/channels/base.py`: definizione del protocollo `ChannelOutboundPort` e dataclass `OutboundSendResult`.
  - `src/core/channels/whatsapp_adapter.py`: `WhatsAppOutboundAdapter` (incapsula `send_whatsapp_message`, gestione `to_number`, disclosure formatting).
  - `src/core/channels/instagram_adapter.py`: `InstagramOutboundAdapter` (incapsula `load_instagram_config`, `InstagramService.send_instagram_message`).
- [ ] File di test: `tests/unit/test_channel_outbound_adapters.py`.
- [ ] Gate 1: `py_compile` sui nuovi moduli.
- [ ] Gate 2: Test unitari dedicati verdi con mock di `WhatsAppService` e `InstagramService`.

### Task 2: Creazione di `InboundProcessingService` e Disaccoppiamento della Pipeline Applicativa
- [ ] Obiettivo: Estrarre la logica di business dei 12 step da `_process_one` in un servizio applicativo puro in `src/core/inbound/service.py`.
- [ ] File da creare:
  - `src/core/inbound/__init__.py`
  - `src/core/inbound/models.py`: dataclass per il contesto di elaborazione messaggio (`InboundMessageContext`, `ProcessingOutcome`).
  - `src/core/inbound/service.py`: `InboundProcessingService` con i 12 step lineari:
    1. Quota & claim check
    2. Opt-out fail-closed
    3. Human handoff request
    4. Feedback emoji
    5. Booking reminder reply
    6. Organization suspension check
    7. Operator claimed ticket check
    8. Fast-path match
    9. Outbound dedup check
    10. Cognitive orchestration (`ConversationOrchestrator` default o `LegacyInboundPipeline` fallback)
    11. Disclosure decoration
    12. Channel dispatch & message finalization
  - `src/core/inbound/legacy_pipeline.py`: estrazione isolata delle ~270 righe del legacy branch per isolamento e deprecazione controllata.
- [ ] File di test: `tests/unit/test_inbound_processing_service.py`.
- [ ] Gate 1: `py_compile` su `src/core/inbound/*.py`.
- [ ] Gate 2: Test unitari dedicati della pipeline con tutti i 12 step coperti da fixture isolate.

### Task 3: Disaccoppiamento del Worker (`InboundWorker`) e Facade di Retrocompatibilità
- [ ] Obiettivo: Creare lo snello `InboundWorker` dedicato al polling e trasformare `InboundProcessor` in una facciata di retrocompatibilità al 100% che preservi tutti i mock dei test storici.
- [ ] File da creare:
  - `src/core/workers/__init__.py`
  - `src/core/workers/inbound_worker.py`: `InboundWorker` (gestisce `reap_stale_claims`, `claim_inbound_messages`, ciclo di batch, `_heartbeat_loop`).
- [ ] File da aggiornare:
  - `src/whatsapp/inbound_processor.py`: integra i nuovi componenti mantenendo esposti tutti i metodi e attributi usati dai test (`_process_one`, `_send_ai_reply`, `_finalize_message`, `_handle_feedback_emoji`, `use_orchestrator`, `shadow_orchestrator`).
  - `run_inbound_processor.py`: continua a istanziare `InboundProcessor` o `InboundWorker` senza alcuna rottura di runtime.
- [ ] File di test: `tests/unit/test_inbound_processor_facade.py`.
- [ ] Gate 1: `py_compile` su `src/whatsapp/inbound_processor.py` e `src/core/workers/*.py`.
- [ ] Gate 2: Esecuzione di `tests/unit/test_inbound_processor_orchestrator.py` (deve passare 100%).

### Task 4: Iniezione dei Repository Specializzati nei Servizi di Dominio (`src/core/`)
- [ ] Obiettivo: Sostituire le dipendenze dirette da `CoreRepository` e `WhatsAppRepository` con i repository specializzati della Fase 1 nei servizi di dominio.
- [ ] Servizi target:
  - `src/core/bookings/service.py`: accettare `BookingRepository` e `OrganizationRepository` (tramite duck-typing o istanza diretta dei repository specializzati).
  - `src/core/notifications/email_service.py`: usare `OrganizationRepository(pool)` invece di `CoreRepository(pool)` a riga 58.
  - `src/core/scheduler.py`: utilizzare i repository specifici (`BookingRepository`, `OrganizationRepository`) per i job schedulati.
- [ ] Gate 1: `py_compile` su tutti i file modificati.
- [ ] Gate 2: `tests/unit/` per booking, email_service e scheduler.

### Task 5: Defaulting di `USE_CONVERSATION_ORCHESTRATOR=true` e Verifica Rigorosa delle Invarianti (P0-1, P0-2, BILL-001)
- [ ] Obiettivo: Promuovere l'orchestratore a default di sistema, verificare l'idempotenza delle prenotazioni su retry e l'affidabilità di invio prima della finalizzazione.
- [ ] File da aggiornare:
  - `src/whatsapp/config.py`: `use_conversation_orchestrator: bool = True` di default in `AppConfig`.
  - `src/core/receptionist/conversation_orchestrator.py`: verifica che `source_message_id` sia sempre passato a `create_booking`.
- [ ] Test di verifica invarianti:
  - Verifica P0-1 (Idempotenza Booking): chiamata multipla a `create_booking` con stesso `source_message_id` non genera righe duplicate e non crasha.
  - Verifica P0-2 (Send-then-mark): simulazione errore di rete su WhatsApp o Instagram non marca il messaggio come `replied_at/handled`.
  - Verifica BILL-001 (Hard-cap Cost Governance): verifica che tenant con `messages_used_this_period >= messages_limit` vengano bloccati con stato `quota_exceeded`.
- [ ] Gate 1: `check_tenant_scoping.py` su tutta la codebase.
- [ ] Gate 2: Esecuzione completa di `tests/unit/` (tutti i 167+ test verdi).
- [ ] Gate 3: Aggiornamento del grafo di conoscenza con `graphify update .`.

---

## Cancelli di Verifica e Criteri di Accettazione

Ogni singolo step di implementazione deve soddisfare i seguenti 5 cancelli prima di essere considerato completato:

| Cancello | Descrizione | Comando di Verifica | Criterio di Superamento |
|---|---|---|---|
| **Gate 1** | Compilazione AST Python | `python -m py_compile <file_modificati>` | 0 errori di sintassi o import |
| **Gate 2** | Verifica Statica Tenant Scoping | `python scripts/check_tenant_scoping.py` | Esito: `TENANT SCOPING CHECK: OK` (0 leak o chiamate unscoped) |
| **Gate 3** | Parità della Pipeline Inbound | `pytest tests/unit/test_inbound_processor_orchestrator.py` | 100% test passati sia con flag `True` che `False` |
| **Gate 4** | Compatibilità Mock & Facade | `pytest tests/unit/test_channel_outbound_adapters.py tests/unit/test_inbound_processing_service.py` | Nuovi test unitari verdi senza bypass o regressioni |
| **Gate 5** | Regressione Completa Unit Test | `pytest tests/unit/ -q` | 167+ test passati, 0 failed, 0 broken contracts |

---

## Procedura di Rollback di Emergenza

In caso di fallimento o regressione inaspettata durante qualsiasi fase:
1. **Rollback del singolo task**: Ogni task è un commit isolato. In caso di fallimento di un Gate, si esegue `git checkout -- <file_toccati>` per tornare allo stato verificato del task precedente.
2. **Kill-Switch a Runtime per l'Orchestratore**: Se si riscontra un'anomalia in produzione, non è necessario alcun redeploy: basta impostare l'environment variable `USE_CONVERSATION_ORCHESTRATOR=false` per reindirizzare istantaneamente tutto il traffico sul branch legacy isolato in `LegacyInboundPipeline`.
3. **Nessun impatto sul Database**: Nessuna migrazione DDL o alterazione di schema viene introdotta in questa fase; i dati e la struttura rimangono al 100% stabili.
