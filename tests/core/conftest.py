import asyncpg
import pytest
import uuid
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer(image="pgvector/pgvector:0.7.4-pg16") as pg:
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
        with open("src/core/db/triggers.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/002_auth_tables.sql") as f:
            await conn.execute(f.read())
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
async def reset_db(pg_pool):
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            TRUNCATE TABLE
                audit_log, user_profiles, organization_memberships,
                event_log, usage_events, email_configs,
                document_chunks, documents, reviews,
                booking_settings, bookings,
                contact_consent_log, message_delivery_attempts,
                messages, conversations, contacts, whatsapp_templates,
                whatsapp_accounts, organizations
            CASCADE
        """)


@pytest.fixture
async def repo(pg_pool):
    from src.core.db.repository import CoreRepository
    return CoreRepository(pool=pg_pool)


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
async def sample_contact(pg_pool, sample_org):
    async with pg_pool.acquire() as conn:
        contact_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO contacts (id, organization_id, phone_number)
            VALUES ($1, $2, 'test@example.com')
        """, contact_id, sample_org["id"])
        return {"id": contact_id}


@pytest.fixture
async def other_org(pg_pool):
    async with pg_pool.acquire() as conn:
        org_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Other Org')",
            org_id,
        )
        return {"id": org_id}
