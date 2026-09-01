import glob
import os

os.environ.setdefault("TC_HOST", "localhost")

import asyncpg
import pytest
import uuid

CI = os.getenv("CI")

_dsn = os.getenv(
    "TEST_DB_DSN",
    f"postgresql://{os.getenv('PGUSER','test')}"
    f":{os.getenv('PGPASSWORD','test')}"
    f"@{os.getenv('PGHOST','localhost')}"
    f":{os.getenv('PGPORT','55432')}"
    f"/{os.getenv('PGDATABASE','p0_concurrency_test')}"
)

@pytest.fixture(scope="session")
def postgres_container():
    class _FakeContainer:
        @staticmethod
        def get_connection_url():
            return _dsn
    return _FakeContainer()


@pytest.fixture
async def pg_pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
    pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=2,
        max_size=10,
        server_settings={"search_path": "public, extensions"},
    )
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE SCHEMA IF NOT EXISTS auth;
            CREATE TABLE IF NOT EXISTS auth.users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                email TEXT
            );
            CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid AS $$
                SELECT NULL::uuid
            $$ LANGUAGE sql STABLE;
            CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb AS $$
                SELECT '{}'::jsonb
            $$ LANGUAGE sql STABLE;
            
            DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                    CREATE ROLE anon;
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'authenticated') THEN
                    CREATE ROLE authenticated;
                END IF;
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'service_role') THEN
                    CREATE ROLE service_role;
                END IF;
            END $$;
            DROP SCHEMA IF EXISTS public CASCADE;
            CREATE SCHEMA public;
        """)
        with open("src/whatsapp/schema.sql", encoding="utf-8") as f:
            await conn.execute(f.read())
        with open("src/core/db/schema.sql", encoding="utf-8") as f:
            await conn.execute(f.read())
        with open("src/core/db/triggers.sql", encoding="utf-8") as f:
            await conn.execute(f.read())
        # Tutte le migrazioni in ordine numerico (stessa policy di
        # migrations.yml): la lista esplicita qui andava fuori sync col repo
        # e produceva errori tipo "column does not exist" nei test.
        for sql_path in sorted(glob.glob("src/core/db/migrations/0*.sql")):
            with open(sql_path, encoding="utf-8") as f:
                sql = f.read()
            try:
                await conn.execute(sql)
            except (asyncpg.UndefinedObjectError, asyncpg.DuplicateObjectError) as exc:
                # Es. 024 (hnsw) se l'ambiente non supporta l'indice:
                # migrazione facoltativa, non blocca la suite.
                if "024_hnsw" in sql_path:
                    continue
                raise
    yield pool
    await pool.close()


@pytest.fixture
async def reset_db(pg_pool):
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            TRUNCATE TABLE
                audit_log, user_profiles, organization_memberships,
                event_log, usage_events, email_configs,
                document_chunks, documents, reviews,
                booking_settings, bookings,
                onboarding_profiles,
                contact_consent_log, message_delivery_attempts,
                messages, conversations, contacts, whatsapp_templates,
                whatsapp_accounts, organizations,
                instagram_accounts,
                faq_cache, message_feedback,
                processed_stripe_events,
                webhook_idempotency,
                google_calendar_credentials,
                google_business_credentials,
                oauth_nonces,
                outbound_dedup,
                weekly_report_log
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
