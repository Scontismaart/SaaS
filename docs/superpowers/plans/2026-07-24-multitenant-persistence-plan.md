# Multi-tenant Persistence Schema — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create DDL, repository layer, and data migration scripts for 8 new PostgreSQL tables that consolidate
all current RAM/Airtable/ChromaDB/JSON storage into a multi-tenant schema.

**Architecture:** New module `src/core/db/` with a `CoreRepository` class following the same asyncpg pattern
as `src/whatsapp/repository.py`. Migration scripts live in `scripts/` and run once (one-shot).

**Tech Stack:** asyncpg, pgvector (HNSW), testcontainers-postgres, pytest-asyncio

## Global Constraints

- PostgreSQL 16+ with `pgvector` extension
- Every table has `organization_id UUID NOT NULL REFERENCES organizations(id)`
- Every query includes `WHERE organization_id = $1`
- asyncpg (no ORM)
- Tests use `testcontainers.postgres.PostgresContainer` + `asyncpg.create_pool`
- All field names in Italian (same convention as existing `src/models/schemas.py`)

---

### Task 1: DDL migration + base repository shell

**Files:**
- Create: `src/core/db/schema.sql`
- Create: `src/core/db/__init__.py`
- Create: `src/core/db/repository.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/conftest.py`
- Create: `tests/core/test_schema.py`

**Interfaces:**
- Consumes: `organizations` table from `src/whatsapp/schema.sql`
- Produces: `CoreRepository(pool: asyncpg.Pool)` class with `__init__(self, pool)`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/core/db tests/core
```

- [ ] **Step 2: Write DDL schema.sql**

File: `src/core/db/schema.sql` — contains the full DDL from the design doc:
- `CREATE EXTENSION` for `pgcrypto` and `vector`
- `bookings` (with CHECK on stato, INDEX on org+data)
- `booking_settings` (JSONB nullable, UNIQUE org)
- `reviews` (CHECK valutazione_stelle 1-5)
- `documents` (with INDEX on org)
- `document_chunks` (vector(384) NOT NULL, HNSW index, trigger function + constraint trigger)
- `email_configs` (UNIQUE org+indirizzo)
- `usage_events` (billing_month GENERATED ALWAYS AS ...)
- `event_log` (with partial INDEX on priorita != 'bassa')
- Trigger functions: `check_chunk_org_consistency`, `log_message_event` (illustrative, to be refined)

- [ ] **Step 3: Write __init__.py**

```python
# (empty)
```

- [ ] **Step 4: Write CoreRepository shell**

```python
class CoreRepository:
    def __init__(self, pool):
        self.pool = pool
