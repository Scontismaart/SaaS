# Tenant Isolation — Wrapper Strutturale + Check CI

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rendere impossibile (strutturalmente) eseguire query su tabelle tenant-scoped senza `organization_id`, con rete di sicurezza CI.

**Architecture:** mixin `TenantScopedRepository` con context manager `scoped_conn(organization_id)` (parametro obbligatorio, connessione "guarded" fail-closed) + decorator `@system_scope` per le eccezioni intenzionali + script AST-based `scripts/check_tenant_scoping.py` che condivide le stesse costanti del check runtime (unica tabella di verità). Il runtime valuta la stringa SQL FINALE (copre SQL dinamico); lo script AST è la rete statica con regola anti-tabella-interpolata.

**Tech Stack:** Python 3.12, asyncpg, FastAPI, pytest (asyncio_mode=auto), GitHub Actions.

## Global Constraints

- Invariant #1 (Tenant Isolation): nessuna query su tabelle tenant-scoped senza filtro `organization_id` esplicito.
- Fail-closed ovunque: org mancante → errore immediato (`MissingOrganizationIdError`/`TypeError`), statement senza filtro → `TenantScopeViolation`. Mai bypass silenzioso.
- `organization_id` è parametro POSIZIONALE OBBLIGATORIO senza default nei metodi migrati.
- Unica tabella di verità: `TENANT_SCOPED_TABLES` in `src/core/db/scoping.py`, importata dal check CI (nessuna duplicazione).
- Stile esistente: classi repository con `self.pool`, `async with self.pool.acquire() as conn`, SQL con placeholder `$n`. Nessun ORM, nessun query builder nuovo.
- Non rompere le chiamate esistenti: aggiornare le firme dei chiamanti dove richiesto (lista nel piano).
- Test su Postgres reale via `TEST_DB_DSN` (docker-compose.test.yml / PGPORT 55432 in locale).
- Commit per task, messaggi conventionali.
- Dopo l'ultima modifica al codice: `graphify update .` (regola AGENTS.md).

## Tabelle (tabella di verità)

- **TENANT_SCOPED_DIRECT** (in `TENANT_SCOPED_TABLES`): whatsapp_accounts, contacts, conversations, messages, whatsapp_templates, bookings, booking_settings, reviews, documents, document_chunks, email_configs, usage_events, event_log, faq_cache, message_feedback, instagram_accounts, google_calendar_credentials, google_business_credentials, weekly_report_log, onboarding_profiles, audit_log, organization_memberships, outbound_dedup
- **INDIRECT** (in `INDIRECT_SCOPED_TABLES`, escluse dal check — coperte da RLS + filtro sul padre): message_delivery_attempts, contact_consent_log
- **ROOT/INFRA escluse**: organizations (root, scope=PK id), processed_stripe_events, webhook_idempotency, oauth_nonces

---

## Task 1: Modulo `src/core/db/scoping.py` + unit test

**Files:**
- Create: `src/core/db/scoping.py`
- Create: `tests/core/test_scoping_unit.py`
- Modify: `src/whatsapp/repository.py` (classe `Repository`: eredita mixin)
- Modify: `src/core/db/repository.py` (classe `CoreRepository`: eredita mixin)
- Modify: `src/instagram/repository.py` (classe `InstagramRepository`: eredita mixin)

**Interfaces (Produces):**
- `TENANT_SCOPED_TABLES: frozenset[str]`, `INDIRECT_SCOPED_TABLES: frozenset[str]`
- `class MissingOrganizationIdError(TypeError)`
- `class TenantScopeViolation(RuntimeError)`
- `extract_tables(sql: str) -> set[str]` — regex `\b(?:from|join|into|update)\s+([a-zA-Z_][a-zA-Z0-9_]*)` case-insensitive
- `assert_org_scoped(sql: str) -> None` — raise `TenantScopeViolation` se `(extract_tables(sql) & TENANT_SCOPED_TABLES)` non vuoto e `"organization_id" not in sql`
- `class ScopedConnection` — proxy asyncpg con `fetch/fetchrow/fetchval/execute/executemany` che chiamano `assert_org_scoped` prima di delegare; `transaction()` delegata; `__getattr__` che rifiuta tutto il resto con `AttributeError` esplicativo
- `class TenantScopedRepository` — mixin con `scoped_conn(self, organization_id)` async context manager: `organization_id` posizionale senza default; `None` → `MissingOrganizationIdError`; conversione `uuid.UUID(str(organization_id))` fail-closed; yield `ScopedConnection(conn, org)`
- `def system_scope(reason: str)` — decorator che setta `fn.__system_scope__ = reason` (reason obbligatorio)

