# Migration Idempotency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Far sì che `schema.sql + triggers + TUTTE le migrazioni in ordine` applichino pulite su un DB fresco, eliminando la classe di bug emersa in PR #31 (conftest con lista esplicita fuori sync; 042 non idempotente; workflow "Migration check" mai eseguito e con psql non-strict).

**Architecture:** Un solo principio: **ogni migrazione deve essere ri-applicabile senza errori su un DB già inizializzato con `schema.sql`** (che è lo snapshot della struttura corrente). Questo rende equivalenti il conftest dei test e `migrations.yml` e permette di sostituire la lista esplicita del conftest con un glob ordinato — eliminando per sempre la classe "column does not exist"/"already exists" vista in CI. `042` è l'unica migrazione non idempotente confermata (029/040 già usano `IF NOT EXISTS`, 043 usa un DO-block guardato, 014 usa `CREATE INDEX IF NOT EXISTS`). In più: `psql -v ON_ERROR_STOP=1` in `migrations.yml` (oggi gli errori vengono ignorati) e trigger anche sui `pull_request`, così il workflow valida le PR toccando le migrazioni PRIMA del merge su main.

**Tech Stack:** SQL (PostgreSQL 16, image pgvector/pgvector:0.7.4), GitHub Actions, pytest con `tests/core/conftest.py` (pg_pool).

**Spec:** Analisi CI PR #31 — commit `09f5e68`: 319 errori da `DuplicateColumnError: column "sent_at" of relation "messages" already exists` (042 vs `src/whatsapp/schema.sql:58`); workflow `migrations.yml` con `on.push.branches: [main]` mai storicamente eseguito; `psql -f` senza `ON_ERROR_STOP` maschera gli errori.

## Global Constraints

- NESSUNA modifica al significato semantico delle migrazioni esistenti: solo idempotenza sintattica (`IF NOT EXISTS`, guardie DO-block). Nessuna colonna/tabella/policy rinominata o rimossa.
- Nessun cambio di schema per la produzione: il DB live (Supabase) ha già tutte le strutture; le migrazioni modificate devono restare no-op lì (verificato dopo il deploy con lo stesso criterio `ADD COLUMN IF NOT EXISTS`).
- Il conftest deve restare deterministico: glob ordinato per nome (`0*.sql` sorted), stesso ordine di `migrations.yml`.
- Le eccezioni tollerate restano solo quelle già tollerate (024 hnsw opzionale).

---

### Task 1: `042_messages_state_machine.sql` idempotente

**Files:**
- Modify: `src/core/db/migrations/042_messages_state_machine.sql`
- Verifica: workflow `Migration check` (green) + suite DB in `ci.yml`

**Interfaces:**
- Consumes: nulla.
- Produces: nessun cambio di schema; le 8 colonne (`billed_at`, `ai_reply_cache`, `ai_reply_generated_at`, `sent_at`, `meta_message_id`, `quota_exceeded_at`, `processing_at`) diventano `ADD COLUMN IF NOT EXISTS`.

- [ ] **Step 1: Statistico del file attuale**

Run: `grep -nE "ADD COLUMN" src/core/db/migrations/042_messages_state_machine.sql`
Expected: 8 righe `ADD COLUMN <nome> <tipo>,?` senza `IF NOT EXISTS`.

- [ ] **Step 2: Trasformare ogni ADD COLUMN**

Sostituire l'ALTER TABLE multi-colonna con una riga per colonna, tutte con `IF NOT EXISTS` (l'ALTER multi-colonna con IF NOT EXISTS misto è illeggibile; una riga per colonna è anche diff-friendly):

```sql
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS billed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ai_reply_cache JSONB,
    ADD COLUMN IF NOT EXISTS ai_reply_generated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS meta_message_id VARCHAR(255),
    ADD COLUMN IF NOT EXISTS quota_exceeded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS processing_at TIMESTAMPTZ;
```

(NOTA: controllare i tipi originali riga per riga e replicarli ESATTAMENTE; il blocco sopra riflette lo stato attuale del file. Se il file contiene altre colonne, aggiungerle allo stesso modo.)

Se il file contiene anche l'ALTER commentato su `bookings.source_message_id` (riga 12) lasciarlo commentato così com'è.

- [ ] **Step 3: Verifica sintattica locale**

Run: `python -c "open('src/core/db/migrations/042_messages_state_machine.sql', encoding='utf-8').read()" && grep -c "ADD COLUMN IF NOT EXISTS" src/core/db/migrations/042_messages_state_machine.sql`
Expected: conteggio = numero colonne del file (8).

- [ ] **Step 4: Commit**

```bash
git add src/core/db/migrations/042_messages_state_machine.sql
git commit -m "fix(migrations): 042 idempotente con ADD COLUMN IF NOT EXISTS"
```

