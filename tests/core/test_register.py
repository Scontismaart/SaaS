import uuid

import pytest

from src.core.auth.register import (
    PASSWORD_MIN,
    _check_signup_throttle,
    _EMAIL_RE,
)
from fastapi import HTTPException

pytestmark = [pytest.mark.usefixtures("reset_db")]


def test_email_regex_accepts_valid():
    assert _EMAIL_RE.match("titolare@attivita.it")
    assert _EMAIL_RE.match("a.b+tag@sub.domain.com")


def test_email_regex_rejects_invalid():
    assert not _EMAIL_RE.match("no-at-sign")
    assert not _EMAIL_RE.match("a@b")
    assert not _EMAIL_RE.match("a b@c.it")


def test_password_min_constant():
    assert PASSWORD_MIN >= 8


def test_signup_throttle_blocks_after_max():
    ip = f"10.0.0.{uuid.uuid4().int % 250 + 1}"
    for _ in range(5):
        _check_signup_throttle(ip)
    with pytest.raises(HTTPException) as exc:
        _check_signup_throttle(ip)
    assert exc.value.status_code == 429


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