```
(with docstring referencing the design doc)

- [ ] **Step 5: Write conftest.py for core tests**

```python
import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture
async def pg_pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        with open("src/whatsapp/schema.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/schema.sql") as f:
            await conn.execute(f.read())
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
async def reset_db(pg_pool):
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            TRUNCATE TABLE
                event_log, usage_events, email_configs,
                document_chunks, documents, reviews,
                booking_settings, bookings,
                contact_consent_log, message_delivery_attempts,
                messages, conversations, contacts, whatsapp_templates,
                whatsapp_accounts, organizations
            CASCADE
        """)
```

- [ ] **Step 6: Write test_schema.py**

```python
import pytest


@pytest.mark.asyncio
async def test_schema_creates_all_tables(pg_pool):
    async with pg_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [r["table_name"] for r in rows]
    required = [
        "bookings", "booking_settings", "reviews", "documents",
        "document_chunks", "email_configs", "usage_events", "event_log",
    ]
    for t in required:
        assert t in tables, f"Missing table: {t}"
```

- [ ] **Step 7: Run tests to verify shema loads**

```bash
pytest tests/core/test_schema.py -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/core/db/ tests/core/ pytest.ini
git commit -m "feat: add multi-tenant DDL and CoreRepository shell"
```

---

### Task 2: Bookings repository + tests

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_bookings.py`

**Interfaces:**
- Produces: `CoreRepository.create_booking(org_id, data) -> dict`
- Produces: `CoreRepository.get_booking(org_id, booking_id) -> dict | None`
- Produces: `CoreRepository.list_bookings(org_id, data: str | None = None) -> list[dict]`
- Produces: `CoreRepository.update_booking_status(org_id, booking_id, stato) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_create_and_get_booking(repo, sample_org):
    data = {
        "organization_id": sample_org["id"],
        "nome_cliente": "Mario Rossi",
        "telefono": "+393912345678",
        "data": "2026-07-25",
        "ora": "20:00",
        "coperti": 4,
        "note": "Tavolo vicino alla finestra",
        "stato": "in_attesa",
        "origine": "WhatsApp",
    }
    created = await repo.create_booking(**data)
    assert created["nome_cliente"] == "Mario Rossi"
    assert created["stato"] == "in_attesa"
    assert created["coperti"] == 4

    fetched = await repo.get_booking(sample_org["id"], created["id"])
    assert fetched is not None
    assert fetched["nome_cliente"] == "Mario Rossi"


@pytest.mark.asyncio
async def test_list_bookings_by_date(repo, sample_org):
    b1 = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="A",
        data="2026-07-25", ora="20:00", coperti=2,
    )
    b2 = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="B",
        data="2026-07-25", ora="21:00", coperti=3,
    )
    b3 = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="C",
        data="2026-07-26", ora="20:00", coperti=2,
    )
    bookings_25 = await repo.list_bookings(sample_org["id"], data="2026-07-25")
    assert len(bookings_25) == 2
    all_bookings = await repo.list_bookings(sample_org["id"])
    assert len(all_bookings) == 3


@pytest.mark.asyncio
async def test_update_booking_status(repo, sample_org):
    created = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="Test",
        data="2026-07-25", ora="20:00", coperti=2,
    )
    updated = await repo.update_booking_status(
        sample_org["id"], created["id"], "confermata"
    )
    assert updated["stato"] == "confermata"
    fetched = await repo.get_booking(sample_org["id"], created["id"])
    assert fetched["stato"] == "confermata"


@pytest.mark.asyncio
async def test_booking_requires_positive_coperti(repo, sample_org):
    with pytest.raises(Exception):
        await repo.create_booking(
            organization_id=sample_org["id"], nome_cliente="Bad",
            data="2026-07-25", ora="20:00", coperti=0,
        )


@pytest.mark.asyncio
async def test_booking_cross_tenant_isolation(repo, sample_org, other_org):
    await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="Org1",
        data="2026-07-25", ora="20:00", coperti=2,
    )
    bookings_org2 = await repo.list_bookings(other_org["id"])
    assert len(bookings_org2) == 0
```

Make sure `repo` fixture is in conftest.py (returns `CoreRepository(pg_pool)`).

Add `sample_org` fixture to conftest.py:

```python
@pytest.fixture
async def sample_org(pg_pool):
    async with pg_pool.acquire() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')",
            org_id,
        )
        return {"id": org_id}


@pytest.fixture
async def other_org(pg_pool):
    async with pg_pool.acquire() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Other Org')",
            org_id,
        )
        return {"id": org_id}
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/core/test_repository_bookings.py -v
```
Expected: FAIL (methods not defined)

- [ ] **Step 3: Implement booking methods in repository.py**

```python
class CoreRepository:
    def __init__(self, pool):
        self.pool = pool

    async def create_booking(self, organization_id, nome_cliente, data, ora, coperti,
                             telefono="", note="", stato="in_attesa", origine="Dashboard",
                             richiede_intervento=False, id_conversazione=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO bookings (id, organization_id, nome_cliente, telefono,
                                      data, ora, coperti, note, stato, origine,
                                      richiede_intervento, id_conversazione)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                RETURNING *
            """, uuid.uuid4(), organization_id, nome_cliente, telefono,
            data, ora, coperti, note, stato, origine,
            richiede_intervento, id_conversazione)
            return dict(row)

    async def get_booking(self, organization_id, booking_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM bookings WHERE organization_id = $1 AND id = $2",
                organization_id, booking_id,
            )
            return dict(row) if row else None

    async def list_bookings(self, organization_id, data=None):
        async with self.pool.acquire() as conn:
            if data:
                rows = await conn.fetch(
                    "SELECT * FROM bookings WHERE organization_id = $1 AND data = $2 ORDER BY ora",
                    organization_id, data,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM bookings WHERE organization_id = $1 ORDER BY data DESC, ora",
                    organization_id,
                )
            return [dict(r) for r in rows]

    async def update_booking_status(self, organization_id, booking_id, stato):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = $3, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, stato)
            return dict(row) if row else None
```

- [ ] **Step 4: Run to verify passes**

```bash
pytest tests/core/test_repository_bookings.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/
git commit -m "feat: add bookings repository with CRUD operations"
```

---

### Task 3: Booking settings repository + tests

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_booking_settings.py`

