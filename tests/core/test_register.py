import uuid

import pytest

pytestmark = [pytest.mark.usefixtures("reset_db")]

# I test di policy password/throttle senza DB stanno in
# tests/core/auth/test_register_policy.py; qui restano i flussi che
# toccano repository e database.


async def test_create_organization_with_owner(repo, pg_pool):
    auth_user_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, 'owner-new@test.com')",
            auth_user_id,
        )

    result = await repo.create_organization_with_owner(
        str(auth_user_id), "Trattoria Test", trial_days=14
    )

    org_id = result["organization_id"]
    async with pg_pool.acquire() as conn:
        org = await conn.fetchrow(
            "SELECT name, subscription_status, trial_end, trial_start "
            "FROM organizations WHERE id = $1::uuid",
            uuid.UUID(org_id),
        )
        assert org is not None
        assert org["name"] == "Trattoria Test"
        assert org["subscription_status"] == "trialing"
        assert org["trial_end"] > org["trial_start"]

        # Isolamento tenant: la membership punta all'org giusta con ruolo owner
        m = await conn.fetchrow("""
            SELECT om.ruolo, up.auth_user_id
            FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE om.organization_id = $1::uuid
        """, uuid.UUID(org_id))
        assert m is not None
        assert m["ruolo"] == "owner"
        assert str(m["auth_user_id"]) == str(auth_user_id)


@pytest.mark.asyncio
async def test_create_organization_fails_without_user_profile(repo):
    # Nessun utente in auth.users: fail-closed, nessuna org orfana
    with pytest.raises(RuntimeError):
        await repo.create_organization_with_owner(
            str(uuid.uuid4()), "Ghost Activity", trial_days=14
        )
