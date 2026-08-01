import os

os.environ.setdefault("TC_HOST", "localhost")

import asyncpg
import pytest
import uuid

CI = os.getenv("CI")

if CI:
    _dsn = (
        f"postgresql://{os.getenv('PGUSER','postgres')}"
        f":{os.getenv('PGPASSWORD','test')}"
        f"@{os.getenv('PGHOST','localhost')}"
        f":{os.getenv('PGPORT','5432')}"
        f"/{os.getenv('PGDATABASE','test')}"
    )

    @pytest.fixture(scope="session")
    def postgres_container():
        class _FakeContainer:
            @staticmethod
            def get_connection_url():
                return _dsn
        return _FakeContainer()
else:
    from testcontainers.postgres import PostgresContainer

    @pytest.fixture(scope="session")
    def postgres_container():
        with PostgresContainer(image="pgvector/pgvector:0.7.4-pg16") as pg:
            yield pg


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
        """)
        with open("src/whatsapp/schema.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/schema.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/triggers.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/002_auth_tables.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/003_billing.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/004_gdpr.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/005_gdpr_consent.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/006_hitl.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/007_booking_standalone.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/010_dead_letter.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/012_reply_guard.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/013_webhook_idempotency.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/014_contact_fk_strategy.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/015_org_fk_strategy.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/016_org_timezone.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/017_advisor_followup.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/018_advisor_followup_2.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/019_google_calendar_credentials.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/020_add_google_event_id.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/021_oauth_nonces.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/022_reviews_ext.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/023_fix_review_priority_trigger.sql") as f:
            await conn.execute(f.read())
        # 024 e' opzionale (hnsw index): se pgvector non supporta hnsw,
        # ignoriamo l'errore senza bloccare i test.
        try:
            with open("src/core/db/migrations/024_hnsw_index.sql") as f:
                await conn.execute(f.read())
        except asyncpg.UndefinedObjectError:
            pass
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
                contact_consent_log, message_delivery_attempts,
                messages, conversations, contacts, whatsapp_templates,
                whatsapp_accounts, organizations,
                processed_stripe_events,
                webhook_idempotency,
                google_calendar_credentials,
                oauth_nonces
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
