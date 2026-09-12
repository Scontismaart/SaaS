# Phase 3: API Decomposition & Centralized Dependency Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decomporre in modo rigoroso, incrementale e verificabile il monolite `src/api/main.py` (~2015 righe) estraendo le route in router modulari sotto `src/api/routes/` e introducendo una gestione centralizzata e tipizzata delle dipendenze in `src/api/dependencies.py`, garantendo la separazione Clean Architecture (Presentation, Application, Domain, Infrastructure, Integrations), zero modifiche ai path HTTP e compatibilità assoluta con la suite di test esistente.

**Architecture:**
- **Presentation Layer (API)**: `src/api/routes/` ospita i router suddivisi per coesione di dominio:
  - `organization.py`: `/api/onboarding/*`, `/api/impostazioni/organizzazione`
  - `integrations.py`: `/api/integrazioni/*`, `/api/audit`
  - `dashboard.py`: `/api/dashboard/*`, `/api/report/*`
  - `knowledge.py`: `/api/documenti/*`, `/api/conoscenza/*`, `/api/ui/summary`
  - `simulator.py`: `/api/messaggio`, `/api/recensione`
- **Application Layer (Use Cases)**: Orchestrazione (`ConversationOrchestrator`), `BookingService`, `WeeklyReport`, `Onboarding`
- **Infrastructure / Data Access**: Centralizzato tramite `src/api/dependencies.py` (`get_repo`, `get_pool`, `get_booking_service`, `get_orchestrator`) sostituendo le chiamate ad-hoc `getattr(request.app.state, ...)`
- **Shared Route Helpers**: `src/api/routes/common.py` per snapshot billing, accounting AI, verifica feature/piani e wrapper trasparenti per i mock di test (`vettorizza`, `estrai_da_url`, `genera_risposta_recensione`).
- **Main App**: `src/api/main.py` diventa uno snello application entrypoint (~400 righe) responsabile esclusivamente di: Lifespan, Middleware (CORS, Security Headers, Trace ID, Rate Limit, CSRF), mount dei router, `/api/health` e static landing pages.

**Tech Stack:** FastAPI, Pydantic v2, asyncpg, pytest, unittest.mock, httpx.

**Spec:** Refactoring architetturale SaaS - Fase 3 (Decomposizione delle API Route e Dependency Injection).

---

## Matrice delle Invarianti di Sicurezza (Fase 3)

