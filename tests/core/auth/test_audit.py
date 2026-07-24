import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_audit_log_creates_entry(repo, sample_org):
    from src.core.auth.audit import audit_log
    entry = await audit_log(
        repo=repo,
        organization_id=str(sample_org["id"]),
        action="profilo_modificato",
        target_table="user_profiles",
        target_id=str(uuid.uuid4()),
        details={"modifica": "Nome cambiato da 'Mario' a 'Luigi'"},
    )
    assert entry["action"] == "profilo_modificato"
    assert entry["target_table"] == "user_profiles"
    assert entry["organization_id"] == sample_org["id"]


async def test_audit_log_with_user(repo, sample_org, pg_pool):
    from src.core.auth.audit import audit_log

    async with pg_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO user_profiles (id, auth_user_id, email)
            VALUES ($1, $2, 'test@test.com')
        """, uuid.uuid4(), "auth|test123")
        up_row = await conn.fetchrow(
            "SELECT id FROM user_profiles WHERE auth_user_id = $1", "auth|test123"
        )

    entry = await audit_log(
        repo=repo,
        organization_id=str(sample_org["id"]),
        user_id=str(up_row["id"]),
        auth_user_id="auth|test123",
        action="prenotazione_eliminata",
        target_table="bookings",
        target_id=str(uuid.uuid4()),
        details={"motivo": "Cliente non venuto"},
    )
    assert entry["action"] == "prenotazione_eliminata"
    assert entry["user_id"] == up_row["id"]