**Interfaces:**
- Produces: `CoreRepository.get_booking_settings(org_id) -> dict | None`
- Produces: `CoreRepository.upsert_booking_settings(org_id, fasce_orarie, capienze_orarie) -> dict`

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_upsert_and_get_settings(repo, sample_org):
    fasce = [f"{h:02d}:00" for h in range(24)]
    capienze = {f: 40 for f in fasce}
    settings = await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce,
        capienze_orarie=capienze,
        slot_minutes=60,
    )
    assert settings["slot_minutes"] == 60
    assert settings["fasce_orarie"] == fasce

    fetched = await repo.get_booking_settings(sample_org["id"])
    assert fetched is not None
    assert fetched["capienze_orarie"]["12:00"] == 40


@pytest.mark.asyncio
async def test_booking_settings_unique_per_org(repo, sample_org):
    fasce = [f"{h:02d}:00" for h in range(24)]
    capienze = {f: 40 for f in fasce}
    await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce, capienze_orarie=capienze,
    )
    # upsert again should succeed (upsert, not duplicate)
    await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce, capienze_orarie={f: 30 for f in fasce},
        slot_minutes=30,
    )
    fetched = await repo.get_booking_settings(sample_org["id"])
    assert fetched["slot_minutes"] == 30
    assert fetched["capienze_orarie"]["12:00"] == 30
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/core/test_repository_booking_settings.py -v
```

- [ ] **Step 3: Implement booking settings methods**

```python
class CoreRepository:
    # ... existing methods ...

    async def get_booking_settings(self, organization_id):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM booking_settings WHERE organization_id = $1",
                organization_id,
            )
            return dict(row) if row else None

    async def upsert_booking_settings(self, organization_id, fasce_orarie, capienze_orarie,
                                       slot_minutes=60):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO booking_settings (id, organization_id, slot_minutes,
                                              fasce_orarie, capienze_orarie)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                ON CONFLICT (organization_id) DO UPDATE
                    SET slot_minutes = $3,
                        fasce_orarie = $4::jsonb,
                        capienze_orarie = $5::jsonb,
                        updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), organization_id, slot_minutes,
            json.dumps(fasce_orarie), json.dumps(capienze_orarie))
            return dict(row)
```

Add `import json` at top of repository.py.

- [ ] **Step 4: Run to verify passes**

```bash
pytest tests/core/test_repository_booking_settings.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/
git commit -m "feat: add booking settings repository with upsert"
```

---

### Task 4: Reviews repository + tests

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_reviews.py`

**Interfaces:**
- Produces: `CoreRepository.create_review(org_id, testo, ...) -> dict`
- Produces: `CoreRepository.list_reviews(org_id) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_create_and_list_reviews(repo, sample_org):
    review = await repo.create_review(
        organization_id=sample_org["id"],
        testo="Ottimo cibo, personale gentile",
        valutazione_stelle=5,
        fonte="google",
        autore="Mario Rossi",
    )
    assert review["valutazione_stelle"] == 5
    assert review["testo"] == "Ottimo cibo, personale gentile"

    reviews = await repo.list_reviews(sample_org["id"])
    assert len(reviews) == 1


@pytest.mark.asyncio
async def test_review_star_validation(repo, sample_org):
    with pytest.raises(Exception):
        await repo.create_review(
            organization_id=sample_org["id"],
            testo="Bad review",
            valutazione_stelle=6,
        )
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/core/test_repository_reviews.py -v
```

- [ ] **Step 3: Implement review methods**

```python
class CoreRepository:
    # ... existing methods ...

    async def create_review(self, organization_id, testo,
                             valutazione_stelle=None, fonte="manuale", autore="",
                             contact_id=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO reviews (id, organization_id, contact_id, testo,
                                     valutazione_stelle, fonte, autore)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
            """, uuid.uuid4(), organization_id, contact_id, testo,
            valutazione_stelle, fonte, autore)
            return dict(row)

    async def list_reviews(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM reviews WHERE organization_id = $1 ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run to verify passes**

```bash
pytest tests/core/test_repository_reviews.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/
git commit -m "feat: add reviews repository"
```

---

### Task 5: Documents + document_chunks repository (pgvector) + tests

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_documents.py`

