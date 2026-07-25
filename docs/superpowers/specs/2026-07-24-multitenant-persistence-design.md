# Multi-tenant Persistence Schema — Design Doc

**Data**: 2026-07-24
**Stato**: Bozza in revisione
**Roadmap riferimento**: Punto 2 (multi-tenancy/DB persistente)

---

## 1. Obiettivo

Consolidare tutte le attuali sorgenti dati (RAM, Airtable, ChromaDB, JSON files, costanti Python) in un unico schema PostgreSQL multi-tenant, estendendo la convenzione `organization_id` già usata in `src/whatsapp/schema.sql`.

### 1.1 Sorgenti da sostituire

| Sorgente | Stato attuale | Destinazione |
|---|---|---|
| `prenotazioni.py` (`_prenotazioni_demo` list) | RAM volatile | `bookings` |
| `airtable_client.py` | Airtable API | `bookings` |
| `vector_store.py` | ChromaDB `documenti_locale` | `documents` + `document_chunks` (pgvector) |
| `business_profile.py` (`TRATTORIA_DA_MARIO`) | Costante Python | `organizations.business_profile` (già esiste) |
| `email_config_store.py` | `data/email_config.json` | `email_configs` |
| `main.py` (`_storico_eventi` list) | RAM volatile | `event_log` (popolato da trigger) |
| `conversation_store.py` (RAM deque) | RAM volatile | Già coperto da tabella `messages` |

### 1.2 Cosa NON cambia

- `gmail_token_store.py` → token OAuth restano su filesystem (`data/gmail_tokens/{organization_id}/{email}.token`), con `organization_id` nel path per isolamento tenant.
- `src/whatsapp/schema.sql` → le 8 tabelle WhatsApp restano invariate.

---

## 2. Schema PostgreSQL

### 2.1 Convenzioni comuni

- Ogni tabella ha `organization_id UUID NOT NULL REFERENCES organizations(id)` come prima chiave di isolamento.
- Ogni query applicativa include `WHERE organization_id = $1`.
- `created_at` e `updated_at` sono `TIMESTAMPTZ DEFAULT NOW()` su ogni tabella.
- Campi semi-strutturati usano `JSONB`.
- CHECK constraints su colonne con insieme finito di valori.

### 2.2 DDL completo