| Invariante | Minaccia durante il Refactoring | Meccanismo di Tutela / Come viene preservata | Verifica Automatica |
|---|---|---|---|
| **1. Tenant Isolation** | Omissione o allentamento di `require_ruolo(...)` o `get_organization_context` durante lo spostamento delle route da `main.py` ai router | Ogni endpoint spostato mantiene ESATTAMENTE la stessa dipendenza di autenticazione e autorizzazione. Nessun endpoint riceve l'organization_id come parametro client | `scripts/audit_route_contracts.py` confronta la lista di ruoli richiesti prima/dopo. `scripts/check_tenant_scoping.py` analizza l'AST |
| **2. Data Scope** | Query SQL dirette in `dashboard.py` o `integrations.py` senza clausola `WHERE organization_id = $1::uuid` | Il CTE `_DASHBOARD_EVENTI_CTE` e le query di integrazioni mantengono il binding obbligatorio all'`organization_id` estratto dal JWT | AST check su `scripts/check_tenant_scoping.py` (target allargati a `src/api/routes/`) |
| **3. Webhook Latency** | Modifica involontaria del montaggio o middleware dei webhook Meta/Instagram/Stripe | I webhook rimangono montati con route dedicate escluse dal rate limiting applicativo (`/webhooks/whatsapp`, `/webhooks/instagram`, `/api/billing/webhook`) | Test di integrazione webhook + esame dei path in `rate_limit_middleware` |
| **4. Idempotency Everywhere** | Raddoppio di elaborazione messaggi o report settimanali durante il disaccoppiamento | Gli endpoint come `/api/report/settimanale` mantengono il parametro `forza: bool = False` e il check su DB; i messaggi simulatore mantengono il namespace `org_id:conv_id` | Test unitario idempotenza report + simulator conversation store |
| **5. No Direct Privileged AI Actions** | Output LLM che invoca mutazioni database senza passare per la validazione | L'endpoint `/api/messaggio` in `simulator.py` delega a `ConversationOrchestrator` con `is_simulation=True`. Nessuna prenotazione reale viene scritta su DB per tenant autenticati; solo per demo locale anonima | `tests/unit/test_api_messaggio_orchestrator.py` |
| **6. Fail-Closed Opt-Out** | Omissione di verifiche di consenso marketing/messaggistica | Non toccato (gestito da InboundProcessor / WhatsAppService); l'API non bypassa lo stato di consenso | Test suite whatsapp regression |
| **7. Guardrail Pipeline** | Aggiramento dei guardrail nella risposta del simulatore | `ConversationOrchestrator` esegue la guardrail pipeline completa anche per le chiamate simulatore | Parity test orchestrator |
| **8. Billing & Cost Governance** | Chiamate AI non tracciate o mancato blocco delle feature fuori piano | `_piano_blocca_feature` (in `common.py`) blocca RAG e recensioni se il piano non le include. `_record_ai_usage` traccia usage e budget ratio su ogni chiamata AI | Test unitari su `common.py` e route knowledge/simulator |
| **9. Observability & Tracing** | Perdita di `trace_id` o log non correlati | `trace_id_middleware` rimane attivo in `main.py` e inietta `X-Trace-ID` su tutte le risposte dei router montati | Test middleware trace id |
| **10. Secrets Management** | Esposizione nei log o nelle risposte API di token Meta, WABA o Google | Gli endpoint `/api/integrazioni/stato` restituiscono solo booleani e ID non sensibili; `/api/integrazioni/test/{canale}` decifra il token in memoria con Fernet e non lo logga mai | Test unitari integrazioni con mock Fernet |
| **11. Human Escalation** | Perdita della notifica o stato escalation nel simulatore o inbox | Il simulatore mappa fedelmente `out.richiede_umano` e `out.motivo_richiesta_umano` nell'output | Test `test_api_messaggio_with_orchestrator` |
### Collocazione Architetturale dei Webhook (Meta, Instagram, Stripe) e Invariante 3

Una precisazione fondamentale: **i webhook NON risiedono direttamente in `src/api/main.py` e non fanno parte dei 5 router da estrarre perché sono GIÀ router dedicati e isolati per dominio**:
- **WhatsApp Webhook** (`/webhooks/whatsapp`): Definito in `src/whatsapp/router.py` via `create_whatsapp_router(app_config, wrepo)`. Montato a runtime nel `lifespan` di `main.py` perché richiede il database pool e i segreti Meta.
- **Instagram Webhook** (`/webhooks/instagram`): Definito in `src/instagram/router.py` via `create_instagram_router(...)`. Montato a runtime nel `lifespan` di `main.py`.
- **Stripe Webhook** (`/api/billing/webhook`): Definito in `src/core/billing/routes.py` all'interno di `billing_router`. Montato staticamente in `main.py` via `app.include_router(billing_router)`.

**Come viene preservata l'Invariante 3 (Webhook Latency)**:
1. Nessuno dei file webhook viene modificato durante la Fase 3.
2. Il montaggio nel `lifespan` di `main.py` e l'inclusione di `billing_router` rimangono intatti al 100%.
3. In `main.py`, il middleware di rate limiting (`rate_limit_middleware`) preserva rigorosamente l'esclusione a monte a riga 378:
   ```python
   if request.url.path in ("/api/health", "/webhooks/whatsapp", "/webhooks/instagram", "/api/billing/webhook"):
       return await call_next(request)
   ```
   garantendo che nessun webhook sia mai rallentato o bloccato dal rate limiting applicativo, assicurando l'ACK immediato (HTTP 200) a Meta e Stripe.

---

## Analisi dei Rischi e Strategia di Rollback

### Matrice dei Rischi

