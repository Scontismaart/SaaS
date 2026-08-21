import base64
import os
import uuid

import httpx
import pytest

from src.core.rate_limit import RedisRateLimiter

pytestmark = pytest.mark.asyncio


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttl = {}

    async def incr(self, key):
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key, seconds):
        self.ttl[key] = seconds


async def test_redis_rate_limiter_shared_across_instances():
    redis = FakeRedis()
    first = RedisRateLimiter(redis)
    second = RedisRateLimiter(redis)

    assert await first.hit("tenant:org", 2, 60) is False
    assert await second.hit("tenant:org", 2, 60) is False
    assert await first.hit("tenant:org", 2, 60) is True
    assert redis.ttl["rl:tenant:org"] == 60


async def test_cookie_mutation_requires_origin_and_csrf(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("AUTH_COOKIE_SECURE", "false")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    async def fake_logout(access_token):
        return None
    monkeypatch.setattr("src.core.auth.bff.logout", fake_logout)
    from src.api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://app.example.com") as client:
        no_origin = await client.post(
            "/api/auth/logout",
            cookies={"wa_at": "jwt", "wa_csrf": "csrf"},
            headers={"X-CSRF-Token": "csrf"},
        )
        assert no_origin.status_code == 403

        bad_token = await client.post(
            "/api/auth/logout",
            cookies={"wa_at": "jwt", "wa_csrf": "csrf"},
            headers={"Origin": "https://app.example.com", "X-CSRF-Token": "wrong"},
        )
        assert bad_token.status_code == 403

        ok = await client.post(
            "/api/auth/logout",
            cookies={"wa_at": "jwt", "wa_csrf": "csrf"},
            headers={"Origin": "https://app.example.com", "X-CSRF-Token": "csrf"},
        )
        assert ok.status_code == 200


async def test_docs_protected_only_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DOCS_BASIC_AUTH_USER", "docs")
    monkeypatch.setenv("DOCS_BASIC_AUTH_PASSWORD", "secret")
    from src.core.security.docs import require_docs_access

    class Req:
        headers = {}
        client = type("Client", (), {"host": "203.0.113.10"})()

    with pytest.raises(Exception):
        require_docs_access(Req())

    token = base64.b64encode(b"docs:secret").decode()
    Req.headers = {"authorization": f"Basic {token}"}
    require_docs_access(Req())


async def test_api_key_rejected_from_public_ip(monkeypatch):
    monkeypatch.setenv("API_KEY_ALLOWED_CIDRS", "10.0.0.0/8")
    from src.core.auth.api_key_guard import api_key_request_allowed

    class Req:
        headers = {}
        client = type("Client", (), {"host": "198.51.100.10"})()

    assert api_key_request_allowed(Req()) is False


async def test_rls_blocks_cross_tenant_direct_query(pg_pool, sample_org, other_org):
    auth_user_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid AS $$
                SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid
            $$ LANGUAGE sql STABLE;
        """)
        await conn.execute("DROP ROLE IF EXISTS authenticated")
        await conn.execute("CREATE ROLE authenticated")
        await conn.execute("GRANT USAGE ON SCHEMA public, auth TO authenticated")
        await conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO authenticated")
        await conn.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, 'rls@test.com')",
            auth_user_id,
        )
        up = await conn.fetchrow("SELECT id FROM user_profiles WHERE auth_user_id = $1", auth_user_id)
        await conn.execute(
            "INSERT INTO organization_memberships (organization_id, user_id, ruolo) VALUES ($1, $2, 'owner')",
            sample_org["id"], up["id"],
        )
        await conn.execute(
            "INSERT INTO documents (id, organization_id, nome) VALUES ($1, $2, 'own.pdf')",
            uuid.uuid4(), sample_org["id"],
        )
        await conn.execute(
            "INSERT INTO documents (id, organization_id, nome) VALUES ($1, $2, 'other.pdf')",
            uuid.uuid4(), other_org["id"],
        )
        await conn.execute("SET ROLE authenticated")
        await conn.execute("SELECT set_config('request.jwt.claim.sub', $1, false)", str(auth_user_id))
        rows = await conn.fetch("SELECT nome FROM documents ORDER BY nome")
        await conn.execute("RESET ROLE")

    assert [r["nome"] for r in rows] == ["own.pdf"]
