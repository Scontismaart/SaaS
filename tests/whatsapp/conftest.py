import asyncio
import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture
async def pg_pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    async with pool.acquire() as conn:
        with open("src/whatsapp/schema.sql") as f:
            await conn.execute(f.read())
        with open("src/core/db/migrations/004_gdpr.sql") as f:
            await conn.execute(f.read())
    yield pool
    await pool.close()


@pytest.fixture(autouse=True, scope="session")
def _set_env():
    import os
    os.environ.setdefault("ENCRYPTION_KEY", "C1IuGfMh142ShEqV9Y2w3WPcMjIjO4aXjbnly7sqlvw=")


@pytest.fixture(autouse=True)
async def reset_db(pg_pool):
    async with pg_pool.acquire() as conn:
        await conn.execute("""
            TRUNCATE TABLE
                contact_consent_log, message_delivery_attempts,
                messages, conversations, contacts, whatsapp_templates,
                whatsapp_accounts, organizations
            CASCADE
        """)


@pytest.fixture
async def repo(pg_pool):
    from src.whatsapp.repository import Repository
    return Repository(pool=pg_pool)


@pytest.fixture
def status_webhook_fixture():
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "391234567890",
                        "phone_number_id": "1234567890",
                    },
                    "statuses": [{
                        "id": "wamid.example",
                        "status": "delivered",
                        "timestamp": "1712345678",
                        "recipient_id": "391234567890",
                        "biz_opaque_callback_data": "msg-uuid-here",
                    }],
                },
            }],
        }],
    }


@pytest.fixture
def message_webhook_fixture():
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "391234567890",
                        "phone_number_id": "1234567890",
                    },
                    "contacts": [{
                        "profile": {"name": "Mario Rossi"},
                        "wa_id": "391234567890",
                    }],
                    "messages": [{
                        "from": "391234567890",
                        "id": "wamid.inbound.1",
                        "timestamp": "1712345678",
                        "type": "text",
                        "text": {"body": "Ciao, vorrei prenotare"},
                    }],
                },
            }],
        }],
    }


@pytest.fixture
def button_reply_fixture():
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "391234567890",
                        "phone_number_id": "1234567890",
                    },
                    "messages": [{
                        "from": "391234567890",
                        "id": "wamid.inbound.2",
                        "timestamp": "1712345679",
                        "type": "interactive",
                        "interactive": {
                            "type": "button_reply",
                            "button_reply": {
                                "id": "unsubscribe_confirm",
                                "title": "Annulla iscrizione",
                            },
                        },
                    }],
                },
            }],
        }],
    }


@pytest.fixture
def template_status_fixture():
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "123456789",
            "changes": [{
                "field": "message_template_status_update",
                "value": {
                    "messaging_product": "whatsapp",
                    "message_template_id": 12345,
                    "message_template_name": "promo_welcome",
                    "message_template_language": "it",
                    "message_template_status": "APPROVED",
                    "event": "UPDATE",
                    "reason": None,
                },
            }],
        }],
    }


@pytest.fixture
def app_config():
    from src.whatsapp.config import AppConfig
    return AppConfig(
        app_secret="test_app_secret_123",
        encryption_key="C1IuGfMh142ShEqV9Y2w3WPcMjIjO4aXjbnly7sqlvw=",
        postgres_dsn="postgresql://test:test@localhost:5432/test",
        verify_token="test_verify_token",
        max_retry_attempts=5,
    )
