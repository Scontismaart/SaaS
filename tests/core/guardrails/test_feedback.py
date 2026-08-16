"""Feedback 👍/👎 sulle risposte AI (task 12): repository su DB reale
(upsert cliente/staff, ultima risposta AI come target emoji) e API staff
(201/403/404/422, idempotenza per operatore)."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.usefixtures("reset_db")

API_KEY = "test-feedback-api-key"


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


async def _make_client(app, org_id, user_id, ruolo="staff"):
    from src.core.auth.dependencies import get_organization_context

    async def fake_get_organization_context():
        return {
            "auth_user_id": str(uuid.uuid4()),
            "organization_id": str(org_id),
            "ruolo": ruolo,
            "source": "jwt",
            "user_id": str(user_id),
        }

    app.dependency_overrides[get_organization_context] = fake_get_organization_context
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _setup_org_conv(pg_pool):
    async with pg_pool.acquire() as conn:
        org = await conn.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Feedback Test') RETURNING id",
            uuid.uuid4(),
        )
        auth_user = await conn.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "staff-feedback@test.com",
        )
        profile = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_user["id"]
        )
        await conn.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], profile["id"],
        )
        contact = await conn.fetchrow(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991112233') RETURNING id",
            uuid.uuid4(), org["id"],
        )
        conv = await conn.fetchrow(
            "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
            uuid.uuid4(), org["id"], contact["id"],
        )
    return org, profile, conv


async def _insert_outbound(pg_pool, org, conv, text, handling_type,
                           created_at=None):
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO messages
                   (id, organization_id, conversation_id, direction, message_type,
                    content, content_text, status, handling_type, created_at)
               VALUES ($1, $2, $3, 'outbound', 'text', '{}'::jsonb, $4, 'sent', $5, $6)
               RETURNING id""",
            uuid.uuid4(), org["id"], conv["id"], text, handling_type,
            created_at or datetime.now(timezone.utc),
        )
        return row["id"]


@pytest.fixture
async def wrepo(pg_pool):
    from src.whatsapp.repository import Repository
    return Repository(pool=pg_pool)


class TestRepoFeedback:
    async def test_ultima_risposta_ai_trovata(self, wrepo, pg_pool):
        org, profile, conv = await _setup_org_conv(pg_pool)
        base = datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc)
        msg_ai_vecchia = await _insert_outbound(pg_pool, org, conv, "AI 1", "ai_handled", base)
        await _insert_outbound(pg_pool, org, conv, "risposta staff", "human", base.replace(hour=11))
        msg_ai_recente = await _insert_outbound(pg_pool, org, conv, "AI 2", "ai_handled", base.replace(hour=12))

        last = await wrepo.get_last_ai_outbound_message(org["id"], conv["id"])
        assert str(last["id"]) == str(msg_ai_recente)
        assert str(last["id"]) != str(msg_ai_vecchia)

    async def test_feedback_cliente_upsert_ultima_emoji_vince(self, wrepo, pg_pool):
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")

        row = await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id,
            conversation_id=conv["id"], source="customer_emoji", value="up",
        )
        assert row["value"] == "up"
        row2 = await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id,
            conversation_id=conv["id"], source="customer_emoji", value="down",
        )
        assert row2["value"] == "down"
        assert row2["id"] == row["id"], "upsert, non duplicato"

    async def test_feedback_staff_uno_per_operatore(self, wrepo, pg_pool):
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")
        altro_utente = uuid.uuid4()

        await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id, conversation_id=conv["id"],
            source="staff_ui", value="up", created_by_user_id=profile["id"],
        )
        row = await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id, conversation_id=conv["id"],
            source="staff_ui", value="down", created_by_user_id=profile["id"],
        )
        assert row["value"] == "down"
        # secondo operatore: riga diversa
        row_b = await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id, conversation_id=conv["id"],
            source="staff_ui", value="up", created_by_user_id=altro_utente,
        )
        assert row_b["id"] != row["id"]

    async def test_list_messages_include_feedback(self, wrepo, pg_pool):
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")
        await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id, conversation_id=conv["id"],
            source="customer_emoji", value="up",
        )
        await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id, conversation_id=conv["id"],
            source="staff_ui", value="down", created_by_user_id=profile["id"],
        )
        rows = await wrepo.list_conversation_messages(org["id"], conv["id"])
        target = next(r for r in rows if str(r["id"]) == str(msg_id))
        assert target["feedback_customer"] == "up"
        assert target["feedback_staff_down"] == 1
        assert target["feedback_staff_up"] == 0