```sql
-- ============================================================
-- EXTENSION
-- ============================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector

-- ============================================================
-- 1. BOOKINGS (sostituisce Airtable + _prenotazioni_demo)
-- ============================================================
CREATE TABLE bookings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    contact_id          UUID REFERENCES contacts(id),
    nome_cliente        TEXT NOT NULL,
    telefono            TEXT NOT NULL DEFAULT '',
    data                DATE NOT NULL,
    ora                 TIME NOT NULL,
    coperti             INT CHECK (coperti > 0),
    note                TEXT NOT NULL DEFAULT '',
    stato               TEXT NOT NULL DEFAULT 'in_attesa'
                        CHECK (stato IN ('in_attesa','confermata','cancellata','no_show','completata')),
    origine             TEXT NOT NULL DEFAULT 'Dashboard',
    richiede_intervento BOOLEAN NOT NULL DEFAULT FALSE,
    id_conversazione    TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_bookings_org_data ON bookings(organization_id, data);

-- ============================================================
-- 2. BOOKING_SETTINGS (sostituisce capienze orarie in RAM)
-- ============================================================
CREATE TABLE booking_settings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id) UNIQUE,
    slot_minutes        INT NOT NULL DEFAULT 60,
    fasce_orarie        JSONB,    -- default gestito da repository.py
    capienze_orarie     JSONB,    -- default gestito da repository.py
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id)
);

-- ============================================================
-- 3. REVIEWS
-- ============================================================
CREATE TABLE reviews (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    contact_id          UUID REFERENCES contacts(id),
    testo               TEXT NOT NULL,
    valutazione_stelle  INT CHECK (valutazione_stelle BETWEEN 1 AND 5),
    fonte               TEXT NOT NULL DEFAULT 'manuale',
    autore              TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_reviews_org ON reviews(organization_id);

-- ============================================================
-- 4. DOCUMENTS (metadati)
-- ============================================================
CREATE TABLE documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    nome                TEXT NOT NULL,
    tipo                TEXT NOT NULL DEFAULT 'upload',
    fonte               TEXT NOT NULL DEFAULT '',
    caricato_il         TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_documents_org ON documents(organization_id);

-- ============================================================
-- 5. DOCUMENT_CHUNKS (pgvector, sostituisce ChromaDB)
-- ============================================================
CREATE TABLE document_chunks (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    document_id         UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index         INT NOT NULL,
    content             TEXT NOT NULL,
    embedding           vector(384) NOT NULL,
    metadata            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_chunks_org_doc ON document_chunks(organization_id, document_id);
CREATE INDEX idx_chunks_org_embedding ON document_chunks
    USING hnsw (embedding vector_cosine_ops);

-- Trigger: garantisce coerenza organization_id tra chunk e documento
CREATE FUNCTION check_chunk_org_consistency() RETURNS trigger AS $$
BEGIN
  IF NEW.organization_id != (SELECT organization_id FROM documents WHERE id = NEW.document_id) THEN
    RAISE EXCEPTION
      'organization_id mismatch: chunk belongs to org %, document belongs to org %',
      NEW.organization_id,
      (SELECT organization_id FROM documents WHERE id = NEW.document_id);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_check_chunk_org
    AFTER INSERT OR UPDATE ON document_chunks
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION check_chunk_org_consistency();

-- ============================================================
-- 6. EMAIL_CONFIGS (sostituisce email_config.json)
-- ============================================================
CREATE TABLE email_configs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    indirizzo           TEXT NOT NULL,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, indirizzo)
);

-- ============================================================
-- 7. USAGE_EVENTS (billing)
-- ============================================================
CREATE TABLE usage_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    event_type          TEXT NOT NULL,
    quantity            INT NOT NULL DEFAULT 1,
    metadata            JSONB NOT NULL DEFAULT '{}',
    billing_month       DATE GENERATED ALWAYS AS
                        (date_trunc('month', created_at AT TIME ZONE 'UTC')::date) STORED,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_usage_events_org_month ON usage_events(organization_id, billing_month);

-- ============================================================
-- 8. EVENT_LOG (proiezione derivata da trigger, mai scritta dal codice)
-- ============================================================
CREATE TABLE event_log (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID NOT NULL REFERENCES organizations(id),
    source_table        TEXT NOT NULL,
    source_id           UUID NOT NULL,
    tipo_evento         TEXT NOT NULL,
    priorita            TEXT NOT NULL,
    testo_originale     TEXT NOT NULL DEFAULT '',
    risposta_ai         TEXT NOT NULL DEFAULT '',
    gestito_da_ai       BOOLEAN NOT NULL DEFAULT TRUE,
    dettagli            JSONB NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_event_log_org_created ON event_log(organization_id, created_at DESC);
CREATE INDEX idx_event_log_org_priorita ON event_log(organization_id, priorita)
    WHERE priorita != 'bassa';
```

### 2.3 Trigger di popolamento event_log (esempi)

```sql
-- messages → event_log (solo inbound handled)
CREATE FUNCTION log_message_event() RETURNS trigger AS $$
BEGIN
  IF NEW.direction = 'inbound' AND NEW.status = 'handled' THEN
    INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                           testo_originale, risposta_ai, gestito_da_ai, dettagli)
    VALUES (
      NEW.organization_id, 'messages', NEW.id, 'messaggio',
      CASE WHEN NEW.handling_type = 'escalated' THEN 'alta' ELSE 'media' END,
      NEW.content_text,
      NEW.content->>'response'::text,
      NEW.handling_type = 'ai_handled',
      jsonb_build_object('conversation_id', NEW.conversation_id, 'handling_type', NEW.handling_type)
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_log_message_event
    AFTER INSERT OR UPDATE OF status ON messages
    FOR EACH ROW EXECUTE FUNCTION log_message_event();
```

