import hashlib
import hmac
import json
import os
import uuid
import pytest

pytestmark = pytest.mark.usefixtures("reset_db")

APP_SECRET = "test_ig_app_secret"
VERIFY_TOKEN = "test_ig_verify_token"
ENCRYPTION_KEY = "C1IuGfMh142ShEqV9Y2w3WPcMjIjO4aXjbnly7sqlvw="


@pytest.fixture(autouse=True)
def set_env():
    os.environ["ENCRYPTION_KEY"] = ENCRYPTION_KEY


@pytest.fixture
def app_config():
    from src.whatsapp.config import AppConfig
    return AppConfig(
        app_secret=APP_SECRET,
        encryption_key=ENCRYPTION_KEY,
        postgres_dsn="",
        verify_token=VERIFY_TOKEN,
    )


@pytest.fixture
def ig_app(app_config, pg_pool):
    from fastapi import FastAPI
    from src.whatsapp.repository import Repository as WRepo
    from src.instagram.router import create_router
    from src.instagram.repository import InstagramRepository

    app = FastAPI()
    app.include_router(
        create_router(app_config, WRepo(pool=pg_pool), InstagramRepository(pool=pg_pool))
    )
    return app


def _signed_headers(payload: dict) -> dict:
    body = json.dumps(payload).encode()
    signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": f"sha256={signature}",
    }


def _ig_payload(ig_account_id="17841400000000000", sender_id="123456789", mid="mid.ig.1",
                text="Ciao, avete un tavolo stasera?"):
    return {
        "object": "instagram",
        "entry": [{
            "id": ig_account_id,
            "time": 1712345678,
            "messaging": [{
                "sender": {"id": sender_id},
                "recipient": {"id": ig_account_id},
                "timestamp": 1712345678,
                "message": {"mid": mid, "text": text},
            }],
        }],
    }


async def _create_org_with_ig_account(pg_pool, ig_user_id="17841400000000000"):
    from src.instagram.repository import InstagramRepository

    async with pg_pool.acquire() as conn:
        org = await conn.fetchrow(
            "INSERT INTO organizations (id, name) VALUES ($1, 'IG Test Org') RETURNING id",
            uuid.uuid4()
        )
    igrepo = InstagramRepository(pool=pg_pool)
    await igrepo.save_instagram_account(org["id"], ig_user_id, "page-token-test")
    return org


class TestInstagramWebhookVerify:
    async def test_verify_ok(self, ig_app):
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            res = await client.get("/webhooks/instagram", params={
                "hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "sfida123",
            })
        assert res.status_code == 200
        assert res.text == "sfida123"

    async def test_verify_wrong_token(self, ig_app):
        from httpx import AsyncClient, ASGITransport
        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            res = await client.get("/webhooks/instagram", params={
                "hub.mode": "subscribe", "hub.verify_token": "sbagliato", "hub.challenge": "x",
            })
        assert res.status_code == 403


class TestInstagramWebhookReceive:
    async def test_invalid_signature_403(self, ig_app, pg_pool):
        from httpx import AsyncClient, ASGITransport
        payload = _ig_payload()
        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            res = await client.post(
                "/webhooks/instagram",
                content=json.dumps(payload),
                headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=deadbeef"},
            )
        assert res.status_code == 403

    async def test_valid_dm_creates_message_and_conversation(self, ig_app, pg_pool):
        from httpx import AsyncClient, ASGITransport
        org = await _create_org_with_ig_account(pg_pool)
        payload = _ig_payload(mid="mid.ig.new.1")

        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            res = await client.post("/webhooks/instagram", content=json.dumps(payload),
                                    headers=_signed_headers(payload))
        assert res.status_code == 200

        async with pg_pool.acquire() as conn:
            msg = await conn.fetchrow(
                "SELECT m.*, c.canale, ct.phone_number FROM messages m "
                "JOIN conversations c ON c.id = m.conversation_id "
                "JOIN contacts ct ON ct.id = c.contact_id "
                "WHERE m.organization_id = $1", org["id"]
            )
        assert msg is not None
        assert msg["wam_id"] == "ig:mid.ig.new.1"
        assert msg["direction"] == "inbound"
        assert msg["status"] == "received_pending_ai"
        assert msg["content_text"] == "Ciao, avete un tavolo stasera?"
        assert msg["canale"] == "instagram"
        # identita' contatto = IG user id del mittente (channel-agnostic)
        assert msg["phone_number"] == "123456789"

    async def test_duplicate_mid_ignored(self, ig_app, pg_pool):
        from httpx import AsyncClient, ASGITransport
        org = await _create_org_with_ig_account(pg_pool)
        payload = _ig_payload(mid="mid.ig.dup.1")

        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            first = await client.post("/webhooks/instagram", content=json.dumps(payload),
                                      headers=_signed_headers(payload))
            second = await client.post("/webhooks/instagram", content=json.dumps(payload),
                                       headers=_signed_headers(payload))
        assert first.status_code == 200
        assert second.status_code == 200

        async with pg_pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM messages WHERE organization_id = $1", org["id"]
            )
        assert count == 1

    async def test_unknown_account_ignored(self, ig_app, pg_pool):
        from httpx import AsyncClient, ASGITransport
        payload = _ig_payload(ig_account_id="99999999999", mid="mid.ig.ghost.1")
        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            res = await client.post("/webhooks/instagram", content=json.dumps(payload),
                                    headers=_signed_headers(payload))
        assert res.status_code == 200

        async with pg_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM messages")
        assert count == 0

    async def test_echo_message_ignored(self, ig_app, pg_pool):
        """Gli echo (nostri outbound che tornano indietro) non devono
        rientrare in pipeline come messaggi del cliente."""
        from httpx import AsyncClient, ASGITransport
        await _create_org_with_ig_account(pg_pool)
        payload = _ig_payload(mid="mid.ig.echo.1")
        payload["entry"][0]["messaging"][0]["message"]["is_echo"] = True
        async with AsyncClient(transport=ASGITransport(app=ig_app), base_url="http://test") as client:
            res = await client.post("/webhooks/instagram", content=json.dumps(payload),
                                    headers=_signed_headers(payload))
        assert res.status_code == 200
        async with pg_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM messages")
        assert count == 0