| Rischio | Probabilità | Impatto | Mitigazione Preventiva | Procedura di Rollback |
|---|---|---|---|---|
| **R1. Omissione o allentamento di autorizzazioni (Auth Drift)** | Media | Critico | Task 0 estrae il baseline dei contratti (`docs/route_contracts_baseline.json`). Lo script `audit_route_contracts.py` blocca la migrazione se una rotta perde ruoli o cambia path | Revert immediato del commit del router specifico |
| **R2. Silent Mock Bypass nei test legacy** | Alta | Alto | I test patchano `src.api.main.vettorizza`. Se `knowledge.py` importa da modulo core, il mock non intercetta la chiamata. Mitigato con re-export esplicito su `main.py` e helper di risoluzione dinamica | Test dedicato `test_mock_compatibility.py` che valida l'intercettazione reale prima di procedere |
| **R3. Circular Imports** | Media | Medio | `src/api/dependencies.py` non importa `main.py`. I router importano solo da `dependencies.py` e `common.py`, mai da `main.py`. `main.py` importa i router. Gerarchia DAG stretta: `dependencies` -> `routes` -> `main` | Verifica automatica di import con `py_compile` e caricamento modulo isolato |
| **R4. Rottura Demo Mode / Fallback senza DB** | Bassa | Medio | `_storico_eventi` e `_prossimo_id` sono centralizzati in `src/api/routes/common.py` come singleton condiviso tra `simulator.py`, `dashboard.py` e scheduler | Test unitario con DATABASE_URL vuoto |
| **R5. Big-Bang Failure su 2000 righe** | Alta | Critico | Rifiuto categorico del refactoring "in un sol colpo". Estrazione router per router (1 alla volta), ciascuno con proprio test e gate di verifica | Reversibilità atomica a livello di singolo router via git |

### Strategia di Rollback Incrementale
1. **Checkpoint Git per ogni router**: Ogni task si conclude con un commit isolato e atomico (es. `refactor(api): extract organization router`).
2. **Branch di sicurezza**: Tutta la Fase 3 opera su commit verificati. Se un router non passa i cancelli di verifica (Gate 1-5), il singolo file viene scartato con `git checkout` e `main.py` ripristinato allo stato del task precedente.
3. **Nessun impatto a caldo su produzione**: I test e i gate vengono eseguiti ad ogni singolo step prima di procedere al router successivo.

---

## Dettaglio Tecnico: Rischio Mock e Risoluzione dei Simboli

### Il Problema
Nella codebase esistente, decine di test storici contengono:
```python
with patch("src.api.main.vettorizza", return_value=[[0.1] * 384]):
    resp = await async_client.post("/api/documenti/carica", ...)
```
Se `src/api/routes/knowledge.py` eseguisse:
```python
from src.core.documenti.embeddings import vettorizza
```
All'interno di `knowledge.py`, il puntatore `vettorizza` punterebbe all'oggetto originale. La chiamata `patch("src.api.main.vettorizza")` modificherebbe esclusivamente l'attributo nel modulo `src.api.main`. Di conseguenza, `knowledge.py` invocherebbe la funzione reale (tentando di connettersi ai modelli o fallendo), generando un **Silent Mock Bypass**.

### La Soluzione Deterministica
1. **Re-export esplicito (Backward Compatibility Facade)** in `src/api/main.py`:
   ```python
   from src.core.documenti.embeddings import vettorizza
   from src.core.documenti.web_extractor import estrai_da_url
   from src.core.crew_runner_review import genera_risposta_recensione
   ```
2. **Dynamic Resolver** in `src/api/routes/common.py`:
   ```python
   import sys

   def resolve_vettorizza():
       main_mod = sys.modules.get("src.api.main")
       if main_mod and hasattr(main_mod, "vettorizza"):
           return getattr(main_mod, "vettorizza")
       from src.core.documenti.embeddings import vettorizza
       return vettorizza
   ```
   Questa implementazione:
   - È non-circolare (non importa `main.py` a top-level, ma controlla `sys.modules` a runtime solo se già caricato).
   - Intercetta immediatamente qualsiasi mock impostato da `unittest.mock.patch("src.api.main.vettorizza")`.
   - Se `main` non è nel dizionario dei moduli, usa direttamente l'implementazione core.
