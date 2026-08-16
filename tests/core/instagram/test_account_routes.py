import os
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from cryptography.fernet import Fernet

pytestmark = pytest.mark.usefixtures("reset_db")

ENCRYPTION_KEY = "C1IuGfMh142ShEqV9Y2w3WPcMjIjO4aXjbnly7sqlvw="


@pytest.fixture(autouse=True)
def set_env():
    os.environ["ENCRYPTION_KEY"] = ENCRYPTION_KEY


@pytest.fixture
async def async_client(repo, pg_pool):
    from src.api.main import app

    app.state.repo = repo
    app.state.pool = pg_pool

    yield repo, pg_pool, app
    app.dependency_overrides.clear()


async def _make_client(app, org_id, user_id, ruolo="owner"):
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


async def _create_org_with_owner(pg_pool):
    async with pg_pool.acquire() as conn:
        org = await conn.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'IG Account Org') RETURNING id",
            uuid.uuid4()
        )
        auth_user = await conn.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "ig-owner@test.com"
        )
        profile = await conn.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", auth_user["id"]
        )
        await conn.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'owner')",
            org["id"], profile["id"]
        )
    return org, profile


class TestInstagramAccountAPI:
    async def test_save_get_delete_roundtrip(self, async_client):
        repo, pg_pool, app = async_client
        org, owner = await _create_org_with_owner(pg_pool)

        async with await _make_client(app, org["id"], owner["id"]) as client:
            saved = await client.post("/api/instagram/account", json={
                "ig_user_id": "17841400000000001",
                "access_token": "EAAG-super-secret-token",
            })
            assert saved.status_code == 200, saved.text
            assert saved.json()["ig_user_id"] == "17841400000000001"

            got = await client.get("/api/instagram/account")
            assert got.status_code == 200
            body = got.json()
            assert body["ig_user_id"] == "17841400000000001"
            assert "access_token" not in body  # mai esposto in chiaro

            deleted = await client.delete("/api/instagram/account")
            assert deleted.status_code == 200

            after = await client.get("/api/instagram/account")
            assert after.status_code == 404

    async def test_token_encrypted_at_rest(self, async_client):
        repo, pg_pool, app = async_client
        org, owner = await _create_org_with_owner(pg_pool)

        async with await _make_client(app, org["id"], owner["id"]) as client:
            res = await client.post("/api/instagram/account", json={
                "ig_user_id": "17841400000000002",
                "access_token": "EAAG-token-da-non-vedere",
            })
            assert res.status_code == 200

        async with pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT access_token FROM instagram_accounts WHERE organization_id = $1",
                org["id"],
            )
        assert row["access_token"] != "EAAG-token-da-non-vedere"
        decrypted = Fernet(ENCRYPTION_KEY.encode()).decrypt(row["access_token"].encode()).decode()
        assert decrypted == "EAAG-token-da-non-vedere"

    async def test_staff_cannot_save(self, async_client):
        repo, pg_pool, app = async_client
        org, owner = await _create_org_with_owner(pg_pool)

        staff_auth = await pg_pool.fetchrow(
            "INSERT INTO auth.users (email) VALUES ($1) RETURNING id",
            "ig-staff@test.com"
        )
        staff = await pg_pool.fetchrow(
            "SELECT * FROM user_profiles WHERE auth_user_id = $1", staff_auth["id"]
        )
        await pg_pool.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'staff')",
            org["id"], staff["id"]
        )

        async with await _make_client(app, org["id"], staff["id"], ruolo="staff") as client:
            res = await client.post("/api/instagram/account", json={
                "ig_user_id": "17841400000000003",
                "access_token": "tok",
            })
        assert res.status_code == 403