---

### Task 2: conftest test DB → glob ordinato

**Files:**
- Modify: `tests/core/conftest.py` (fixture `pg_pool`)

**Interfaces:**
- Consumes: migrazioni tutte idempotenti (Task 1).
- Produces: il test DB applica `0*.sql` in ordine numerico — stesso contratto di `migrations.yml`; nessun'altra fixture cambia firma.

- [ ] **Step 1: Sostituire la lista esplicita con il glob**

Sostituire l'intera sequenza di `with open("src/core/db/migrations/0XX...")` nel fixture `pg_pool` (da 002 fino a 045) con:

```python
        # Tutte le migrazioni in ordine numerico (stessa policy di
        # migrations.yml, che ora gira anche sulle PR con ON_ERROR_STOP).
        # La lista esplicita era andata fuori sync col repo producendo
        # errori "column does not exist" (PR #31).
        for sql_path in sorted(glob.glob("src/core/db/migrations/0*.sql")):
            with open(sql_path, encoding="utf-8") as f:
                await conn.execute(f.read())
```

Con `import glob` in testa al file. Rimuovere anche le letture modulo-level di 036/037 (`_WEEKLY_REPORT_LOG_SQL`/`_STATUS`) se non usate altrove, poiché 036/037 vengono ora applicate dal glob.

- [ ] **Step 2: Compilazione**

Run: `python -m py_compile tests/core/conftest.py`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add tests/core/conftest.py
git commit -m "test(db): conftest applica tutte le migrazioni in ordine (glob)"
```

---

### Task 3: `migrations.yml` strict + gate sulle PR

**Files:**
- Modify: `.github/workflows/migrations.yml`

**Interfaces:**
- Consumes: migrazioni idempotenti (Task 1), conftest glob (Task 2) come seconda rete di verifica in `ci.yml`.
- Produces: `Migration check` eseguito su ogni PR che tocca `migrations/`, `schema.sql`, `triggers.sql`; fallisce al primo errore SQL.

- [ ] **Step 1: Trigger su pull_request**

```yaml
on:
  push:
    branches: [main]
    paths:
      - "src/core/db/migrations/*.sql"
      - "src/core/db/schema.sql"
      - "src/core/db/triggers.sql"
      - "src/whatsapp/schema.sql"
  pull_request:
    paths:
      - "src/core/db/migrations/*.sql"
      - "src/core/db/schema.sql"
      - "src/core/db/triggers.sql"
      - "src/whatsapp/schema.sql"
```

- [ ] **Step 2: ON_ERROR_STOP su ogni invocazione psql**

Ogni comando `psql` nel workflow diventa:

```bash
PGPASSWORD=test psql -v ON_ERROR_STOP=1 -h localhost -U postgres -d test -f <file>
```

Anche il loop "Apply all migrations in order":

```bash
for f in $(ls src/core/db/migrations/0*.sql | sort); do
  echo "--- Applying $f ---"
  PGPASSWORD=test psql -v ON_ERROR_STOP=1 -h localhost -U postgres -d test -f "$f"
done
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/migrations.yml
git commit -m "ci(migrations): ON_ERROR_STOP=1 e trigger anche su pull_request"
```

---

### Task 4: Verifica end-to-end su CI

- [ ] **Step 1: Push del branch e apertura PR**

Run: `git push -u origin fix/migration-idempotency` + apertura PR verso `main`.
Expected: partono `CI` (con conftest glob sui test DB) e `Migration check` (strict, fresh DB).

- [ ] **Step 2: Green su entrambi i workflow**

Expected: `Migration check` verde = la pipeline "schema.sql + tutte le migrazioni" applica pulita; `CI` verde = i test girano sullo schema completo. Se `Migration check` scopre ulteriori duplicati latenti (non emersi nell'audit statico), correggerli con lo stesso criterio `IF NOT EXISTS`/guardie, un commit per migrazione.

- [ ] **Step 3: Code review**

Skill requesting-code-review: reviewer sul diff del branch (migrations 042, conftest, migrations.yml), DESCRIPTION = questo piano.

---

## No-Go / Rischi noti

- `reset_db` in conftest TRUNCA una lista fissa di tabelle: se qualche migrazione crea tabelle nuove non in lista, i test che si aspettano pulizia fallirebbero — oggi nessuna migrazione aggiunge tabelle nuove (verificato: 029/040/042/043 solo ALTER/INDEX/POLICY).
- `psql -f` esegue l'intero file in una transazione implicita per statement: con ON_ERROR_STOP un fallimento a metà file lascia applicate le statement precedenti — accettabile per DB efimeri di CI (vengono ricreati a ogni run).