3. **Validazione con test dedicato**: Il Task 1 include `tests/unit/api/test_mock_compatibility.py` che dimostra matematicamente che `patch("src.api.main.vettorizza")` intercetta l'esecuzione del router.

---

## Ordine di Scomposizione Incrementale

L'ordine di scomposizione è rigorosamente pianificato per complessità e rischio crescenti:

```text
Task 0: Baseline Contratti Route (audit_route_contracts.py)
  ↓
Task 1: Fondamenta (src/api/dependencies.py & src/api/routes/common.py)
  ↓
Task 2: Router 1 - organization.py (Onboarding, Profilo, Timezone - zero AI)
  ↓
Task 3: Router 2 - integrations.py (Stato, Test Canali, Audit Log - zero AI)
  ↓
Task 4: Router 3 - dashboard.py (CTE unificato, Prioritari, Reportistica)
  ↓
Task 5: Router 4 - knowledge.py (FAQ, RAG, File Upload, Web Scraper - RAG & Embeddings)
  ↓
Task 6: Router 5 - simulator.py (/api/messaggio con ConversationOrchestrator, /api/recensione)
  ↓
Task 7: Snellimento src/api/main.py e Re-Export Facade
  ↓
Task 8: Validazione Finale & Knowledge Graph Update
```

---

## Cancelli di Verifica Espliciti per Task (Gates)

Per ogni singolo task, devono essere superati TUTTI i seguenti cancelli prima di considerare il task completato:
* **Gate 1 (Sintassi & Compilazione)**: `& "C:\Program Files\Python312\python.exe" -m py_compile <file_modificati>` senza errori.
* **Gate 2 (Route Contract Parity)**: `& "C:\Program Files\Python312\python.exe" scripts/audit_route_contracts.py verify`
  - Nessuna rotta eliminata o duplicata.
  - Nessuna guardia di ruolo allentata o rimossa.
  - Nessun modello di risposta o richiesta alterato.
* **Gate 3 (AST Tenant Scoping)**: `& "C:\Program Files\Python312\python.exe" scripts/check_tenant_scoping.py` (Exit code 0).
* **Gate 4 (Test Unitari Specifici)**: Esecuzione del test dedicato al router con esito 100% PASS.
* **Gate 5 (Regressione Completa)**: `& "C:\Program Files\Python312\python.exe" -m pytest tests/unit/ -v` (126+ test passati in <35s).

---

## Task Decomposition

### Task 0: Baseline Contratti Route & Script di Audit Parità

**Files:**
- Create: `scripts/audit_route_contracts.py`
- Generate: `docs/route_contracts_baseline.json`

**Interfaces:**
- CLI:
  - `python scripts/audit_route_contracts.py dump docs/route_contracts_baseline.json` (cattura lo stato di `app.routes`)
  - `python scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json` (confronta `app.routes` attuale con il baseline e fallisce con exit code 1 se rileva differenze)

- [ ] **Step 1: Scrivere `scripts/audit_route_contracts.py`**
Estrae da `app.routes`:
- `path`: es. `/api/onboarding/profilo`
- `methods`: es. `["POST"]`
- `required_roles`: estratto da `dependant.dependencies` ispezionando la closure di `_check` (es. `["owner", "manager"]`)
- `response_model`: nome della classe o schema
- `endpoint_name`: nome della funzione handler

- [ ] **Step 2: Generare il baseline iniziale**
Run: `& "C:\Program Files\Python312\python.exe" scripts/audit_route_contracts.py dump docs/route_contracts_baseline.json`
Verificare che contenga esattamente i 34 endpoint `/api/*` attuali.