Unit test (nessun DB richiesto, mock conn):
- `assert_org_scoped` accetta `SELECT * FROM bookings WHERE organization_id = $1`
- `assert_org_scoped` rifiuta `SELECT * FROM bookings WHERE id = $1` → `TenantScopeViolation`
- `assert_org_scoped` NON flaggia tabelle infra (`webhook_idempotency`) né root (`organizations`)
- SQL costruito dinamicamente (`"SELECT * FROM " + var_tabella` con var="bookings") → rifiutato (il runtime vede la stringa finale)
- `scoped_conn(None)` → `MissingOrganizationIdError`
- `ScopedConnection` con org valida esegue query con filtro (mock conn), rifiuta senza filtro

Steps:
- [ ] Write failing tests
- [ ] Run: `pytest tests/core/test_scoping_unit.py -v` → FAIL (module not found)
- [ ] Implement `scoping.py`, aggiungi mixin alle 3 classi repository
- [ ] Run: `pytest tests/core/test_scoping_unit.py -v` → PASS
- [ ] Run: `pytest tests/ -x -q -k "not integration"` smoke (verifica nessun import rotto)
- [ ] Commit: `feat: add tenant scoping primitives (scoped_conn, system_scope)`

## Task 2: Script CI `scripts/check_tenant_scoping.py` + test

**Files:**
- Create: `scripts/check_tenant_scoping.py`
- Create: `tests/scripts/test_check_tenant_scoping.py`

**Interfaces (Consumes):** `TENANT_SCOPED_TABLES`, `extract_tables` da `src.core.db.scoping`.

**Spec script:**
- AST-based: per ogni `FunctionDef`/`AsyncFunctionDef` nei file target:
  - skip se decorator `@system_scope(...)` (Name o Call con func Name `system_scope`)
  - skip se `"{path}::{fn.name}"` in `ALLOWLISTED_FUNCTIONS` (dict nel file, valore = motivo obbligatorio)
  - per ogni literal SQL (Constant str; JoinedStr → concat delle parti statiche Constant):
    - se contiene keyword SQL (`\b(select|insert|update|delete)\b` case-insensitive):
      - **Regola anti-tabella-interpolata:** se una parte statica termina con `(from|join|into|update)\s*$` (case-insensitive) e la f-string ha un `FormattedValue` → violazione "dynamic table identifier"
      - `tables = extract_tables(static_text) & TENANT_SCOPED_TABLES`; se non vuoto e `"organization_id" not in static_text` → violazione (path, fn.name, fn.lineno, tabelle, sql[:100])
  - dedup violazioni per (fn.name, node.lineno) (nested functions visitate una volta)
- `DEFAULT_TARGETS = ["src/whatsapp/repository.py", "src/core/db/repository.py", "src/instagram/repository.py", "src/core/billing/webhook_handler.py", "src/core/bookings/reminder_job.py", "src/core/calendar/service.py", "src/core/report/weekly_report.py"]`
- `main(argv)`: target da argv[1:] o DEFAULT_TARGETS; exit 1 con report se violazioni, exit 0 "TENANT SCOPING CHECK: OK"
- Allowlist iniziale: `"src/core/reviews/google_service.py::..."` NON serve (file non nei target); lasciare dict vuoto con commento d'uso.

Test (filesystem tmp, subprocess per e2e, nessun DB):
- file pulito (query con organization_id) → 0 violazioni
- file con `SELECT * FROM bookings WHERE id = $1` → violazione con file/funzione/riga
- funzione `@system_scope("motivo")` → skippata
- funzione in ALLOWLISTED_FUNCTIONS → skippata
- query solo su tabelle infra/root (`SELECT 1`, `UPDATE organizations SET ... WHERE id=$1`) → non flaggiata
- f-string `f"SELECT * FROM {table}"` → violazione dynamic table identifier
- e2e subprocess: `python scripts/check_tenant_scoping.py <bad_file>` → returncode 1; file pulito → 0

