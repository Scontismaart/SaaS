"""Test per GET /api/ui/summary (task18 Fase 3).

Il summary restituisce conteggi org-scoped (inbox attivi, prenotazioni,
documenti, recensioni da approvare) con l'organization_id risolto
server-side dalla membership JWT: nessun header X-Organization-Id e
nessuna leak tra tenant.
"""

import os
import uuid

import httpx
import pytest

API_KEY = "test-api-key-12345"

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("API_KEY_SERVICE", API_KEY)
    monkeypatch.setenv("SUPABASE_URL", "https://myproj.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-test-key")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("DEMO_MODE", "false")


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app

    app.state.repo = repo
    app.state.pool = pg_pool
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_membership(pg_pool, org_id, auth_user_id):
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, 'owner@test.com')",
            auth_user_id,
        )
        up_row = await conn.fetchrow(
            "SELECT id FROM user_profiles WHERE auth_user_id = $1", auth_user_id
        )
        await conn.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) "
            "VALUES ($1, $2, 'owner')",
            org_id, up_row["id"],
        )


async def _insert_booking(pg_pool, org_id):
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bookings (id, organization_id, nome_cliente, data, ora, coperti, stato) "
            "VALUES ($1, $2, 'Cliente', CURRENT_DATE, '19:00', 2, 'confermata')",
            uuid.uuid4(), org_id,
        )


async def _insert_document(pg_pool, org_id):
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO documents (id, organization_id, nome) VALUES ($1, $2, 'menu.pdf')",
            uuid.uuid4(), org_id,
        )


async def _insert_ticket(pg_pool, org_id, ticket_status, phone_number="+39333111222"):
    async with pg_pool.acquire() as conn:
        contact_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO contacts (id, organization_id, phone_number) VALUES ($1, $2, $3)",
            contact_id, org_id, phone_number,
        )
        conv_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO conversations (id, organization_id, contact_id, ticket_status, pending_staff_at) "
            "VALUES ($1, $2, $3, $4, NOW())",
            conv_id, org_id, contact_id, ticket_status,
        )
        return conv_id


class TestUiSummary:
    async def test_summary_org_scoped_counts(self, async_client, pg_pool, sample_org, monkeypatch):
        auth_user_id = os.urandom(16).hex()
        org_id = sample_org["id"]
        await _seed_membership(pg_pool, org_id, auth_user_id)

        await _insert_booking(pg_pool, org_id)
        await _insert_document(pg_pool, org_id)
        await _insert_ticket(pg_pool, org_id, "PENDING_STAFF", "+39333111222")
        await _insert_ticket(pg_pool, org_id, "CLAIMED", "+39333111223")
        await _insert_ticket(pg_pool, org_id, "RESOLVED", "+39333111224")

        import src.core.auth.dependencies as deps_module

        async def fake_verify(token):
            return {"sub": auth_user_id, "email": "owner@test.com"}

        monkeypatch.setattr(deps_module, "verify_supabase_jwt", fake_verify)

        resp = await async_client.get(
            "/api/ui/summary", headers={"Authorization": "Bearer at.fake"}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["inbox_attivi"] == 2
        assert data["prenotazioni"] == 1
        assert data["documenti"] == 1
        assert data["recensioni_da_approvare"] == 0
        assert len(data["inbox_attivi_ids"]) == 2

    async def test_summary_tenant_isolation(self, async_client, pg_pool, sample_org, other_org, monkeypatch):
        """Il conteggio dell'org dell'utente NON include i dati dell'altro org."""
        auth_user_id = os.urandom(16).hex()
        await _seed_membership(pg_pool, sample_org["id"], auth_user_id)

        # dati nell'altro org: non devono comparire
        await _insert_booking(pg_pool, other_org["id"])
        await _insert_document(pg_pool, other_org["id"])
        await _insert_ticket(pg_pool, other_org["id"], "PENDING_STAFF")

        import src.core.auth.dependencies as deps_module

        async def fake_verify(token):
            return {"sub": auth_user_id, "email": "owner@test.com"}

        monkeypatch.setattr(deps_module, "verify_supabase_jwt", fake_verify)

        resp = await async_client.get(
            "/api/ui/summary", headers={"Authorization": "Bearer at.fake"}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["inbox_attivi"] == 0
        assert data["prenotazioni"] == 0
        assert data["documenti"] == 0
        assert data["recensioni_da_approvare"] == 0
        assert data["inbox_attivi_ids"] == []

    async def test_summary_requires_auth(self, async_client):
        """Senza sessione (DEMO_MODE=false) → 401."""
        resp = await async_client.get("/api/ui/summary")
        assert resp.status_code == 401