- [ ] **Step 3: Verificare il comando `verify`**
Run: `& "C:\Program Files\Python312\python.exe" scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
Expected: `ROUTE CONTRACT AUDIT: OK (0 drifts, 34 endpoints matched)`

---

### Task 1: `src/api/dependencies.py` & `src/api/routes/common.py` (DI & Shared Helpers)

**Files:**
- Create: `src/api/dependencies.py`
- Create: `src/api/routes/__init__.py`
- Create: `src/api/routes/common.py`
- Test: `tests/unit/api/test_dependencies.py`
- Test: `tests/unit/api/test_mock_compatibility.py`

**Interfaces:**
- Produces:
  - `src/api/dependencies.py`:
    - `get_repo(request: Request) -> CoreRepository`
    - `get_pool(request: Request) -> asyncpg.Pool`
    - `get_booking_service(request: Request) -> BookingService`
    - `get_orchestrator(request: Request) -> ConversationOrchestrator`
    - `get_current_org_id(user: dict = Depends(get_organization_context)) -> str`
    - Re-export di `require_ruolo`, `get_organization_context` da `src.core.auth.dependencies`
  - `src/api/routes/common.py`:
    - `audit_event(request: Request, user: dict, action: str, target_table: str | None = None, target_id: str | None = None, details: dict | None = None) -> None`
    - `get_billing_snapshot(repo, organization_id: str | None) -> dict | None`
    - `record_ai_usage(repo, organization_id: str | None, task_type: str, user_text: str, billing: dict | None, metadata: dict | None = None) -> None`
    - `check_feature_blocked_by_plan(repo, org_id: str | None, feature: str) -> str | None`
    - `get_shared_event_history() -> list[EventoDashboard]`
    - `next_event_id(tipo: str) -> str`
    - Dynamic mock resolvers: `resolve_vettorizza()`, `resolve_estrai_da_url()`, `resolve_genera_risposta_recensione()`

- [ ] **Step 1: Scrivere i test unitari per DI e risolutori mock**
`tests/unit/api/test_dependencies.py` e `tests/unit/api/test_mock_compatibility.py`
Dimostrare che `resolve_vettorizza()` restituisce il mock se `src.api.main.vettorizza` è patchato.

- [ ] **Step 2: Eseguire i test (FAIL atteso)**
Run: `& "C:\Program Files\Python312\python.exe" -m pytest tests/unit/api/ -v`

- [ ] **Step 3: Implementare `src/api/dependencies.py` e `src/api/routes/common.py`**

- [ ] **Step 4: Eseguire i test (PASS atteso) e verificare tutti i Gate**
Run: `& "C:\Program Files\Python312\python.exe" -m pytest tests/unit/api/ -v`

---

### Task 2: Router 1 - `src/api/routes/organization.py`

**Files:**
- Create: `src/api/routes/organization.py`
- Modify: `src/api/main.py` (rimozione endpoint locali e mount del router)
- Test: `tests/unit/api/test_organization_routes.py`

**Endpoints Migrati:**
- `GET /api/onboarding/verticali` (ruolo: owner, manager, staff)
- `GET /api/onboarding/profilo` (ruolo: owner, manager, staff)
- `POST /api/onboarding/profilo` (ruolo: owner, manager)
- `POST /api/onboarding/preview` (ruolo: owner, manager, staff)
- `GET /api/impostazioni/organizzazione` (ruolo: owner, manager, staff)
- `PUT /api/impostazioni/organizzazione` (ruolo: owner, manager)

- [ ] **Step 1: Scrivere `tests/unit/api/test_organization_routes.py`**
- [ ] **Step 2: Creare `src/api/routes/organization.py`**
- [ ] **Step 3: Rimuovere gli endpoint da `src/api/main.py` e montare `organization.router`**
- [ ] **Step 4: Eseguire Gates 1-5**
  - Gate 1: `py_compile`
  - Gate 2: `python scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
  - Gate 3: `python scripts/check_tenant_scoping.py`
  - Gate 4: `pytest tests/unit/api/test_organization_routes.py`
  - Gate 5: `pytest tests/unit/`

---

### Task 3: Router 2 - `src/api/routes/integrations.py`

**Files:**
- Create: `src/api/routes/integrations.py`
- Modify: `src/api/main.py` (rimozione endpoint locali e mount del router)
- Test: `tests/unit/api/test_integrations_routes.py`

**Endpoints Migrati:**
- `GET /api/integrazioni/stato` (ruolo: owner, manager, staff)
- `POST /api/integrazioni/test/{canale}` (ruolo: owner, manager, staff)
- `GET /api/audit` (ruolo: owner, manager, staff)