Steps:
- [ ] Write failing tests
- [ ] Run: `pytest tests/scripts/test_check_tenant_scoping.py -v` → FAIL
- [ ] Implement script
- [ ] Run: `pytest tests/scripts/test_check_tenant_scoping.py -v` → PASS
- [ ] Run script sui DEFAULT_TARGETS → deve produrre SOLO le violazioni attese (inventario Task 3), exit 1
- [ ] Commit: `feat: add tenant scoping CI check script`

## Task 3: Integrazione CI + baseline violazioni

**Files:**
- Modify: `.github/workflows/ci.yml` (step tra ruff e pytest)

Step YAML da aggiungere:
```yaml
      - name: Tenant scoping check (guard dog)
        run: python scripts/check_tenant_scoping.py
```

- [ ] Aggiungi step CI
- [ ] Esegui `python scripts/check_tenant_scoping.py` localmente → salva output baseline in `.superpowers/sdd/<plan>/baseline-violations.txt`
- [ ] Verifica baseline ⊇ criticità Fase 1 (update_template_status, get_conversation, wam_id fallback, get_outbound_dedup, list_onboarding_profiles) + legacy (webhook_handler L76, reminder_job L18, calendar/service L171/L244, weekly_report L130)
- [ ] Commit: `ci: add tenant scoping guard dog step`

## Task 4: Fix criticità immediate (5 fix dedicati + 5 test dedicati)

**Files:**
- Modify: `src/whatsapp/repository.py` (update_template_status L919, _upsert_message fallback L199, get_outbound_dedup L471; DELETE soft_delete_message/conversation/contact L428-436)
- Modify: `src/core/db/repository.py` (DELETE list_onboarding_profiles L568)
- Modify: `src/whatsapp/templates.py:36`, `src/whatsapp/router.py:258` (chiamanti update_template_status)
- Modify: `src/core/inbox/routes.py` (7 chiamanti get_conversation — passano org_id già in scope)
- Modify: `src/whatsapp/inbound_processor.py:227` (chiamante get_outbound_dedup)
- Test: `tests/core/test_tenant_scoping.py` (nuovo, fixture seed 2 org su pg_pool full-schema di tests/core/conftest.py)

**Matrice di tracciabilità (chiusura fase = tutte e 5 verdi):**

| # | Criticità | Fix | Test dedicato |
|---|---|---|---|
| 1 | update_template_status org in SET mai WHERE | org obbligatorio + `WHERE organization_id=$1 AND name=$2 AND language=$5`; chiamanti aggiornati | `test_update_template_status_non_sovrascrive_altra_org`: 2 org stesso name/language; update org_a → riga org_b resta PENDING |
| 2 | get_conversation IDOR | param org obbligatorio + `c.organization_id = $2`; 7 chiamanti inbox/routes.py | `test_get_conversation_idor`: conv org_b con org_a → None; conv propria → ritornata |
| 3 | _upsert_message fallback wam_id cross-org | fallback `WHERE wam_id=$1 AND organization_id=$2` | `test_upsert_wamid_collision_per_org`: stesso wam_id da 2 org → ciascuna ottiene la propria riga |
| 4 | get_outbound_dedup senza org | `WHERE message_id=$1 AND organization_id=$2`; chiamante passa `msg["organization_id"]` | `test_outbound_dedup_scoped`: dedup org_a non visibile con org_b |
| 5 | dead code cross-tenant | DELETE `list_onboarding_profiles`, `soft_delete_message`, `soft_delete_conversation`, `soft_delete_contact` | `test_dead_code_rimosso`: `assert not hasattr(repo, ...)` per tutti e 4 |

I metodi fixati (1-4) usano `scoped_conn(organization_id)` (runtime check attivo).

