# WhatsApp Business Cloud API Integration — Design Doc

**Data**: 2026-07-24  
**Stato**: Bozza in revisione  
**Roadmap riferimento**: Punto 1 (WhatsApp), Punto 2 (multi-tenancy/DB), Punto 5 (cifratura), Punto 6 (HITL/escalation)

---

## 1. Architettura generale

### 1.1 Struttura moduli

L'integrazione vive in un nuovo package `src/whatsapp/`, separato dal codice esistente ma coerente con la stratificazione già usata in `src/api/` + `src/core/`.

```
src/whatsapp/
├── router.py           # FastAPI: GET/POST /webhooks/whatsapp, validazione HMAC
├── service.py          # Orchestrazione: send_whatsapp_message, attempt_delivery,
│                       #   dispatch inbound, opt-out check, fast path
├── client.py           # Meta Graph API client (httpx async, chiamate REST nude)
├── models.py           # Pydantic: payload webhook, risposte Meta, richieste invio
├── repository.py       # asyncpg: tutte le query sulle tabelle WhatsApp
├── templates.py        # Sync template Meta ↔ DB (pull periodico + push webhook)
├── config.py           # AppConfig (env, globale) + TenantConfig + load_tenant_config()
├── inbound_processor.py  # Worker: polling messaggi received_pending_ai → AI → invio
└── retry_worker.py     # Worker: polling message_delivery_attempts → retry outbound
```

### 1.2 Stack

- **HTTP client**: `httpx` (async nativo, HTTP/2, coerenza con uvicorn async)
- **Retry immediati**: `tenacity` su `client.py` (2 tentativi, 5xx/429 con Retry-After)
- **Database**: Postgres + `asyncpg` (non ORM, query dirette)
- **Coda retry**: Postgres via tabella `message_delivery_attempts` con `SKIP LOCKED` — nessun Redis
- **Test**: `pytest` + `respx` (mock httpx) + `testcontainers` (Postgres integration)

### 1.3 Multi-tenancy

- `phone_number_id` → lookup su `whatsapp_accounts` per `statuses[]` / `messages[]`
- `waba_id` → lookup su `whatsapp_accounts` per `message_template_status_update`
- `verify_token` a livello di app (unico in `AppConfig`), non per-tenant — per-tenant sarà introdotto solo con Embedded Signup (futuro)
- `access_token` cifrato a riposo con `ENCRYPTION_KEY` (Punto 5 roadmap), decifrato in `load_tenant_config()`
- `business_profile` su `organizations` come JSONB — compromesso esplicito (non gratuito: query su campi specifici è più scomoda rispetto a colonne proprie)

---

## 2. Webhook endpoint

### 2.1 GET /webhooks/whatsapp — Verifica iniziale Meta

```
Input:  hub.mode, hub.verify_token, hub.challenge (query params)
Output: 200 {hub.challenge} oppure 403

AppConfig.verify_token (unico) confrontato con hub.verify_token.
```

### 2.2 POST /webhooks/whatsapp — Ricezione eventi

Pipeline di ingresso per ogni richiesta:

1. **Verifica HMAC**: legge `X-Hub-Signature-256`, calcola HMAC-SHA256(body, `app_secret`), confronto constant-time (`hmac.compare_digest`). Se non valida → **403 Forbidden**

2. **Branch per tipo evento** (3 rami):

   a. **`statuses[]`** (delivered/read/failed) → inline, solo query DB
      - Lookup `phone_number_id` → organization_id
      - Match del messaggio da aggiornare — in ordine:
        1. Per `wam_id` (`payload.statuses[].id`) — caso normale
        2. Se non trovato, per `biz_opaque_callback_data = messages.id` — caso
           `sending_ambiguous`, dove il `wam_id` non era ancora stato assegnato.
           Se trovato per questa via, popola anche `wam_id` ora.
      - UPDATE messages SET status con `apply_status_update()` guardia monotona
      - Risponde 200 immediato

   b. **`messages[]`** (messaggio in ingresso) → insert veloce + worker
      - Lookup `phone_number_id` → organization_id
      - UPSERT messages (ON CONFLICT wam_id DO NOTHING) — idempotenza su retry Meta
      - Stato: `received_pending_ai`
      - Risponde 200 immediato
      - Worker `inbound_processor.py` raccoglie via SKIP LOCKED

   c. **`message_template_status_update`** → inline, aggiornamento stato template
      - Lookup `waba_id` → organization_id (`get_org_by_waba_id`)
      - UPDATE whatsapp_templates SET status, rejected_reason (se REJECTED)
      - Solo stato, NON sovrascrive i components

