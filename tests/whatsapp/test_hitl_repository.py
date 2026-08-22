import uuid
import asyncpg
import pytest


pytestmark = pytest.mark.usefixtures("reset_db")


@pytest.fixture
async def extended_pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        with open("src/whatsapp/schema.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/004_gdpr.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/005_gdpr_consent.sql") as f:
            await conn.execute(f.read())
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
        with open("src/core/db/migrations/002_auth_tables.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/006_hitl.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/027_sla.sql") as f:
            await conn.execute(f.read())
        await conn.execute("""
            DROP TABLE IF EXISTS event_log CASCADE;
            CREATE TABLE event_log (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                organization_id UUID NOT NULL,
                source_table    TEXT NOT NULL,
                source_id       UUID NOT NULL,
                tipo_evento     TEXT NOT NULL,
                priorita        TEXT NOT NULL,
                testo_originale TEXT NOT NULL DEFAULT '',
                risposta_ai     TEXT NOT NULL DEFAULT '',
                gestito_da_ai   BOOLEAN NOT NULL DEFAULT TRUE,
                dettagli        JSONB NOT NULL DEFAULT '{}',
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
async def reset_db():
    pass  # Override conftest's reset_db — we use our own


@pytest.fixture(autouse=True)
async def reset_extended_db(extended_pool):
    async with extended_pool.acquire() as conn:
        await conn.execute("""
            TRUNCATE TABLE
                audit_log, user_profiles, organization_memberships,
                contact_consent_log, message_delivery_attempts,
                messages, conversations, contacts, whatsapp_templates,
                whatsapp_accounts, organizations
            CASCADE
        """)


@pytest.fixture
async def repo(extended_pool):
    from src.whatsapp.repository import Repository
    return Repository(pool=extended_pool)


class TestTicketRepository:
    async def _create_test_data(self, repo):
        async with repo.pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'HITL Test') RETURNING id",
                uuid.uuid4()
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234567') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id, ticket_status, version",
                uuid.uuid4(), org["id"], contact["id"]
            )
        return org, contact, conv

    async def _create_staff(self, repo, org_id, ruolo="staff"):
        async with repo.pool.acquire() as conn:
            auth_user = await conn.fetchrow(
                "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                f"staff_{uuid.uuid4().hex[:8]}@test.com"
            )
            # Trigger auto-creates user_profiles; fetch it
            profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE auth_user_id = $1",
                auth_user["id"]
            )
            await conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, $3)",
                org_id, profile["id"], ruolo
            )
        return str(profile["id"])

    async def test_list_tickets_empty(self, repo):
        tickets = await repo.list_tickets(str(uuid.uuid4()))
        assert tickets == []

    async def test_list_tickets_by_status(self, repo):
        org, _, conv = await self._create_test_data(repo)
        tickets = await repo.list_tickets(str(org["id"]), status="AI_ACTIVE")
        assert len(tickets) == 1
        assert tickets[0]["id"] == conv["id"]

    async def test_list_tickets_filters_status(self, repo):
        org, _, _ = await self._create_test_data(repo)
        tickets = await repo.list_tickets(str(org["id"]), status="PENDING_STAFF")
        assert tickets == []

    async def test_get_conversation_found(self, repo):
        org, _, conv = await self._create_test_data(repo)
        result = await repo.get_conversation(str(conv["id"]), str(org["id"]))
        assert result is not None
        assert result["id"] == conv["id"]
        assert result["ticket_status"] == "AI_ACTIVE"
        assert result["version"] == 1

    async def test_get_conversation_not_found(self, repo):
        result = await repo.get_conversation(str(uuid.uuid4()), str(uuid.uuid4()))
        assert result is None

    async def test_escalate_to_human_success(self, repo):
        org, _, conv = await self._create_test_data(repo)
        result = await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        assert result is not None
        assert result["ticket_status"] == "PENDING_STAFF"
        assert result["pending_staff_at"] is not None
        assert result["version"] == 2

    async def test_escalate_to_human_already_escalated(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        result = await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        assert result is None

    async def test_claim_ticket_success(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        staff_id = await self._create_staff(repo, org["id"])
        result = await repo.claim_ticket(str(conv["id"]), staff_id, expected_version=2, organization_id=str(org["id"]))
        assert result is not None
        assert result["ticket_status"] == "CLAIMED"
        assert str(result["assigned_to"]) == staff_id
        assert result["claimed_at"] is not None
        assert result["version"] == 3

    async def test_claim_ticket_optimistic_lock_fail(self, repo):
        org, _, conv = await self._create_test_data(repo)
        other_id = await self._create_staff(repo, org["id"])
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        result = await repo.claim_ticket(str(conv["id"]), other_id, expected_version=1, organization_id=str(org["id"]))
        assert result is None

    async def test_claim_ticket_wrong_current_status(self, repo):
        org, _, conv = await self._create_test_data(repo)
        staff_id = await self._create_staff(repo, org["id"])
        result = await repo.claim_ticket(str(conv["id"]), staff_id, expected_version=1, organization_id=str(org["id"]))
        assert result is None

    async def test_release_ticket_success(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        staff_id = await self._create_staff(repo, org["id"])
        await repo.claim_ticket(str(conv["id"]), staff_id, expected_version=2, organization_id=str(org["id"]))
        result = await repo.release_ticket(str(conv["id"]), staff_id, str(org["id"]))
        assert result is not None
        assert result["ticket_status"] == "PENDING_STAFF"
        assert result["assigned_to"] is None
        assert result["version"] == 4

    async def test_release_ticket_wrong_user(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        staff_id = await self._create_staff(repo, org["id"])
        other_id = await self._create_staff(repo, org["id"])
        await repo.claim_ticket(str(conv["id"]), staff_id, expected_version=2, organization_id=str(org["id"]))
        result = await repo.release_ticket(str(conv["id"]), other_id, str(org["id"]))
        assert result is None

    async def test_resolve_ticket_success(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        staff_id = await self._create_staff(repo, org["id"])
        await repo.claim_ticket(str(conv["id"]), staff_id, expected_version=2, organization_id=str(org["id"]))
        result = await repo.resolve_ticket(str(conv["id"]), staff_id, str(org["id"]))
        assert result is not None
        assert result["ticket_status"] == "RESOLVED"
        assert result["resolved_at"] is not None
        assert result["assigned_to"] is None
        assert result["version"] == 4

    async def test_resolve_ticket_not_assigned_to_user(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        staff_id = await self._create_staff(repo, org["id"])
        other_id = await self._create_staff(repo, org["id"])
        await repo.claim_ticket(str(conv["id"]), staff_id, expected_version=2, organization_id=str(org["id"]))
        result = await repo.resolve_ticket(str(conv["id"]), other_id, str(org["id"]))
        assert result is None

    async def test_set_conversation_ai_active(self, repo):
        org, _, conv = await self._create_test_data(repo)
        await repo.escalate_to_human(str(conv["id"]), str(org["id"]))
        result = await repo.set_conversation_ai_active(str(conv["id"]), str(org["id"]))
        assert result is not None
        assert result["ticket_status"] == "AI_ACTIVE"
        assert result["assigned_to"] is None

    async def test_check_idempotency_found(self, repo):
        async with repo.pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Idem Test') RETURNING id",
                uuid.uuid4()
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234568') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
                uuid.uuid4(), org["id"], contact["id"]
            )
            await conn.execute(
                """INSERT INTO messages (id, organization_id, conversation_id, direction, message_type, content, status, idempotency_key)
                   VALUES ($1, $2, $3, 'outbound', 'text', '{}'::jsonb, 'sent', 'idem-001')""",
                uuid.uuid4(), org["id"], conv["id"]
            )
        result = await repo.check_idempotency(str(org["id"]), "idem-001")
        assert result is not None
        assert result["idempotency_key"] == "idem-001"

    async def test_check_idempotency_not_found(self, repo):
        result = await repo.check_idempotency(str(uuid.uuid4()), "nonexistent")
        assert result is None
