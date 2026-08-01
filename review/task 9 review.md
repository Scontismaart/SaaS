# Task 09 — Robustezza, GDPR, Atomicità e Refactoring Infrastructure

## Obiettivo

Rendere il webhook Meta più robusto (idempotenza, batch isolation), implementare la nuova strategia GDPR/FK, centralizzare il trial length in `BillingConfig`, aggiungere timezone per tenant, validare il business profile con Pydantic, e sostituire l'invio email bloccante con una coda asincrona.

---

## Piano

### 1. Idempotenza webhook Meta
- PK tripla `(wam_id, resource_type, status_value)` con `INSERT ... ON CONFLICT DO NOTHING RETURNING NULL`
- Nessun `except Exception` nel batch loop → DB error → 500 → Meta ritenta
- TTL cleanup rimandato (non implementato in questa task)

### 2. GDPR / FK Cascade
- **Migration 014** — indici B-tree su FK contatti, CASCADE per dati cliente, SET NULL per storico billing/audit, trigger `mask_pii_before_contact_delete`, trigger `propagate_contact_soft_delete`
- **delete_organization** — singola `DELETE FROM organizations WHERE id = $1`, CASCADE DB gestisce tutto
- **Test** — `test_gdpr_fk.py`: soft-delete preserva booking, hard-delete anonimizza PII, CASCADE elimina conversation+consent_log, delete_organization attiva trigger anonimizzazione, transaction rollback su usage failure

### 3. Atomicità messaggio + usage
- `upsert_message` e `increment_message_usage` con parametro `conn` opzionale
- `_handle_inbound_message` apre `pool.acquire() + conn.transaction()` e inietta `conn`
- Usage increment eseguito per ultimo (minima contesa lock)

### 4. Trial length centralizzato
- `src/core/billing/config.py` — `BillingConfig(stripe_trial_days=7)`
- `app.state.billing_config` creato in `main.py` prima del blocco DB
- `routes.py` legge da `request.app.state.billing_config.stripe_trial_days`
- `webhook_handler.py` accetta `trial_days: int` come parametro (rimosso `os.getenv`)
- `.env` → `STRIPE_TRIAL_DAYS=7`

### 5. Timezone reminders
- **Migration 016** — `ALTER TABLE organizations ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Europe/Rome'`
- `TenantConfig.timezone` letto in `load_tenant_config`
- `reminder_job.py` / `no_show_job.py` — `ZoneInfo(org_timezone)` invece di `date.today()`
- `scheduler.py` — SELECT `id, timezone` passato alle job functions

### 6. Business profile validation
- `WhatsAppBusinessProfile(BaseModel)` in `src/models/schemas.py`
- `_profile_from_dict` usa `model_validate()` + log strutturato su `ValidationError`

### 7. Async queue escalation email
- `email_service.py` riscritto: `EscalationEvent`, `asyncio.Queue`, `_worker()`, `_send_with_retry(tenacity 3 tentativi, backoff 5s-30s-120s)`, `enqueue_escalation()`, `start_worker()/stop_worker()`
- Webhook non attende SMTP
- `requirements.txt` — aggiunto `tenacity>=9.0,<10`
- `inbound_processor.py` — `enqueue_escalation` invece di `await send_escalation_notification`
- `inbox/routes.py` — import aggiornato
- `main.py` — `start_worker()` all'avvio, `stop_email_worker()` in shutdown

---

## Files modificati / creati

### Nuovi
| File | Descrizione |
|------|-------------|
| `src/core/billing/config.py` | `BillingConfig` dataclass |
| `src/core/db/migrations/016_org_timezone.sql` | Colonna `timezone` su organizations |
| `src/models/schemas.py` | `WhatsAppBusinessProfile(BaseModel)` |
| `tests/whatsapp/test_gdpr_fk.py` | 5 test GDPR cascade |

### Modificati
| File | Cosa |
|------|------|
| `src/core/db/migrations/014_contact_fk_strategy.sql` | Indici B-tree, CASCADE/SET NULL, trigger PII |
| `src/whatsapp/inbound_processor.py` | `_profile_from_dict` Pydantic; `enqueue_escalation` |
| `src/core/notifications/email_service.py` | Riscritto con queue + tenacity retry |
| `src/api/main.py` | `app.state.billing_config`, `start_worker()`, `stop_email_worker()` |
| `src/core/billing/routes.py` | Legge `stripe_trial_days` da `app.state` |
| `src/core/billing/webhook_handler.py` | Accetta `trial_days` param, rimosso `os.getenv` |
| `src/core/bookings/reminder_job.py` | `ZoneInfo(org_timezone)` |
| `src/core/bookings/no_show_job.py` | `ZoneInfo(org_timezone)` |
| `src/core/scheduler.py` | SELECT `timezone` passato ai job |
| `src/whatsapp/config.py` | `TenantConfig.timezone` |
| `src/core/inbox/routes.py` | Import `enqueue_escalation` |
| `.env` | `STRIPE_TRIAL_DAYS=7` |
| `requirements.txt` | `tenacity>=9.0,<10` |
| `prompt-roadmap-saas.md` | "trial 14" → "trial 7" |

### Test modificati
| File | Cosa |
|------|------|
| `tests/core/test_email_service.py` | Riscritto per `_send_with_retry` + `enqueue_escalation` |
| `tests/whatsapp/test_inbound_processor.py` | Patch `enqueue_escalation`, `MagicMock` non `AsyncMock` |
| `tests/whatsapp/test_router.py` | `mock_conn` `AsyncMock` → `MagicMock` |
| `tests/whatsapp/conftest.py` | Booking/reviews/booking_settings CREATE; stub documents, document_chunks, email_configs, usage_events, event_log, audit_log; carica 015+016 |
| `tests/core/conftest.py` | Carica 015+016 migration |

---

## Fix applicati durante la sessione

### Fix 1 — `test_enqueue_escalation_adds_to_queue` (stale import)
- `from ... import _queue` crea un riferimento locale che non vede la riassegnazione di `_queue = asyncio.Queue()` in `start_worker()`
- **Soluzione:** import tramite `notifications.email_service._queue`

### Fix 2 — `handle_stripe_webhook` missing `trial_days`
- 16 chiamate in `test_webhook_handler.py` + 2 in `test_webhook_deposito.py` senza l'argomento `trial_days`
- **Soluzione:** `, 7` aggiunto a tutte le 18 chiamate

### Fix 3 — `documents` / `document_chunks` / `email_configs` / `usage_events` / `event_log` / `audit_log` mancanti per migration 015
- `test_inbound_processor.py` e altri fallivano con `relation "document_chunks" does not exist`
- **Soluzione:** CREATE TABLE IF NOT EXISTS stubs nel conftest whatsapp prima di caricare 015

### Fix 4 — `audit_log` stub senza `created_at`
- Lo stub minimal `CREATE TABLE IF NOT EXISTS audit_log (id UUID PRIMARY KEY, organization_id UUID)` non ha `created_at`
- Quando `test_hitl_repository.py` esegue `002_auth_tables.sql`, `CREATE TABLE IF NOT EXISTS` skippa (tabella già esistente), ma `CREATE INDEX ... ON audit_log(organization_id, created_at DESC)` fallisce perché `created_at` manca
- **Soluzione:** aggiunto `created_at TIMESTAMPTZ DEFAULT NOW()` allo stub

### Fix 5 — `assert_awaited_once` su sync function
- `enqueue_escalation` è ora sincrona (non async), ma il test usava `assert_awaited_once()`
- **Soluzione:** cambiato in `assert_called_once()`

---

## Risultato finale

```
304 passed, 4 warnings in 122.09s
```