Steps:
- [ ] Write i 4 test di regressione (2 org seed) → FAIL contro codice attuale dove applicabile (1: update cross-org; 2: IDOR; 3: collisione; 4: leak)
- [ ] Run: `pytest tests/core/test_tenant_scoping.py -v` → i 4 test FALLONO (dimostra il bug)
- [ ] Applica i 5 fix + aggiorna chiamanti + `test_dead_code_rimosso`
- [ ] Run: `pytest tests/core/test_tenant_scoping.py -v` → PASS
- [ ] Run: `pytest tests/whatsapp tests/core/inbox -x -q` → PASS (chiamanti aggiornati non rompono nulla)
- [ ] Commit: `fix: tenant-scope 5 critical repository paths + regression tests`

## Task 5: Migrazione metodi request-path a scoped_conn

**Files:**
- Modify: `src/whatsapp/repository.py`: update_message_status (L202, dynamic SET builder — org nel WHERE finale), update_message_status_by_wam_id (L242), try_mark_replied (L275), update_heartbeat (L292), claim_message_and_check_quota (L937 — statement messages con org), escalate_to_human (L791), claim_ticket (L807), release_ticket (L825), resolve_ticket (L843), assign_ticket (L875), set_conversation_ai_active (L897), save_ai_reply (L998), mark_message_sent (L1013), record_consent_event (L318 — UPDATE contacts con org; INSERT consent log invariato, tabella indiretta), get_contact_consent (L334), mark_ai_disclosure_sent (L342)
- Modify chiamanti: `src/whatsapp/router.py:193,200,210`, `src/whatsapp/service.py:128,133`, `src/instagram/service.py:59,64`, `src/whatsapp/retry_worker.py:60`, `src/whatsapp/repository.py:250` (interno), `src/whatsapp/inbound_processor.py:73,99,109,127,144,165,315,395,412,482,483`, `src/core/inbox/routes.py` (ticket lifecycle), `src/core/gdpr/routes.py:174`

**Regole:**
- `organization_id` parametro obbligatorio aggiunto IN CODA alla firma (no default). I chiamanti passano org già disponibile: router (webhook), service (TenantConfig.organization_id), retry_worker (`payload["organization_id"]`), inbound_processor (`msg["organization_id"]`), inbox/routes (`org_id` in scope), gdpr/routes (`org_id`).
- Corpo: `async with self.scoped_conn(organization_id) as conn:` al posto di `pool.acquire()`.
- `update_message_status_by_wam_id` riceve org e lo passa a `update_message_status` + filtro sul SELECT per wam_id.

Steps:
- [ ] Migra i 17 metodi + aggiorna tutti i chiamanti elencati
- [ ] Aggiorna mock in tests (AsyncMock firme: tests/whatsapp/conftest.py mock_repo, test vari che chiamano i metodi migrati) — aggiungi org args dove le firme sono cambiate
- [ ] Run: `pytest tests/whatsapp tests/core/inbox tests/core/gdpr -x -q` → PASS
- [ ] Run: `python scripts/check_tenant_scoping.py src/whatsapp/repository.py` → violazioni residue solo worker/system (ridotte rispetto baseline)
- [ ] Commit: `refactor: migrate request-path repository methods to scoped_conn`

## Task 6: Marcature @system_scope

**Files:**
- Modify: `src/whatsapp/repository.py`: get_org_by_phone_number_id, get_org_by_waba_id, claim_inbound_messages, claim_delivery_attempts, reap_stale_claims, delete_expired_messages, purge_soft_deleted_messages, cleanup_empty_conversations, reconstruct_payload_for_retry, insert_delivery_attempt, update_delivery_attempt
- Modify: `src/core/db/repository.py`: get_memberships_by_auth, get_organization_by_stripe_customer, delete_organization
- Modify: `src/instagram/repository.py`: get_org_by_instagram_user_id
- Test: `tests/scripts/test_check_tenant_scoping.py` (già copre decorator)

Motivi obbligatori (verbatim):
- tenant-resolution: `"tenant-resolution: lookup da webhook Meta (identita' platform-unique, pre-auth)"`
- worker/queue: `"worker queue: claim globale SKIP LOCKED, solo background job fidati"`
- retention/reaper: `"retention/reaper globale: manutenzione cross-tenant programmata"`
- retry: `"retry worker: org letta dal payload e riusata a valle"`
- delivery attempts (indiretta): `"tabella indiretta (via messages), solo worker"`
- memberships: `"risoluzione multi-org da JWT validato server-side"`
- stripe: `"risoluzione tenant da stripe_customer_id platform-unique"`
- delete_organization: `"root PK delete, cascade DB, endpoint owner-only"`
- instagram: `"tenant-resolution: lookup da webhook Meta (ig_user_id platform-unique)"`

