import os
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

pytestmark = pytest.mark.usefixtures("reset_db")


API_KEY = "test-inbox-api-key"


@pytest.fixture(autouse=True)
def set_env():
    os.environ["API_KEY_SERVICE"] = API_KEY


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app
    from src.core.auth.dependencies import get_organization_context

    app.state.repo = repo
    app.state.pool = pg_pool

    yield repo, pg_pool, app
    app.dependency_overrides.clear()


class TestInboxAPI:
    async def _create_org_with_staff(self, pg_pool):
        async with pg_pool.acquire() as conn:
            org = await conn.fetchrow(
                "INSERT INTO organizations (id, name) VALUES ($1, 'Inbox Test') RETURNING id",
                uuid.uuid4()
            )
            auth_user = await conn.fetchrow(
                "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
                "staff@test.com"
            )
            profile = await conn.fetchrow(
                "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_user["id"]
            )
            await conn.execute(
                "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
                org["id"], profile["id"]
            )
            contact = await conn.fetchrow(
                "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, '+393991234567') RETURNING id",
                uuid.uuid4(), org["id"]
            )
            conv = await conn.fetchrow(
                "INSERT INTO conversations (id, organization_id, contact_id) VALUES ($1, $2, $3) RETURNING id",
                uuid.uuid4(), org["id"], contact["id"]
            )
        return org, profile, conv

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

    async def test_list_tickets_empty(self, async_client):
        repo, pg_pool, app = async_client
        org = await pg_pool.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Empty Org') RETURNING id",
            uuid.uuid4()
        )
        async with await self._make_client(app, org["id"], uuid.uuid4()) as client:
            response = await client.get("/api/inbox/tickets")
            assert response.status_code == 200
            assert response.json() == {"tickets": []}

    async def test_list_tickets_with_pending(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)
        # Create another staff user for auth
        auth_user2 = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "staff2@test.com"
        )
        profile2 = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_user2["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], profile2["id"]
        )

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        async with await self._make_client(app, org["id"], profile2["id"]) as client:
            response = await client.get("/api/inbox/tickets")
            assert response.status_code == 200
            data = response.json()
            assert len(data["tickets"]) == 1
            assert data["tickets"][0]["id"] == str(conv["id"])
            assert data["tickets"][0]["ticket_status"] == "PENDING_STAFF"

    async def test_claim_ticket(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)

        # Create staff user for claiming
        auth_staff = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "claimer@test.com"
        )
        staff_profile = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_staff["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], staff_profile["id"]
        )

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        async with await self._make_client(app, org["id"], staff_profile["id"]) as client:
            response = await client.post(
                f"/api/inbox/claim/{conv['id']}",
                json={"expected_version": 2}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["ticket_status"] == "CLAIMED"
            assert data["assigned_to"] == str(staff_profile["id"])

    async def test_claim_ticket_conflict(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)

        auth_staff = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "conflicter@test.com"
        )
        staff_profile = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_staff["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], staff_profile["id"]
        )

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))

        async with await self._make_client(app, org["id"], staff_profile["id"]) as client:
            response = await client.post(
                f"/api/inbox/claim/{conv['id']}",
                json={"expected_version": 1}  # wrong version
            )
            assert response.status_code == 409

    async def test_get_ticket_not_found(self, async_client):
        repo, pg_pool, app = async_client
        org = await pg_pool.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'Test') RETURNING id",
            uuid.uuid4()
        )
        async with await self._make_client(app, org["id"], uuid.uuid4()) as client:
            response = await client.get(f"/api/inbox/tickets/{uuid.uuid4()}")
            assert response.status_code == 404

    async def test_release_ticket(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)

        auth_staff = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "releaser@test.com"
        )
        staff_profile = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_staff["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], staff_profile["id"]
        )

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))
        await wrepo.claim_ticket(str(conv["id"]), str(staff_profile["id"]), expected_version=2)

        async with await self._make_client(app, org["id"], staff_profile["id"]) as client:
            response = await client.post(f"/api/inbox/release/{conv['id']}")
            assert response.status_code == 200
            data = response.json()
            assert data["ticket_status"] == "PENDING_STAFF"

    async def test_resolve_ticket(self, async_client):
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)

        auth_staff = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "resolver@test.com"
        )
        staff_profile = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_staff["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], staff_profile["id"]
        )

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))
        await wrepo.claim_ticket(str(conv["id"]), str(staff_profile["id"]), expected_version=2)

        async with await self._make_client(app, org["id"], staff_profile["id"]) as client:
            response = await client.post(f"/api/inbox/resolve/{conv['id']}")
            assert response.status_code == 200
            data = response.json()
            assert data["ticket_status"] == "RESOLVED"

    async def test_inbox_router_registered(self, async_client):
        repo, pg_pool, app = async_client

        def all_paths(routes):
            for r in routes:
                p = getattr(r, "path", None)
                if p:
                    yield p
                original = getattr(r, "original_router", None)
                if original is not None:
                    yield from all_paths(getattr(original, "routes", []))
                nested = getattr(r, "routes", None)
                if nested:
                    yield from all_paths(nested)

        paths = list(all_paths(app.routes))
        assert any("/api/inbox/tickets" in p for p in paths)

    async def test_reply_requires_claim_by_you(self, async_client):
        """Task 6: non si puo' rispondere a un ticket non CLAIMED da te."""
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))  # PENDING_STAFF, non CLAIMED

        async with await self._make_client(app, org["id"], profile["id"]) as client:
            response = await client.post(
                f"/api/inbox/reply/{conv['id']}",
                json={"content": "Certo, confermo!", "idempotency_key": "test-key-1"},
            )
            assert response.status_code == 409

    async def test_reply_success_sends_via_whatsapp(self, async_client):
        """Task 6: risposta manuale inoltrata a Meta Cloud API (mockata,
        niente rete reale) su ticket CLAIMED dall'operatore che risponde."""
        from unittest.mock import AsyncMock, patch, MagicMock
        repo, pg_pool, app = async_client
        org, profile, conv = await self._create_org_with_staff(pg_pool)

        auth_staff = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "replier@test.com"
        )
        staff_profile = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_staff["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], staff_profile["id"]
        )

        from src.whatsapp.repository import Repository as WRepo
        wrepo = WRepo(pool=pg_pool)
        await wrepo.escalate_to_human(str(conv["id"]))
        await wrepo.claim_ticket(str(conv["id"]), str(staff_profile["id"]), expected_version=2)

        fake_tenant_config = MagicMock(phone_number_id="123", access_token="tok")
        fake_result = {"id": "msg-uuid-1", "status": "sent"}

        with patch("src.core.inbox.routes.load_tenant_config", AsyncMock(return_value=fake_tenant_config)), \
             patch.object(
                 __import__("src.whatsapp.service", fromlist=["WhatsAppService"]).WhatsAppService,
                 "send_whatsapp_message",
                 AsyncMock(return_value=fake_result),
             ) as mock_send:
            async with await self._make_client(app, org["id"], staff_profile["id"]) as client:
                response = await client.post(
                    f"/api/inbox/reply/{conv['id']}",
                    json={"content": "Certo, confermo la prenotazione!", "idempotency_key": "test-key-ok"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["message_id"] == "msg-uuid-1"
                assert data["status"] == "sent"

        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["idempotency_key"] == "test-key-ok"
        assert call_kwargs["payload"]["text"]["body"] == "Certo, confermo la prenotazione!"