Trigger analoghi per `reviews` (on INSERT) e `bookings` (on UPDATE of stato = 'cancellata').

---

## 3. Multi-tenancy

### 3.1 Isolamento a livello query

Stessa strategia di `src/whatsapp/schema.sql`:

- `organization_id` come prima colonna in ogni indice composto.
- Repository layer (`src/whatsapp/repository.py`) già parametrizza ogni query con `$1 = organization_id`.
- Nuovo repository per tabelle core (bookings, documents, ecc.) seguirà lo stesso pattern.

### 3.2 Isolamento strutturale su document_chunks

Il trigger `trg_check_chunk_org` impedisce che un chunk venga associato a un `organization_id` diverso dal suo documento padre. Questo è un guardrail a livello DB, non solo una convenzione del codice.

### 3.3 Isolamento Gmail token su filesystem

```
data/gmail_tokens/{organization_id}/{email}.token
```

`email_configs` referenzia l'indirizzo email; il path di isolamento è costruito a runtime dal repository layer concatenando `organization_id` e `indirizzo`.

---

## 4. pgvector: strategia embedding

| Parametro | Valore |
|---|---|
| Modello | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Dimensione | 384 |
| Indice | HNSW (cosine) |
| Metrica | `vector_cosine_ops` |

Scelta HNSW vs IVFFlat:

- HNSW funziona bene indipendentemente dal volume di righe (non richiede tuning di `lists`).
- IVFFlat richiede `lists ≈ sqrt(N)` — con poche centinaia di chunk per tenant, `lists` sarebbe più grande del dataset stesso.
- HNSW supporta insert incrementali senza dover re-indicizzare.

---

## 5. Piano di migrazione

### Step 1: DDL su PostgreSQL

Eseguire lo schema DDL sopra sul database di staging (e poi produzione).

### Step 2: business_profile → organizations

```python
UPDATE organizations
SET business_profile = '{
  "nome": "Trattoria Da Mario",
  "tipo_attivita": "ristorante",
  "tono": "caldo, informale, familiare...",
  "orari": "Martedì-Domenica: ...",
  "servizi_principali": [...],
  "note_speciali": [...]
}'::jsonb
WHERE id = '<org_id>';
```

### Step 3: Airtable → bookings

Script Python one-shot:
1. `GET /api/airtable/bookings` (fetch all).
2. Trasforma `PrenotazioneCalendario` → row `bookings`.
3. Batch INSERT via `asyncpg`.

### Step 4: ChromaDB → documents + document_chunks

Script Python one-shot:
1. Legge tutti i chunk da ChromaDB `documenti_locale`.
2. Raggruppa per `document_id` → INSERT in `documents`.
3. Per ogni chunk → INSERT in `document_chunks` con embedding (ri-calcolato con stesso modello).
4. Verifica: `SELECT COUNT(*) = chroma_collection.count()`.

### Step 5: email_config.json → email_configs

Script Python one-shot:
1. Legge `data/email_config.json`.
2. Per ogni entry → INSERT in `email_configs`.

### Step 6: event_log backfill (opzionale)

Se serve continuità storica per i report dashboard, script che legge da `messages` storici e popola `event_log`.

---

## 6. Dipendenze

### Nuove dipendenze Python

- `pgvector` (estensione PostgreSQL) — già installabile via `CREATE EXTENSION vector`.
- `asyncpg` — già in `requirements.txt`.

### Dipendenze rimosse

| Pacchetto | Motivo |
|---|---|
| `pyairtable` | Sostituito da tabella `bookings` |
| `chromadb` | Sostituito da pgvector + `document_chunks` |

---

## 7. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Cross-tenant leak su document_chunks | Trigger `trg_check_chunk_org` a livello DB |
| Doppia source of truth event_log ↔ messages | `event_log` popolato solo da trigger, mai da codice |
| Embedding dimensione diversa dal modello | `vector(384) NOT NULL` — mismatch rilevato al primo INSERT |
| Gmail token perde isolamento tenant | Path su disco include `{organization_id}/` |