Steps:
- [ ] Applica i 16 decorator con i motivi sopra
- [ ] Run: `python scripts/check_tenant_scoping.py` → confronta con baseline: violazioni residue = SOLO i 4 siti legacy (Task 7)
- [ ] Run: `pytest tests/ -x -q` smoke → PASS
- [ ] Commit: `chore: mark intentional cross-tenant repository methods system_scope`

## Task 7: Fix legacy fuori repository

**Files:**
- Modify: `src/core/billing/webhook_handler.py:76` — `UPDATE bookings ... WHERE id=$2` → aggiungi `AND organization_id=$3`; org da Stripe metadata; se metadata.organization_id assente/malformato → log + skip (fail-closed, nessun update)
- Modify: `src/core/bookings/reminder_job.py:18` — `WHERE id=$1` → `WHERE organization_id=$2 AND id=$1` (param org esiste in firma)
- Modify: `src/core/calendar/service.py:171,244` — create_event/delete_event: aggiungi `organization_id` param obbligatorio + filtro WHERE (booking dict porta organization_id)
- Modify: `src/core/report/weekly_report.py:130` — _segna_stato: aggiungi org param + filtro WHERE (org in scope chiamante)
- Modify chiamanti di create_event/delete_event/_segna_stato (grep per i call sites)

Steps:
- [ ] Applica i 4 fix + chiamanti
- [ ] Run: `python scripts/check_tenant_scoping.py` → **exit 0, zero violazioni**
- [ ] Run: `pytest tests/core tests/concurrency -x -q` → PASS
- [ ] Commit: `fix: org-filter legacy raw SQL outside repository layer`

## Task 8: QA finale (Fase 3 del mandato)

**Files:**
- Test: `tests/core/test_tenant_scoping.py` (estendi), `tests/scripts/test_check_tenant_scoping.py` (e2e guard-dog)

Checklist QA (ogni punto con evidenza nel report):
1. **Fail esplicito:** `scoped_conn(None)` → MissingOrganizationIdError; metodo migrato senza org → TypeError; statement senza filtro → TenantScopeViolation (test già in Task 1/4 — verifica esecuzione)
2. **Isolamento 2 org:** i 4 test regressione Task 4 verdi + `test_search_similar_isolato` (chunk org_b non ritornato a org_a)
3. **Guard-dog reale:** script sui target → exit 0; crea `scratch/test_violation_repo.py` con query deliberata senza filtro → script exit 1 con report → cancella file
4. **Completezza:** `grep -c "system_scope" src/**/repository.py` = 16 attese; nessun metodo della lista Fase 1 nel vecchio pattern; audit f-string SQL nei file scansionati (inventario: update_message_status migrato, list_reviews/update_review org nel testo statico, update_organization_billing root PK — nessun altro senza allowlist)
5. Suite completa: `pytest -v --tb=short` (TEST_DB_DSN) → PASS
6. `graphify update .`

Steps:
- [ ] Esegui checklist 1-4 con evidenze
- [ ] Run suite completa → PASS
- [ ] graphify update
- [ ] Commit: `test: tenant isolation QA suite + guard-dog e2e`

---

## Verification Matrix (finale)

| Requisito mandato | Evidenza |
|---|---|
| Wrapper: org obbligatorio strutturale | scoped_conn firma + test MissingOrganizationIdError/TypeError |
| Runtime fail-closed (copre SQL dinamico) | test assert_org_scoped su stringa finale assemblata |
| Check CI su repository layer + 4 legacy | script + step ci.yml + exit 0 finale |
| 5 criticità: fix + test dedicati ciascuna | matrice Task 4, tutti verdi |
| Guard-dog blocca davvero | QA-3: violazione deliberata → exit 1 |
| Nessuna funzione dimenticata | script exit 0 = prova formale + conteggio system_scope = 16 |
