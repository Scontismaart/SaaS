import os
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from datetime import timedelta

pytestmark = pytest.mark.usefixtures("reset_db")


API_KEY = "test-sla-api-key"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app

    app.state.repo = repo
    app.state.pool = pg_pool

    yield repo, pg_pool, app
    app.dependency_overrides.clear()


class TestSla:
    async def _create_org(self, pg_pool, sla_minutes=None):
        id = uuid.uuid4()
        if sla_minutes is None:
            row = await pg_pool.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Sla Org') RETURNING id",
                id,
            )
        else:
            row = await pg_pool.fetchrow(
                "INSERT INTO organizations (id, name, sla_minutes) VALUES ($1, 'Sla Org', $2) RETURNING id, sla_minutes",
                id, sla_minutes,
            )
        return row

    async def _create_conv(self, pg_pool, org_id, contact_phone="+393991234567"):
        contact = await pg_pool.fetchrow(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, $3) RETURNING id",
            uuid.uuid4(), org_id, contact_phone,
        )
        conv = await pg_pool.fetchrow(
            "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
            uuid.uuid4(), org_id, contact["id"],
        )
        return contact, conv

    async def _make_client(self, app, org_id, user_id):
        from src.core.auth.dependencies import get_organization_context

        async def fake_get_organization_context():
            return {
                "auth_user_id": str(uuid.uuid4()),
                "organization_id": str(org_id),
                "ruolo": "staff",
                "source": "jwt",
                "user_id": str(user_id),
            }

        app.dependency_overrides[get_organization_context] = fake_get_organization_context
        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    async def test_sla_due_at_from_org_sla_minutes(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool, sla_minutes=30)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        rows = await wrepo.list_tickets(str(org["id"]))
        assert len(rows) == 1
        assert rows[0]["sla_minutes"] == 30
        pending = rows[0]["pending_staff_at"]
        assert rows[0]["sla_due_at"] == pending + timedelta(minutes=30)
        assert rows[0]["is_overdue"] is False

    async def test_sla_default_15(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        rows = await wrepo.list_tickets(str(org["id"]))
        assert rows[0]["sla_minutes"] == 15
        assert rows[0]["sla_due_at"] == rows[0]["pending_staff_at"] + timedelta(minutes=15)

    async def test_sla_overdue_when_expired(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool, sla_minutes=5)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))
        async with pg_pool.acquire() as conn:
            await conn.execute(
                "UPDATE conversations SET pending_staff_at = NOW() - interval '10 minutes' WHERE id = $1",
                conv["id"],
            )

        rows = await wrepo.list_tickets(str(org["id"]))
        assert rows[0]["is_overdue"] is True

    async def test_priority_from_event_log(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        _, conv = await self._create_conv(pg_pool, org["id"])

        async with pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO event_log (organization_id, source_table, source_id, tipo_evento, priorita)
                   VALUES ($1, 'messages', $2, 'messaggio', 'alta')""",
                org["id"], uuid.uuid4(),
            )
            await conn.execute(
                "UPDATE event_log SET dettagli = jsonb_build_object('conversation_id', $1::text) WHERE source_table = 'messages'",
                str(conv["id"]),
            )

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        rows = await wrepo.list_tickets(str(org["id"]))
        assert rows[0]["priorita"] == "alta"

    async def test_priority_fallback_pending_staff_high(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        rows = await wrepo.list_tickets(str(org["id"]))
        assert rows[0]["priorita"] == "alta"

    async def test_priority_fallback_ai_active_medium(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        rows = await wrepo.list_tickets(str(org["id"]))
        assert rows[0]["ticket_status"] == "AI_ACTIVE"
        assert rows[0]["priorita"] == "media"

    async def test_priority_filter_query(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        rows = await wrepo.list_tickets(str(org["id"]), priorita="alta")
        assert len(rows) == 1
        rows_media = await wrepo.list_tickets(str(org["id"]), priorita="media")
        assert rows_media == []

    async def test_priority_filter_via_route(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        async with await self._make_client(app, org["id"], uuid.uuid4()) as client:
            response = await client.get("/api/inbox/tickets?priorita=alta")
            assert response.status_code == 200
            data = response.json()
            assert len(data["tickets"]) == 1
            assert data["tickets"][0]["priorita"] == "alta"

            response_media = await client.get("/api/inbox/tickets?priorita=media")
            assert response_media.json() == {"tickets": []}

    async def test_phone_and_last_message_preview(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool)
        contact, conv = await self._create_conv(pg_pool, org["id"])

        async with pg_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO messages (id, organization_id, conversation_id, wam_id, direction, message_type, content, content_text, status, handling_type)
                   VALUES ($1, $2, $3, $4, 'inbound', 'text', '{"body": "Vorrei prenotare"}', 'Vorrei prenotare', 'handled', 'ai_handled')""",
                uuid.uuid4(), org["id"], conv["id"], uuid.uuid4().hex,
            )

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        rows = await wrepo.list_tickets(str(org["id"]))
        assert rows[0]["phone_number"] == "+393991234567"
        assert rows[0]["last_message_preview"] == "Vorrei prenotare"

    async def test_get_ticket_sla_and_context(self, async_client):
        from src.whatsapp.repository import Repository as WRepo

        repo, pg_pool, app = async_client
        org = await self._create_org(pg_pool, sla_minutes=45)
        _, conv = await self._create_conv(pg_pool, org["id"])

        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        row = await wrepo.get_conversation(str(conv["id"]))
        assert row["sla_minutes"] == 45
        assert row["is_overdue"] is False
        assert row["phone_number"] == "+393991234567"

        async with await self._make_client(app, org["id"], uuid.uuid4()) as client:
            response = await client.get(f"/api/inbox/tickets/{conv['id']}")
            assert response.status_code == 200
            data = response.json()
            assert data["sla_minutes"] == 45
            assert data["priorita"] == "alta"