### 2.3 HMAC verificato prima di tutto

La verifica avviene prima di qualunque altro processing (incluso tenant lookup), perché:
- È un controllo di sicurezza che va fatto sul body grezzo prima di ogni altra operazione
- Non dipende dal tenant, usa solo `AppConfig.app_secret`

---

## 3. Inbound processing pipeline (`inbound_processor.py`)

Worker standalone (stesso pattern di `src/api/reindex_worker.py`). Loop:
`SELECT ... FROM messages WHERE direction='inbound' AND status='received_pending_ai' LIMIT 10 FOR UPDATE SKIP LOCKED` → claim a `processing` + `claimed_at=NOW()` in transazione breve → processa fuori transazione.

**Reaper (crash recovery)**: a ogni ciclo, prima del claim normale, resetta righe rimaste in `processing` oltre 5 minuti:
```sql
UPDATE messages SET status='received_pending_ai', claimed_at=NULL
  WHERE status='processing' AND claimed_at < NOW() - INTERVAL '5 minutes';
UPDATE message_delivery_attempts SET status='pending', claimed_at=NULL
  WHERE status='processing' AND claimed_at < NOW() - INTERVAL '5 minutes';
```
Questo garantisce che un worker crashato dopo il claim ma prima del completamento non lasci righe bloccate per sempre. Valido sia per `inbound_processor.py` che per `retry_worker.py`.

Pipeline per ogni messaggio:

### Step 1 — Opt-out check

Il messaggio in arrivo è una richiesta di opt-out?

- **Keyword matching** multilingua su testo libero (normalizzato: lowercase, trim, rimozione punteggiatura)
- **Button reply** con id esplicito (`unsubscribe_confirm`) — canale affidabile, deterministico
- Match certo → `record_consent_event()`, invia solo ack testuale, **salta step 2-5**
- Match ambiguo (frase lunga che contiene la keyword ma intento non chiaro) → **HITL**, non auto-processare

### Step 2 — Fast path

Pattern match su categorie dove la risposta non richiede né RAG né LLM (zero rischio allucinazione):

- **Saluti/apertura**: risposta fissa da business_profile
- **Orari/indirizzo/telefono**: dati strutturati da `organizations.business_profile` (JSONB)
- **Fuori orario**: basato su `business_profile.orari` + timestamp corrente
- **Ringraziamenti/chiusura**: risposta fissa

Se match → `handling_type = fast_path`, genera risposta senza AI, **salta step 3-5**.

**Governance**: si parte con queste sole 3 categorie. Nuove categorie aggiunte solo se dati reali (Punto 17) mostrano volume significativo di un pattern ricorrente e sicuro.

### Step 3 — Intent classification

Chiamata a modello economico per classificare il messaggio in una categoria (prenotazione, reclamo, informazione, generico, ...).

### Step 4 — RAG retrieval

Recupero chunks rilevanti dal vector store per il contesto della risposta.

### Step 5 — AI response generation

CrewAI agent (riusa `responder_agent.py` / `crea_crew()` esistente) con contesto WhatsApp.

### Step 6 — Outbound send

Chiama `send_whatsapp_message()` in `service.py` (vedi Sezione 4), che include:
- Opt-out gate: se categoria risposta = `marketing` e `contacts.marketing_opt_out = true` → `MessageBlockedByOptOut`
- POST a Meta con `biz_opaque_callback_data = msg_id`
- UPSERT messages con wam_id di risposta

### Step 7 — Status tracking

Il callback di stato (delivered/read/failed) arriva via webhook statuses[] e viene correlato al messaggio outbound originale tramite `biz_opaque_callback_data`.

### Metriche