**Interfaces:**
- Produces: `CoreRepository.create_document(org_id, nome, tipo, fonte) -> dict`
- Produces: `CoreRepository.add_chunk(org_id, document_id, chunk_index, content, embedding, metadata) -> dict`
- Produces: `CoreRepository.search_similar(org_id, embedding, k=5) -> list[dict]`
- Produces: `CoreRepository.list_documents(org_id) -> list[dict]`

- [ ] **Step 1: Write the failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_create_document_and_add_chunks(repo, sample_org):
    doc = await repo.create_document(
        organization_id=sample_org["id"],
        nome="menu_estivo.pdf",
        tipo="upload",
        fonte="dashboard",
    )
    assert doc["nome"] == "menu_estivo.pdf"

    chunk = await repo.add_chunk(
        organization_id=sample_org["id"],
        document_id=doc["id"],
        chunk_index=0,
        content="Antipasto misto della casa: 12€",
        embedding=[0.1] * 384,
        metadata={"fonte": "menu_estivo.pdf"},
    )
    assert chunk["chunk_index"] == 0
    assert chunk["content"] == "Antipasto misto della casa: 12€"


@pytest.mark.asyncio
async def test_search_similar_returns_chunks(repo, sample_org):
    doc = await repo.create_document(
        organization_id=sample_org["id"],
        nome="menu.pdf", tipo="upload",
    )
    await repo.add_chunk(
        organization_id=sample_org["id"], document_id=doc["id"],
        chunk_index=0, content="Pizza margherita: 8€",
        embedding=[0.1] * 384,
    )
    await repo.add_chunk(
        organization_id=sample_org["id"], document_id=doc["id"],
        chunk_index=1, content="Pasta carbonara: 12€",
        embedding=[0.2] * 384,
    )

    results = await repo.search_similar(
        organization_id=sample_org["id"],
        embedding=[0.15] * 384,
        k=2,
    )
    assert len(results) >= 1
    assert "Pizza" in results[0]["content"] or "Pasta" in results[0]["content"]


@pytest.mark.asyncio
async def test_document_chunk_cross_tenant_trigger(repo, sample_org, other_org):
    doc = await repo.create_document(
        organization_id=sample_org["id"],
        nome="doc1.pdf", tipo="upload",
    )
    with pytest.raises(Exception, match="organization_id mismatch"):
        await repo.add_chunk(
            organization_id=other_org["id"],  # different org!
            document_id=doc["id"],
            chunk_index=0, content="test",
            embedding=[0.1] * 384,
        )
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/core/test_repository_documents.py -v
```

- [ ] **Step 3: Implement document/chunk methods**

```python
class CoreRepository:
    # ... existing methods ...

    async def create_document(self, organization_id, nome, tipo="upload",
                               fonte="", caricato_il=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO documents (id, organization_id, nome, tipo, fonte, caricato_il)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
            """, uuid.uuid4(), organization_id, nome, tipo, fonte,
            caricato_il or "NOW()")
            return dict(row)

    async def add_chunk(self, organization_id, document_id, chunk_index,
                         content, embedding, metadata=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO document_chunks (id, organization_id, document_id,
                                             chunk_index, content, embedding, metadata)
                VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
                RETURNING *
            """, uuid.uuid4(), organization_id, document_id,
            chunk_index, content, embedding,
            json.dumps(metadata or {}))
            return dict(row)

    async def search_similar(self, organization_id, embedding, k=5):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT dc.id, dc.content, dc.metadata, dc.chunk_index,
                       dc.document_id, d.nome as document_name,
                       dc.embedding <=> $2::vector AS distance
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.organization_id = $1
                ORDER BY dc.embedding <=> $2::vector
                LIMIT $3
            """, organization_id, embedding, k)
            return [dict(r) for r in rows]

    async def list_documents(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM documents WHERE organization_id = $1 ORDER BY created_at DESC",
                organization_id,
            )
            return [dict(r) for r in rows]
```

- [ ] **Step 4: Run to verify passes**

```bash
pytest tests/core/test_repository_documents.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/
git commit -m "feat: add pgvector document repository with semantic search"
```

---

### Task 6: Email configs repository + tests

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_email_configs.py`

**Interfaces:**
- Produces: `CoreRepository.add_email_config(org_id, indirizzo) -> dict`
- Produces: `CoreRepository.list_email_configs(org_id) -> list[dict]`
- Produces: `CoreRepository.remove_email_config(org_id, indirizzo) -> bool`

- [ ] **Step 1: Write failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_add_and_list_email_configs(repo, sample_org):
    cfg = await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    assert cfg["indirizzo"] == "test@example.com"
    assert cfg["is_active"] is True

    configs = await repo.list_email_configs(sample_org["id"])
    assert len(configs) == 1


@pytest.mark.asyncio
async def test_remove_email_config(repo, sample_org):
    await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    removed = await repo.remove_email_config(sample_org["id"], "test@example.com")
    assert removed is True
    configs = await repo.list_email_configs(sample_org["id"])
    assert len(configs) == 0


@pytest.mark.asyncio
async def test_duplicate_email_config(repo, sample_org):
    await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    with pytest.raises(Exception):
        await repo.add_email_config(
            organization_id=sample_org["id"],
            indirizzo="test@example.com",
        )


@pytest.mark.asyncio
async def test_email_config_org_isolation(repo, sample_org, other_org):
    await repo.add_email_config(
        organization_id=sample_org["id"],
        indirizzo="test@example.com",
    )
    configs = await repo.list_email_configs(other_org["id"])
    assert len(configs) == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/core/test_repository_email_configs.py -v
```

- [ ] **Step 3: Implement email config methods**

```python
class CoreRepository:
    # ... existing methods ...

    async def add_email_config(self, organization_id, indirizzo, is_active=True):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO email_configs (id, organization_id, indirizzo, is_active)
                VALUES ($1, $2, $3, $4)
                RETURNING *
            """, uuid.uuid4(), organization_id, indirizzo, is_active)
            return dict(row)

    async def list_email_configs(self, organization_id):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM email_configs WHERE organization_id = $1 ORDER BY created_at",
                organization_id,
            )
            return [dict(r) for r in rows]

    async def remove_email_config(self, organization_id, indirizzo):
        async with self.pool.acquire() as conn:
            result = await conn.execute("""
                DELETE FROM email_configs
                WHERE organization_id = $1 AND indirizzo = $2
            """, organization_id, indirizzo)
            return result != "DELETE 0"