- [ ] **Step 1: Scrivere `tests/unit/api/test_integrations_routes.py`**
- [ ] **Step 2: Creare `src/api/routes/integrations.py`**
- [ ] **Step 3: Rimuovere gli endpoint da `src/api/main.py` e montare `integrations.router`**
- [ ] **Step 4: Eseguire Gates 1-5**
  - Gate 1: `py_compile`
  - Gate 2: `python scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
  - Gate 3: `python scripts/check_tenant_scoping.py`
  - Gate 4: `pytest tests/unit/api/test_integrations_routes.py`
  - Gate 5: `pytest tests/unit/`

---

### Task 4: Router 3 - `src/api/routes/dashboard.py`

**Files:**
- Create: `src/api/routes/dashboard.py`
- Modify: `src/api/main.py` (rimozione CTE, helper fetch, endpoint locali e mount del router)
- Test: `tests/unit/api/test_dashboard_routes.py`

**Endpoints Migrati:**
- `GET /api/dashboard` (ruolo: owner, manager, staff)
- `GET /api/dashboard/prioritari` (ruolo: owner, manager, staff)
- `GET /api/report` (ruolo: owner, manager, staff)
- `GET /api/report/stato` (ruolo: owner, manager, staff)
- `GET /api/report/settimanale` (ruolo: owner, manager)
- `GET /api/report/csv` (ruolo: owner, manager)

- [ ] **Step 1: Scrivere `tests/unit/api/test_dashboard_routes.py`**
- [ ] **Step 2: Creare `src/api/routes/dashboard.py`**
Trasferire `_DASHBOARD_EVENTI_CTE`, `recupera_eventi_dashboard`, `recupera_eventi_prioritari`.
- [ ] **Step 3: Rimuovere gli endpoint da `src/api/main.py` e montare `dashboard.router`**
- [ ] **Step 4: Eseguire Gates 1-5**
  - Gate 1: `py_compile`
  - Gate 2: `python scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
  - Gate 3: `python scripts/check_tenant_scoping.py`
  - Gate 4: `pytest tests/unit/api/test_dashboard_routes.py`
  - Gate 5: `pytest tests/unit/`

---

### Task 5: Router 4 - `src/api/routes/knowledge.py`

**Files:**
- Create: `src/api/routes/knowledge.py`
- Modify: `src/api/main.py` (rimozione endpoint locali e mount del router)
- Test: `tests/unit/api/test_knowledge_routes.py`

**Endpoints Migrati:**
- `POST /api/documenti/chiedi` (ruolo: owner, manager, staff)
- `GET /api/documenti/conteggio` (ruolo: owner, manager, staff)
- `GET /api/documenti/elenco` (ruolo: owner, manager, staff)
- `PATCH /api/documenti/{documento_id}/toggle` (ruolo: owner, manager)
- `GET /api/ui/summary` (ruolo: owner, manager, staff)
- `POST /api/conoscenza/faq` (ruolo: owner, manager)
- `PUT /api/conoscenza/faq/{faq_id}` (ruolo: owner, manager)
- `DELETE /api/conoscenza/faq/{faq_id}` (ruolo: owner, manager)
- `POST /api/conoscenza/web` (ruolo: owner, manager)
- `GET /api/conoscenza/dati-struttura` (ruolo: owner, manager, staff)
- `PUT /api/conoscenza/dati-struttura` (ruolo: owner, manager)
- `GET /api/conoscenza/conflitti` (ruolo: owner, manager, staff)
- `GET /api/conoscenza/summary` (ruolo: owner, manager, staff)
- `POST /api/documenti/carica` (ruolo: owner, manager)
- `POST /api/documenti/carica-file` (ruolo: owner, manager)
- `DELETE /api/documenti/{documento_id}` (ruolo: owner, manager)

