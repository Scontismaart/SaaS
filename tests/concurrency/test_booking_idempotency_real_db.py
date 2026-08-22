"""
Test reale su Postgres (senza mock) per Difetto 3 (SEC-001):
Idempotenza del booking via vincolo DB UNIQUE / ON CONFLICT su (organization_id, source_message_id).

Verifica che:
1. Il vincolo UNIQUE su (organization_id, source_message_id) e' attivo e applicato dal DB PostgreSQL reale.
2. Due chiamate concorrenti a CoreRepository.create_booking con lo stesso source_message_id
   (eseguite in parallelo con asyncio.gather su connessioni reali separate) non creano duplicati.
3. Il DB impedisce il duplicato tramite ON CONFLICT DO NOTHING + SELECT riga esistente.
4. Entrambi i chiamanti concorrenti ricevono la riga esistente con successo, senza alcuna eccezione propagata.
5. Due booking distinte con source_message_id diversi (o per organizzazioni diverse) vengono create normalmente.
"""
import asyncio
import os
import uuid
import asyncpg
import pytest

from src.core.db.repository import CoreRepository

DB_DSN = os.environ.get(
    "TEST_DB_DSN",
    f"postgresql://{os.getenv('PGUSER', 'test')}:{os.getenv('PGPASSWORD', 'test')}@{os.getenv('PGHOST', 'localhost')}:{os.getenv('PGPORT', '55432')}/{os.getenv('PGDATABASE', 'p0_concurrency_test')}",
)

SCHEMA_DEFECT_3 = """
DROP TABLE IF EXISTS bookings CASCADE;
DROP TABLE IF EXISTS organizations CASCADE;

CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE bookings (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    contact_id UUID,
    nome_cliente TEXT NOT NULL,
    telefono TEXT NOT NULL DEFAULT '',
    data DATE NOT NULL,
    ora TIME NOT NULL,
    coperti INT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    stato TEXT NOT NULL DEFAULT 'in_attesa',
    origine TEXT NOT NULL DEFAULT 'Dashboard',
    richiede_intervento BOOLEAN NOT NULL DEFAULT FALSE,
    id_conversazione TEXT,
    richiede_deposito BOOLEAN NOT NULL DEFAULT FALSE,
    completata_at TIMESTAMPTZ,
    tipo_evento TEXT NOT NULL DEFAULT '',
    source_message_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Migration 040 reale: vincolo UNIQUE su (organization_id, source_message_id)
CREATE UNIQUE INDEX idx_bookings_source_message 
    ON bookings (organization_id, source_message_id) 
    WHERE source_message_id IS NOT NULL;
"""


@pytest.fixture
async def real_db_pool():
    pool = await asyncpg.create_pool(DB_DSN, min_size=5, max_size=20)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_DEFECT_3)
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_concurrent_booking_creation_same_source_message_id(real_db_pool):
    """Due worker lanciano create_booking simultaneamente con lo stesso source_message_id:
    esattamente una riga deve essere creata nel DB e entrambi devono ricevere la stessa riga."""
    repo = CoreRepository(pool=real_db_pool)
    org_id = uuid.uuid4()
    source_msg_id = str(uuid.uuid4())

    async with real_db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Ristorante Concorrenza')",
            org_id
        )

    # Lancio di due chiamate parallele con lo stesso source_message_id
    res1, res2 = await asyncio.gather(
        repo.create_booking(
            organization_id=org_id,
            nome_cliente="Mario Rossi Worker A",
            data="2026-09-15",
            ora="20:00",
            coperti=4,
            telefono="39333000111",
            source_message_id=source_msg_id,
        ),
        repo.create_booking(
            organization_id=org_id,
            nome_cliente="Mario Rossi Worker B",
            data="2026-09-15",
            ora="20:00",
            coperti=4,
            telefono="39333000111",
            source_message_id=source_msg_id,
        ),
    )

    # 1. Nessun errore propagato: entrambi i worker hanno un risultato valido
    assert res1 is not None, "Worker A doveva ricevere la riga di booking"
    assert res2 is not None, "Worker B doveva ricevere la riga di booking"

    # 2. Entrambi i worker puntano allo STESSO booking id
    assert res1["id"] == res2["id"], f"I due worker hanno ritornato booking differenti: {res1['id']} vs {res2['id']}"
    assert res1["source_message_id"] == source_msg_id
    assert res2["source_message_id"] == source_msg_id

    # 3. Verifica nel DB Postgres reale: esiste UNA SOLA riga in totale
    async with real_db_pool.acquire() as conn:
        total_rows = await conn.fetchval(
            "SELECT COUNT(*) FROM bookings WHERE organization_id = $1 AND source_message_id = $2",
            org_id, source_msg_id
        )
        assert total_rows == 1, f"Attesa esattamente 1 riga nel DB reale, trovate {total_rows}"


@pytest.mark.asyncio
async def test_db_enforces_unique_constraint_on_raw_duplicate_insert(real_db_pool):
    """Verifica che sia il vincolo Postgres reale a respingere INSERT duplicate dirette."""
    org_id = uuid.uuid4()
    source_msg_id = str(uuid.uuid4())

    async with real_db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Ristorante DB Enforce')",
            org_id
        )

        # Prima INSERT diretta
        await conn.execute("""
            INSERT INTO bookings (id, organization_id, nome_cliente, data, ora, coperti, source_message_id)
            VALUES ($1, $2, 'Cliente 1', '2026-09-15', '20:00', 2, $3)
        """, uuid.uuid4(), org_id, source_msg_id)

        # Seconda INSERT diretta con lo stesso source_message_id (senza ON CONFLICT)
        # DEVE sollevare UniqueViolationError a livello DB
        with pytest.raises(asyncpg.exceptions.UniqueViolationError) as exc_info:
            await conn.execute("""
                INSERT INTO bookings (id, organization_id, nome_cliente, data, ora, coperti, source_message_id)
                VALUES ($1, $2, 'Cliente 2', '2026-09-15', '20:00', 2, $3)
            """, uuid.uuid4(), org_id, source_msg_id)

        assert "idx_bookings_source_message" in str(exc_info.value), (
            f"Errore inatteso: {exc_info.value}"
        )


@pytest.mark.asyncio
async def test_different_source_message_ids_create_distinct_bookings(real_db_pool):
    """Messaggi diversi generano booking separate senza falsi positivi di deduplica."""
    repo = CoreRepository(pool=real_db_pool)
    org_id = uuid.uuid4()
    msg1 = str(uuid.uuid4())
    msg2 = str(uuid.uuid4())

    async with real_db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Ristorante Multi')",
            org_id
        )

    res1, res2 = await asyncio.gather(
        repo.create_booking(
            organization_id=org_id,
            nome_cliente="Cliente 1",
            data="2026-09-15",
            ora="19:00",
            coperti=2,
            source_message_id=msg1,
        ),
        repo.create_booking(
            organization_id=org_id,
            nome_cliente="Cliente 2",
            data="2026-09-15",
            ora="21:00",
            coperti=3,
            source_message_id=msg2,
        ),
    )

    assert res1["id"] != res2["id"]
    async with real_db_pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM bookings WHERE organization_id = $1",
            org_id
        )
        assert total == 2