```

- [ ] **Step 4: Run to verify passes**

```bash
pytest tests/core/test_repository_email_configs.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/
git commit -m "feat: add email configs repository"
```

---

### Task 7: Usage events repository + tests

**Files:**
- Modify: `src/core/db/repository.py`
- Create: `tests/core/test_repository_usage.py`

**Interfaces:**
- Produces: `CoreRepository.record_usage(org_id, event_type, quantity, metadata) -> dict`
- Produces: `CoreRepository.get_usage_by_month(org_id, year, month) -> list[dict]`
- Produces: `CoreRepository.get_usage_summary(org_id, year, month) -> dict`

- [ ] **Step 1: Write failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_record_and_query_usage(repo, sample_org):
    event = await repo.record_usage(
        organization_id=sample_org["id"],
        event_type="message_sent",
        quantity=1,
        metadata={"conversation_id": "conv-1"},
    )
    assert event["event_type"] == "message_sent"
    assert event["billing_month"] is not None

    events = await repo.get_usage_by_month(sample_org["id"], 2026, 7)
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_usage_summary(repo, sample_org):
    for i in range(3):
        await repo.record_usage(
            organization_id=sample_org["id"],
            event_type="message_sent",
            quantity=1,
        )
    await repo.record_usage(
        organization_id=sample_org["id"],
        event_type="ai_response",
        quantity=2,
    )
    summary = await repo.get_usage_summary(sample_org["id"], 2026, 7)
    assert summary["message_sent"] == 3
    assert summary["ai_response"] == 2
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/core/test_repository_usage.py -v
```

- [ ] **Step 3: Implement usage event methods**

```python
class CoreRepository:
    # ... existing methods ...

    async def record_usage(self, organization_id, event_type, quantity=1,
                            metadata=None):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO usage_events (id, organization_id, event_type,
                                          quantity, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                RETURNING *
            """, uuid.uuid4(), organization_id, event_type, quantity,
            json.dumps(metadata or {}))
            return dict(row)

    async def get_usage_by_month(self, organization_id, year, month):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM usage_events
                WHERE organization_id = $1
                  AND billing_month = $2::date
                ORDER BY created_at
            """, organization_id, f"{year}-{month:02d}-01")
            return [dict(r) for r in rows]

    async def get_usage_summary(self, organization_id, year, month):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT event_type, SUM(quantity)::int as total
                FROM usage_events
                WHERE organization_id = $1
                  AND billing_month = $2::date
                GROUP BY event_type
            """, organization_id, f"{year}-{month:02d}-01")
            return {r["event_type"]: r["total"] for r in rows}
```