- [ ] **Step 1: Scrivere `tests/unit/api/test_knowledge_routes.py`**
- [ ] **Step 2: Creare `src/api/routes/knowledge.py`** usando `resolve_vettorizza()` e `resolve_estrai_da_url()`
- [ ] **Step 3: Rimuovere gli endpoint da `src/api/main.py` e montare `knowledge.router`**
- [ ] **Step 4: Eseguire Gates 1-5**
  - Gate 1: `py_compile`
  - Gate 2: `python scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
  - Gate 3: `python scripts/check_tenant_scoping.py`
  - Gate 4: `pytest tests/unit/api/test_knowledge_routes.py`
  - Gate 5: `pytest tests/unit/`

---

### Task 6: Router 5 - `src/api/routes/simulator.py`

**Files:**
- Create: `src/api/routes/simulator.py`
- Modify: `src/api/main.py` (rimozione endpoint locali e mount del router)
- Test: `tests/unit/api/test_simulator_routes.py`

**Endpoints Migrati:**
- `POST /api/messaggio` (pubblico/demo con auth facoltativa - delega a `ConversationOrchestrator` con `is_simulation=True`)
- `POST /api/recensione` (ruolo: owner, manager, staff)

- [ ] **Step 1: Scrivere `tests/unit/api/test_simulator_routes.py`**
- [ ] **Step 2: Creare `src/api/routes/simulator.py`**
- [ ] **Step 3: Rimuovere gli endpoint da `src/api/main.py` e montare `simulator.router`**
- [ ] **Step 4: Eseguire Gates 1-5**
  - Gate 1: `py_compile`
  - Gate 2: `python scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
  - Gate 3: `python scripts/check_tenant_scoping.py`
  - Gate 4: `pytest tests/unit/api/test_simulator_routes.py tests/unit/test_api_messaggio_orchestrator.py`
  - Gate 5: `pytest tests/unit/`

---

### Task 7: Pulizia Finale di `src/api/main.py` e Re-Export Facade

**Files:**
- Modify: `src/api/main.py`
- Test: `tests/unit/test_api_messaggio_orchestrator.py` + full unit suite

**Modifiche:**
- Mantenere esclusivamente:
  - Lifespan (`app.state.pool`, `app.state.repo`, `app.state.orchestrator`, `app.state.booking_service`, webhook runtime includes)
  - Middleware (CORS, Security Headers, Trace ID, Rate Limit, CSRF)
  - Mount dei router (Billing, GDPR, Inbox, Bookings, Calendar, Reviews, Accounts, Auth, Register, Organization, Integrations, Dashboard, Knowledge, Simulator)
  - Endpoint `/api/health`
  - Static files & landing page routes
  - Re-export trasparenti per backward compatibility test: `vettorizza`, `estrai_da_url`, `genera_risposta_recensione`
- Riduzione righe: da ~2015 a ~400 righe pulite e leggibili.

- [ ] **Step 1: Pulire le dipendenze inutilizzate da `src/api/main.py`**
- [ ] **Step 2: Eseguire Gates 1-5**

---

### Task 8: Validazione Finale, Verifica AST Scoping & Knowledge Graph Update

**Files:**
- Verify: Full test suite (`tests/unit/`)
- Verify: `scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
- Verify: `scripts/check_tenant_scoping.py`
- Update: `graphify update .`

- [ ] **Step 1: Eseguire la verifica dei contratti di tutte le route**
Run: `& "C:\Program Files\Python312\python.exe" scripts/audit_route_contracts.py verify docs/route_contracts_baseline.json`
Expected: `ROUTE CONTRACT AUDIT: OK (0 drifts, 34 endpoints matched)`

- [ ] **Step 2: Eseguire il check AST di tenant scoping**
Run: `& "C:\Program Files\Python312\python.exe" scripts/check_tenant_scoping.py`
Expected: `TENANT SCOPING CHECK: OK` (0 violazioni)

- [ ] **Step 3: Eseguire l'intera suite di unit test**
Run: `& "C:\Program Files\Python312\python.exe" -m pytest tests/unit/ -v`
Expected: Tutti i test passano in ~30s.

- [ ] **Step 4: Aggiornare il knowledge graph**
Run: `& "C:\Program Files\Python312\python.exe" -m graphify update .`