Ogni messaggio outbound è taggato con `handling_type`:
- `fast_path` — risposta da pattern match, nessun LLM chiamato
- `ai` — risposta generata da CrewAI
- `escalated_human` — passato a staff

Il fast path non consuma budget LLM e va escluso dal conteggio `usage_events` per metriche Stripe/Piano (Punto 4/13).

---

## 4. Outbound send + retry worker

### 4.1 `send_whatsapp_message()` in `service.py`

```
send_whatsapp_message(org_id, to_number, payload, category)
  1. Opt-out gate: if category == "marketing" AND contacts.marketing_opt_out → raise
  2. Carica tenant config (load_tenant_config → decifra access_token)
  3. INSERT messages (status=queued, direction=outbound, content, biz_opaque_callback_data=id)
  4. Chiama attempt_delivery(message_id, phone_number_id, access_token, payload)
  5. Restituisce { wam_id, status, msg_id }
```

### 4.2 `attempt_delivery()` in `service.py`

Solo POST a Meta + UPDATE — mai INSERT. Usata sia dal primo tentativo che da `retry_worker.py`.

```
attempt_delivery(message_id, phone_number_id, access_token, payload)
  POST /v20.0/{phone_number_id}/messages (httpx, 5s timeout)
    ├── 2xx → UPDATE messages SET wam_id, status=sent, sent_at=NOW()
    ├── 429 → rispetta Retry-After header; se inline (tenacity): riprova;
    │           se in worker: programma retry con backoff
    ├── 5xx → retry (inline o coda)
    ├── 4xx ≠ 429 → UPDATE messages SET status=failed (errore permanente, NO retry)
    └── timeout/ConnectError →
          UPDATE messages SET status=sending_ambiguous
          INSERT message_delivery_attempts (status=pending, next_retry_at = NOW() + breve delay)
          # Il worker, prima di ritentare, controlla se nel frattempo è arrivato
          # un webhook di stato per questo message_id (via biz_opaque_callback_data)
```

### 4.3 `retry_worker.py`

Entry point standalone, loop polling su `message_delivery_attempts`:

```
Loop:
  1. Transazione breve: BEGIN; SELECT ... FOR UPDATE SKIP LOCKED LIMIT 10;
     UPDATE status='processing'; COMMIT;
  2. Per ogni riga (fuori transazione):
     a. Recupera messages.id → reconstruct payload (da messages.content JSONB)
     b. Controlla: se nel frattempo è arrivato webhook di stato per questo
        message_id? Se sì → allinea stato, non ritentare
     c. Se no → attempt_delivery()
        - successo: UPDATE message_delivery_attempts status=succeeded
        - fallito: incrementa attempt_number
          - se < max_retry (5): UPDATE next_retry_at = backoff(NOW())
          - se >= max_retry: UPDATE status=failed, messages.status=failed
            → notifica staff (escalation)
  3. sleep(1)
```

Backoff strategy per `next_retry_at`:
- 1° retry: +30s
- 2°: +2min
- 3°: +10min
- 4°: +1h
- 5°: +6h (dead-letter)

---

## 5. Schema DB

### 5.1 Tabelle