- [ ] **Step 4: Run to verify passes**

```bash
pytest tests/core/test_repository_usage.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/
git commit -m "feat: add usage events repository with monthly billing queries"
```

---

### Task 8: Event log trigger function

**Files:**
- Create: `src/core/db/triggers.sql`
- Create: `tests/core/test_triggers_event_log.py`

**Note:** event_log is populated by DB triggers only (never by application code).
This task defines and tests the trigger functions.

- [ ] **Step 1: Write triggers.sql**

```sql
-- Function: log handled inbound messages
CREATE OR REPLACE FUNCTION log_message_event() RETURNS trigger AS $$
BEGIN
  IF NEW.direction = 'inbound' AND NEW.status = 'handled' THEN
    INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                           testo_originale, gestito_da_ai, dettagli)
    VALUES (
      NEW.organization_id, 'messages', NEW.id, 'messaggio',
      CASE WHEN NEW.handling_type = 'escalated' THEN 'alta' ELSE 'media' END,
      NEW.content_text,
      NEW.handling_type = 'ai_handled',
      jsonb_build_object('conversation_id', NEW.conversation_id, 'handling_type', NEW.handling_type)
    );
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_message_event ON messages;
CREATE TRIGGER trg_log_message_event
    AFTER INSERT OR UPDATE OF status ON messages
    FOR EACH ROW EXECUTE FUNCTION log_message_event();

-- Function: log new reviews
CREATE OR REPLACE FUNCTION log_review_event() RETURNS trigger AS $$
BEGIN
  INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita,
                         testo_originale, gestito_da_ai, dettagli)
  VALUES (
    NEW.organization_id, 'reviews', NEW.id, 'recensione',
    CASE WHEN NEW.valutazione_stelle IS NOT NULL AND NEW.valutazione_stelle <= 2 THEN 'alta' ELSE 'bassa' END,
    NEW.testo,
    TRUE,
    jsonb_build_object('valutazione_stelle', NEW.valutazione_stelle, 'fonte', NEW.fonte)
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_log_review_event ON reviews;
CREATE TRIGGER trg_log_review_event
    AFTER INSERT ON reviews
    FOR EACH ROW EXECUTE FUNCTION log_review_event();
```

- [ ] **Step 2: Update conftest.py to load triggers.sql**

```python
# In the pg_pool fixture, after the two schema files:
with open("src/core/db/triggers.sql") as f:
    await conn.execute(f.read())
```

- [ ] **Step 3: Write failing test**

```python
import pytest


@pytest.mark.asyncio
async def test_message_event_triggers_event_log(repo, sample_org, sample_contact):
    # Insert a handled inbound message directly
    async with repo.pool.acquire() as conn:
        conv_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO conversations (id, organization_id, contact_id, status)
            VALUES ($1, $2, $3, 'active')
        """, conv_id, sample_org["id"], sample_contact["id"])

        msg_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO messages (id, organization_id, conversation_id, direction,
                                  message_type, content, content_text, status, handling_type)
            VALUES ($1, $2, $3, 'inbound', 'text', '{"text":"test"}'::jsonb, 'test message',
                    'received_pending_ai', NULL)
        """, msg_id, sample_org["id"], conv_id)

        # Update to handled — should trigger event_log insert
        await conn.execute("""
            UPDATE messages SET status = 'handled', handling_type = 'ai_handled'
            WHERE id = $1
        """, msg_id)

    # Check event_log
    async with repo.pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT * FROM event_log WHERE organization_id = $1 ORDER BY created_at",
            sample_org["id"],
        )
    assert len(events) >= 1
    assert events[0]["source_table"] == "messages"
    assert events[0]["tipo_evento"] == "messaggio"


@pytest.mark.asyncio
async def test_review_event_triggers_event_log(repo, sample_org):
    await repo.create_review(
        organization_id=sample_org["id"],
        testo="Bad food",
        valutazione_stelle=1,
        fonte="google",
    )
    async with repo.pool.acquire() as conn:
        events = await conn.fetch(
            "SELECT * FROM event_log WHERE organization_id = $1",
            sample_org["id"],
        )
    assert len(events) >= 1
    assert events[0]["source_table"] == "reviews"
```

