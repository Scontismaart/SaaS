import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_get_membership_by_auth_found(repo, pg_pool, sample_org):
    auth_user_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        # Insert into auth.users - trigger auto-creates user_profiles
        await conn.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, 'test@test.com')",
            auth_user_id,
        )
        up_row = await conn.fetchrow(
            "SELECT id FROM user_profiles WHERE auth_user_id = $1", auth_user_id
        )
        await conn.execute("""
            INSERT INTO organization_memberships (organization_id, user_id, ruolo)
            VALUES ($1, $2, 'owner')
        """, sample_org["id"], up_row["id"])
    result = await repo.get_membership_by_auth(str(auth_user_id), str(sample_org["id"]))
    assert result is not None
    assert result["ruolo"] == "owner"


async def test_get_membership_by_auth_not_found(repo):
    result = await repo.get_membership_by_auth(str(uuid.uuid4()), str(uuid.uuid4()))
    assert result is None


async def test_get_membership_by_auth_wrong_org(repo, pg_pool, sample_org, other_org):
    auth_user_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        # Insert into auth.users - trigger auto-creates user_profiles
        await conn.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, 'test2@test.com')",
            auth_user_id,
        )
        up_row = await conn.fetchrow(
            "SELECT id FROM user_profiles WHERE auth_user_id = $1", auth_user_id
        )
        await conn.execute("""
            INSERT INTO organization_memberships (organization_id, user_id, ruolo)
            VALUES ($1, $2, 'manager')
        """, sample_org["id"], up_row["id"])
    result = await repo.get_membership_by_auth(str(auth_user_id), str(other_org["id"]))
    assert result is None