class TestApiFeedback:
    async def test_staff_feedback_ok(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")

        async with await _make_client(app, org["id"], profile["id"]) as client:
            r = await client.post(
                f"/api/inbox/messages/{msg_id}/feedback", json={"value": "up"}
            )
        assert r.status_code == 200
        assert r.json() == {"message_id": str(msg_id), "value": "up", "source": "staff_ui"}

        # idempotente per operatore: ri-votare aggiorna
        async with await _make_client(app, org["id"], profile["id"]) as client:
            r2 = await client.post(
                f"/api/inbox/messages/{msg_id}/feedback", json={"value": "down"}
            )
        assert r2.status_code == 200
        assert r2.json()["value"] == "down"

    async def test_api_key_senza_user_id_403(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")

        from src.core.auth.dependencies import get_organization_context

        async def fake_api_key_context():
            return {
                "auth_user_id": None, "organization_id": str(org["id"]),
                "ruolo": "staff", "source": "api_key", "user_id": None,
            }

        app.dependency_overrides[get_organization_context] = fake_api_key_context
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                f"/api/inbox/messages/{msg_id}/feedback", json={"value": "up"}
            )
        assert r.status_code == 403

    async def test_cross_tenant_404(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await _setup_org_conv(pg_pool)
        altro_org = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")

        async with await _make_client(app, altro_org[0]["id"], altro_org[1]["id"]) as client:
            r = await client.post(
                f"/api/inbox/messages/{msg_id}/feedback", json={"value": "up"}
            )
        assert r.status_code == 404

    async def test_feedback_su_messaggio_inbound_422(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await _setup_org_conv(pg_pool)
        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO messages
                       (id, organization_id, conversation_id, direction, message_type,
                        content, content_text, status, handling_type)
                   VALUES ($1, $2, $3, 'inbound', 'text', '{}'::jsonb, 'domanda', 'handled', 'ai_handled')
                   RETURNING id""",
                uuid.uuid4(), org["id"], conv["id"],
            )
            inbound_id = row["id"]

        async with await _make_client(app, org["id"], profile["id"]) as client:
            r = await client.post(
                f"/api/inbox/messages/{inbound_id}/feedback", json={"value": "up"}
            )
        assert r.status_code == 422

    async def test_value_invalido_422(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")
        async with await _make_client(app, org["id"], profile["id"]) as client:
            r = await client.post(
                f"/api/inbox/messages/{msg_id}/feedback", json={"value": "ottimo"}
            )
        assert r.status_code == 422

    async def test_get_messages_espone_feedback(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await _setup_org_conv(pg_pool)
        msg_id = await _insert_outbound(pg_pool, org, conv, "AI", "ai_handled")
        from src.whatsapp.repository import Repository
        wrepo = Repository(pool=pg_pool)
        await wrepo.registra_feedback(
            organization_id=org["id"], message_id=msg_id, conversation_id=conv["id"],
            source="customer_emoji", value="up",
        )
        async with await _make_client(app, org["id"], profile["id"]) as client:
            r = await client.get(f"/api/inbox/tickets/{conv['id']}/messages")
        assert r.status_code == 200
        target = next(m for m in r.json()["messages"] if m["id"] == str(msg_id))
        assert target["feedback_customer"] == "up"
        assert target["handling_type"] == "ai_handled"