Add `sample_contact` fixture:

```python
@pytest.fixture
async def sample_contact(pg_pool, sample_org):
    async with pg_pool.acquire() as conn:
        contact_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO contacts (id, organization_id, phone_number)
            VALUES ($1, $2, 'test@example.com')
        """, contact_id, sample_org["id"])
        return {"id": contact_id}
```

- [ ] **Step 4: Run to verify failure**

```bash
pytest tests/core/test_triggers_event_log.py -v
```
Expected: FAIL (trigger functions not loaded yet)

- [ ] **Step 5: Run with triggers loaded**

The conftest already loads `triggers.sql` (updated in step 2).

```bash
pytest tests/core/test_triggers_event_log.py -v
```
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/db/triggers.sql tests/core/
git commit -m "feat: add event_log trigger functions for messages and reviews"
```

---

### Task 9: Migration scripts (one-shot)

**Files:**
- Create: `scripts/migrate_airtable_to_bookings.py`
- Create: `scripts/migrate_chromadb_to_pgvector.py`
- Create: `scripts/migrate_email_configs.py`
- Create: `scripts/README.md`

**Note:** These are one-shot scripts, not production code. They run once and are then archived.

- [ ] **Step 1: Write migrate_airtable_to_bookings.py**

```python
#!/usr/bin/env python3
"""One-shot migration: Airtable → bookings table.

Usage: python scripts/migrate_airtable_to_bookings.py <organization_id>

Reads all records from Airtable Prenotazioni table, transforms them to
bookings rows, and bulk-inserts into PostgreSQL.
"""

import argparse
import asyncio
import os
import uuid

import asyncpg
from pyairtable import Api

from src.models.schemas import PrenotazioneCalendario


def fetch_airtable_bookings() -> list[dict]:
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    table_name = os.getenv("AIRTABLE_TABLE_NAME", "Prenotazioni")
    if not api_key or not base_id:
        print("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set")
        return []
    api = Api(api_key)
    table = api.table(base_id, table_name)
    records = table.all()
    result = []
    for r in records:
        fields = r.get("fields", {})
        data = fields.get("Data prenotazione") or ""
        ora = ""
        ora_pren = fields.get("Ora prenotazione") or ""
        if isinstance(ora_pren, str) and "T" in ora_pren:
            data = data or ora_pren[:10]
            ora = ora_pren[11:16]
        elif isinstance(ora_pren, str):
            ora = ora_pren[:5]
        result.append({
            "nome_cliente": fields.get("Nome cliente", ""),
            "telefono": fields.get("Telefono", ""),
            "data": data,
            "ora": ora,
            "coperti": fields.get("Numero coperti"),
            "note": fields.get("Note", ""),
            "stato": fields.get("Stato", "in_attesa").lower().replace(" ", "_"),
            "origine": fields.get("Origine", "Airtable"),
            "richiede_intervento": bool(fields.get("Richiesta umano", False)),
            "id_conversazione": fields.get("ID conversazione"),
        })
    return result


async def insert_bookings(pool, org_id, bookings: list[dict]):
    async with pool.acquire() as conn:
        for b in bookings:
            await conn.execute("""
                INSERT INTO bookings (id, organization_id, nome_cliente, telefono,
                                      data, ora, coperti, note, stato, origine,
                                      richiede_intervento, id_conversazione)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT DO NOTHING
            """, uuid.uuid4(), org_id, b["nome_cliente"], b["telefono"],
            b["data"] or None, b["ora"] or None, b["coperti"],
            b["note"], b["stato"], b["origine"],
            b["richiede_intervento"], b["id_conversazione"])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("organization_id", type=uuid.UUID)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))
    args = parser.parse_args()

    print("Fetching Airtable bookings...")
    bookings = fetch_airtable_bookings()
    print(f"Found {len(bookings)} records")

    if not bookings:
        return

    pool = await asyncpg.create_pool(dsn=args.dsn)
    try:
        await insert_bookings(pool, args.organization_id, bookings)
        print(f"Inserted {len(bookings)} bookings")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Write migrate_chromadb_to_pgvector.py**

