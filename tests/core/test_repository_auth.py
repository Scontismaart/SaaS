import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_get_membership_by_auth_found(repo, pg_pool, sample_org):
    auth_user_id = "auth|test123"
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_profiles (id, auth_user_id, email)
            VALUES ($1, $2, 'test@test.com')
        """, uuid.uuid4(), auth_user_id)
        up_row = await conn.fetchrow(
            "SELECT id FROM user_profiles WHERE auth_user_id = $1", auth_user_id
        )
        await conn.execute("""
            INSERT INTO organization_memberships (organization_id, user_id, ruolo)
            VALUES ($1, $2, 'owner')
        """, sample_org["id"], up_row["id"])
    result = await repo.get_membership_by_auth(auth_user_id, str(sample_org["id"]))
    assert result is not None
    assert result["ruolo"] == "owner"


async def test_get_membership_by_auth_not_found(repo):
    result = await repo.get_membership_by_auth("auth|nonexistent", str(uuid.uuid4()))
    assert result is None


async def test_get_membership_by_auth_wrong_org(repo, pg_pool, sample_org, other_org):
    auth_user_id = "auth|test456"
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_profiles (id, auth_user_id, email)
            VALUES ($1, $2, 'test2@test.com')
        """, uuid.uuid4(), auth_user_id)
        up_row = await conn.fetchrow(
            "SELECT id FROM user_profiles WHERE auth_user_id = $1", auth_user_id
        )
        await conn.execute("""
            INSERT INTO organization_memberships (organization_id, user_id, ruolo)
            VALUES ($1, $2, 'manager')
        """, sample_org["id"], up_row["id"])
    result = await repo.get_membership_by_auth(auth_user_id, str(other_org["id"]))
    assert result is None