```sql
CREATE TABLE organizations (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL,
    business_profile JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE whatsapp_accounts (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    phone_number_id TEXT NOT NULL UNIQUE,
    waba_id         TEXT NOT NULL,
    access_token    TEXT NOT NULL,          -- cifrato con ENCRYPTION_KEY
    verify_token    TEXT,                   -- nullable: serve solo se Embedded Signup
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_whatsapp_accounts_org ON whatsapp_accounts(organization_id);

CREATE TABLE contacts (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    phone_number    TEXT NOT NULL,
    marketing_opt_out BOOLEAN NOT NULL DEFAULT FALSE,
    opted_out_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, phone_number)
);
CREATE INDEX idx_contacts_org ON contacts(organization_id);

CREATE TABLE conversations (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    contact_id      UUID NOT NULL REFERENCES contacts(id),
    status          TEXT NOT NULL DEFAULT 'active',
    last_message_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, contact_id)
);
CREATE INDEX idx_conversations_org ON conversations(organization_id);

CREATE TABLE messages (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    wam_id          TEXT UNIQUE,
    direction       TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    message_type    TEXT NOT NULL,
    content         JSONB NOT NULL,
    content_text    TEXT,
    status          TEXT NOT NULL,
    handling_type   TEXT,
    error_code      TEXT,
    error_title     TEXT,
    error_details   JSONB,
    sent_at         TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    read_at         TIMESTAMPTZ,
    claimed_at      TIMESTAMPTZ,           -- worker claim, per recovery crash
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_status_by_direction CHECK (
        (direction = 'inbound'  AND status IN ('received_pending_ai','processing','handled'))
        OR
        (direction = 'outbound' AND status IN ('queued','processing','sent','delivered','read','failed','sending_ambiguous'))
    )
);
CREATE UNIQUE INDEX idx_messages_wam_id ON messages(wam_id) WHERE wam_id IS NOT NULL;
CREATE INDEX idx_messages_org_created ON messages(organization_id, created_at DESC);
CREATE INDEX idx_messages_org_status ON messages(organization_id, status) WHERE status != 'read';
CREATE INDEX idx_messages_org_inbound_pending ON messages(organization_id)
    WHERE direction='inbound' AND status='received_pending_ai';
CREATE INDEX idx_messages_conversation ON messages(conversation_id, created_at);

CREATE TABLE message_delivery_attempts (
    id              UUID PRIMARY KEY,
    message_id      UUID NOT NULL REFERENCES messages(id),
    attempt_number  INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending',
    next_retry_at   TIMESTAMPTZ,
    error_details   JSONB,
    claimed_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_delivery_attempts_message ON message_delivery_attempts(message_id);
CREATE INDEX idx_delivery_attempts_retry
    ON message_delivery_attempts(status, next_retry_at)
    WHERE status = 'pending';
CREATE UNIQUE INDEX idx_one_active_attempt_per_message
    ON message_delivery_attempts(message_id)
    WHERE status IN ('pending', 'processing');

CREATE TABLE contact_consent_log (
    id              UUID PRIMARY KEY,
    contact_id      UUID NOT NULL REFERENCES contacts(id),
    event_type      TEXT NOT NULL CHECK (event_type IN ('opt_out', 'opt_in')),
    method          TEXT NOT NULL CHECK (method IN ('keyword_match', 'button_reply', 'manual_staff')),
    triggering_message_id UUID REFERENCES messages(id),
    matched_text    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_consent_log_contact ON contact_consent_log(contact_id);

CREATE TABLE whatsapp_templates (
    id              UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name            TEXT NOT NULL,
    language        TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')),
    status          TEXT NOT NULL DEFAULT 'PENDING',
    components      JSONB NOT NULL,
    rejected_reason TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, name, language)
);
CREATE INDEX idx_templates_org ON whatsapp_templates(organization_id);
```

### 5.2 `apply_status_update()` — guardia monotona per messaggi outbound

```python
STATUS_RANK = {
    "queued": 0, "processing": 0, "sending_ambiguous": 0,
    "sent": 1, "delivered": 2, "read": 3, "failed": 4
}

def apply_status_update(current_status: str, new_status: str) -> bool:
    if new_status == "failed":
        return True  # failed vince sempre
    return STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(current_status, 0)
```

### 5.3 `repository.py` — funzioni pubbliche

- `get_org_by_phone_number_id(pid)` → organization_id + tenant data
- `get_org_by_waba_id(waba_id)` → organization_id
- `get_tenant_config(org_id)` → access_token (cifrato), phone_number_id, waba_id
- `get_or_create_contact(org_id, phone)` → contact
- `get_or_create_conversation(org_id, contact_id)` → conversation
- `get_contact_prefs(org_id, phone)` → contact (con marketing_opt_out)
- `upsert_message(msg)` → ON CONFLICT (wam_id) DO NOTHING
- `update_message_status(id, status, wam_id, ...)` → con guardia `apply_status_update()`
- `claim_inbound_messages(limit)` → SELECT FOR UPDATE SKIP LOCKED + UPDATE processing
- `claim_delivery_attempts(limit)` → SELECT FOR UPDATE SKIP LOCKED + UPDATE processing
- `record_consent_event(contact_id, event_type, method, ...)` → insert consent_log
- `insert_delivery_attempt(message_id, next_retry_at)` → insert
- `update_delivery_attempt(id, status, error_details)` → update
- `reconstruct_payload_for_retry(message_id)` → join messages + templates se necessario
- `reap_stale_claims()` → reset righe `processing` con `claimed_at` scaduto