```python
#!/usr/bin/env python3
"""One-shot migration: ChromaDB → documents + document_chunks.

Usage: python scripts/migrate_chromadb_to_pgvector.py <organization_id>

Reads all chunks from ChromaDB `documenti_locale` collection, creates
document records, and inserts chunks with embeddings into pgvector.
"""

import argparse
import asyncio
import os
import uuid
from collections import defaultdict

import asyncpg
import chromadb
from chromadb.config import Settings


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("organization_id", type=uuid.UUID)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))
    args = parser.parse_args()

    persist = os.path.join("data", "chroma")
    client = chromadb.PersistentClient(
        path=os.path.abspath(persist),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(name="documenti_locale")
    all_data = collection.get(include=["documents", "metadatas", "embeddings"])
    if not all_data["ids"]:
        print("No data in ChromaDB collection")
        return

    # Group by document/fonte
    doc_chunks = defaultdict(list)
    for i, doc_id in enumerate(all_data["ids"]):
        meta = (all_data["metadatas"] or [{}])[i] or {}
        fonte = meta.get("fonte") or "documento"
        doc_key = meta.get("document_id") or f"legacy:{fonte}"
        doc_chunks[doc_key].append({
            "chunk_id": doc_id,
            "content": (all_data["documents"] or [""])[i],
            "embedding": (all_data["embeddings"] or [[]])[i],
            "metadata": meta,
        })

    pool = await asyncpg.create_pool(dsn=args.dsn)
    try:
        async with pool.acquire() as conn:
            for doc_key, chunks in doc_chunks.items():
                fonte = chunks[0]["metadata"].get("fonte") or "documento"
                doc_uuid = uuid.uuid4()
                await conn.execute("""
                    INSERT INTO documents (id, organization_id, nome, tipo, fonte, caricato_il)
                    VALUES ($1, $2, $3, 'upload', $4, NOW())
                """, doc_uuid, args.organization_id, fonte, fonte)

                for chunk in chunks:
                    await conn.execute("""
                        INSERT INTO document_chunks (id, organization_id, document_id,
                                                     chunk_index, content, embedding, metadata)
                        VALUES ($1, $2, $3, $4, $5, $6::vector, $7::jsonb)
                    """, uuid.uuid4(), args.organization_id, doc_uuid,
                    chunk["chunk_id"], chunk["content"], chunk["embedding"],
                    "{}")

        print(f"Migrated {len(all_data['ids'])} chunks from {len(doc_chunks)} documents")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Write migrate_email_configs.py**

```python
#!/usr/bin/env python3
"""One-shot migration: email_config.json → email_configs table.

Usage: python scripts/migrate_email_configs.py <organization_id>
"""

import argparse
import json
import os
import uuid
import asyncio
import asyncpg


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("organization_id", type=uuid.UUID)
    parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))
    parser.add_argument("--config-path", default="data/email_config.json")
    args = parser.parse_args()

    if not os.path.exists(args.config_path):
        print(f"No config file found at {args.config_path}")
        return

    with open(args.config_path) as f:
        configs = json.load(f)

    pool = await asyncpg.create_pool(dsn=args.dsn)
    try:
        async with pool.acquire() as conn:
            for cfg in configs:
                await conn.execute("""
                    INSERT INTO email_configs (id, organization_id, indirizzo)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (organization_id, indirizzo) DO NOTHING
                """, uuid.uuid4(), args.organization_id, cfg["indirizzo"])
        print(f"Migrated {len(configs)} email configs")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Write scripts/README.md**

```markdown
# Migration Scripts

One-shot scripts for migrating data from legacy storage to PostgreSQL multi-tenant schema.

## Order

1. `migrate_airtable_to_bookings.py <org_id>`
2. `migrate_chromadb_to_pgvector.py <org_id>`
3. `migrate_email_configs.py <org_id>`

## Prerequisites

- PostgreSQL with multi-tenant schema applied (see `src/core/db/schema.sql`)
- Environment variables:
  - `POSTGRES_DSN` — PostgreSQL connection string
  - `AIRTABLE_API_KEY` (for bookings migration)
  - `AIRTABLE_BASE_ID` (for bookings migration)
- ChromaDB data directory at `data/chroma/` (for documents migration)
- Email config at `data/email_config.json` (for email configs migration)

## Verification

After each migration, verify row counts match:

```sql
SELECT COUNT(*) FROM bookings;
SELECT COUNT(*) FROM documents;
SELECT COUNT(*) FROM document_chunks;
SELECT COUNT(*) FROM email_configs;
```
```

- [ ] **Step 5: Commit**

```bash
git add scripts/
git commit -m "feat: add one-shot data migration scripts from legacy storage"
```

---