---

## 6. Config

### 6.1 `AppConfig` (globale, da env, letto una volta all'avvio)

```
app_secret          # Meta App Secret (HMAC, condiviso)
encryption_key      # ENCRYPTION_KEY per cifratura access_token
postgres_dsn        # connessione DB
verify_token        # unico a livello app (per MVP)
max_retry_attempts  # default 5
```

### 6.2 `TenantConfig` (per-request, caricato da DB)

```
organization_id     # UUID
phone_number_id     # chiave lookup webhook
waba_id             # per template sync
access_token        # già decifrato
business_profile    # orari, indirizzo, tono per fast path
```

### 6.3 `load_tenant_config(org_id, app_config, repo)` — punto di raccordo

Unico posto dove `encryption_key` (da AppConfig) incontra `access_token` (da DB). Decifra il token e costruisce `TenantConfig`.

---

## 7. Template sync

- **Pull periodico**: job schedulato ogni 6h, per ogni tenant fa `GET /v20.0/{waba_id}/message_templates`, upsert completo
- **Push da Meta**: webhook `message_template_status_update` (branch c nel router) — solo update di `status` e `rejected_reason`, mai replace dei `components`
- **Race pull/push**: last-write-wins accettato (entrambi convergono allo stesso stato reale)

---

## 8. Test plan

| Layer | Tool | Cosa testa |
|---|---|---|
| `models.py` | `pytest` | Parsing payload Meta reali (fixture JSON versionate dalla doc Meta) |
| `client.py` | `respx` | Mock HTTP: 2xx, 429 con Retry-After, 5xx, timeout |
| `repository.py` | `pytest` + **testcontainers** (Postgres 16) | Idempotenza upsert wam_id, guardia monotona, SKIP LOCKED concorrente, unique partial index |
| `apply_status_update()` | `pytest` | Transizioni valide/invalide, failed vince, retrocessioni ignorate |
| `service.py` | Mock client + mock repo | Opt-out gate blocca marketing, attempt_delivery mai INSERT |
| `templates.py` | `respx` + mock repo | Pull upsert corretto, push solo stato+rejected_reason |
| `router.py` | `TestClient` + monkeypatch HMAC | GET 200/403, POST firma valida/invalida, lookup fallito |
| `inbound_processor.py` | Integration | Polling → processing → durabilità su crash |
| `retry_worker.py` | Integration | Backoff, dead-letter, timeout → sending_ambiguous |

### Dettagli implementativi test

- **Testcontainers locale**: `postgres:16` (stessa versione della CI)
- **Service container CI**: `postgres:16` (stessa versione, non `latest`)
- **Migrazioni**: stesse migrazioni (Alembic) usate per deploy reale, applicate sia su testcontainers sia su CI — mai schema "di comodo"
- **Isolamento tra test**: `TRUNCATE ... CASCADE` in fixture setup (o rollback automatico per-test con transazione)
- **Test concorrenza SKIP LOCKED**: due connessioni separate + `asyncio.gather` (non in sequenza)
- **Payload fixture**: file JSON reali dalla documentazione Meta, salvati versionati nel repo

---

## 9. Decisioni aperte / future

- `verify_token` per-tenant: sarà introdotto solo con Embedded Signup self-service (Punto 7 wizard onboarding)
- `business_profile` come JSONB: compromesso per MVP; se Punto 6/7 richiedono query su campi specifici (es. SLA, regole escalation per settore), va migrato a colonne proprie
- Redis: non introdotto ora; sarà valutato al Punto 15 (infrastruttura production) per throughput elevato, pub/sub, rate limiting distribuito
- Non serve un webhook per statuses[] separato: convive nello stesso POST /webhooks/whatsapp, differenziato dal branch iniziale
