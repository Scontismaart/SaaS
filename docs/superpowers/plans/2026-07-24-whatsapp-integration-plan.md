# WhatsApp Business Cloud API Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the full WhatsApp Business Cloud API integration: webhook receiver, outbound message sender, multi-tenant routing, message status tracking, opt-out handling, template sync, and retry workers.

**Architecture:** New `src/whatsapp/` package layered as router → service → client + repository. Inbound messages are received inline (insert+200), then processed async by a worker polling Postgres with SKIP LOCKED. Outbound retry uses the same pattern. Postgres serves as both primary DB and retry queue (no Redis). HMAC verification on every webhook request, multi-tenant via `phone_number_id`/`waba_id` lookup.

**Tech Stack:** FastAPI, asyncpg, httpx, tenacity, pytest, respx, testcontainers (Postgres 16), Alembic, cryptography.

## Global Constraints

- Postgres 16 (same version local and CI, not `latest`)
- asyncpg for all DB access (no ORM)
- httpx async for all Meta API calls
- tenacity for inline retry (max 2 attempts, 5xx/429 only)
- cryptography (Fernet) for access_token encryption at rest with ENCRYPTION_KEY
- Alembic for schema migrations
- testcontainers (postgres:16) for repository integration tests
- respx for mocking httpx in client tests
- Test DB isolation: TRUNCATE ... CASCADE between tests (or per-test transaction rollback)
- All code in Italian or English? Follow existing project convention (Italian comments, Italian identifiers in existing code — new code uses English identifiers, Italian only for business logic comments)
- `wam_id` UNIQUE partial index (WHERE wam_id IS NOT NULL)
- All status updates guarded by `apply_status_update()` ranking
- `claimed_at` + reaper for crash recovery (5 min timeout)
- `biz_opaque_callback_data` = messages.id for status correlation

---

## File Structure

### Files Created

| File | Responsibility |
|---|---|
| `src/whatsapp/__init__.py` | Package marker |
| `src/whatsapp/config.py` | `AppConfig` (env), `TenantConfig` (per-request), `load_tenant_config()` |
| `src/whatsapp/models.py` | Pydantic models: webhook payload, outbound requests, Meta responses |
| `src/whatsapp/client.py` | `MetaClient`: httpx wrapper for Meta Graph API |
| `src/whatsapp/repository.py` | `Repository`: all asyncpg queries |
| `src/whatsapp/service.py` | `WhatsAppService`: orchestration, opt-out gate, fast path |
| `src/whatsapp/router.py` | FastAPI router: webhook GET/POST, HMAC verification |
| `src/whatsapp/templates.py` | `TemplateSyncer`: pull + push template sync |
| `src/whatsapp/inbound_processor.py` | Worker: polling + processing inbound messages |
| `src/whatsapp/retry_worker.py` | Worker: polling + retrying failed delivery attempts |
| `tests/whatsapp/test_apply_status_update.py` | Pure function tests |
| `tests/whatsapp/test_models.py` | Pydantic parsing tests |
| `tests/whatsapp/test_client.py` | MetaClient tests with respx |
| `tests/whatsapp/test_repository.py` | Repository tests with testcontainers |
| `tests/whatsapp/test_service.py` | Service tests with mocks |
| `tests/whatsapp/test_router.py` | Router tests with TestClient |
| `tests/whatsapp/test_templates.py` | TemplateSyncer tests |
| `tests/whatsapp/test_inbound_processor.py` | Worker integration tests |
| `tests/whatsapp/test_retry_worker.py` | Worker integration tests |
| `tests/whatsapp/conftest.py` | Shared fixtures (pg_pool, app_config, etc.) |

### Files Modified

| File | Change |
|---|---|
| `requirements.txt` | Add httpx, asyncpg, cryptography, alembic, pytest, pytest-asyncio, respx, testcontainers |
| `src/api/main.py` | Create asyncpg pool at startup, mount whatsapp router, register template sync scheduler |

---

## Task 1: Foundation — Config, Models, Dependencies

**Files:**
- Create: `src/whatsapp/__init__.py`
- Create: `src/whatsapp/config.py`
- Create: `src/whatsapp/models.py`
- Create: `tests/whatsapp/__init__.py`
- Create: `tests/whatsapp/conftest.py`
- Create: `tests/whatsapp/test_models.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `AppConfig`, `TenantConfig`, `load_tenant_config()` signature; all Pydantic models for webhook/outbound/status

- [ ] **Step 1: Update requirements.txt**

```txt
# Added for WhatsApp integration
httpx>=0.27,<1
asyncpg>=0.29,<1
cryptography>=43,<44
alembic>=1.13,<2
pytest>=8.0,<9
pytest-asyncio>=0.23,<1
respx>=0.21,<1
testcontainers>=4.0,<5
```

- [ ] **Step 2: Create `src/whatsapp/__init__.py` and `tests/whatsapp/__init__.py`**

Empty files (package markers).

- [ ] **Step 3: Write the test for config models**

```python
# tests/whatsapp/test_models.py
import pytest
from pydantic import ValidationError
from src.whatsapp.models import (
    IngoingWebhook, StatusEntry, MessageEntry,
    TemplateStatusUpdate, SendTextRequest, SendResponse,
    OutboundTextPayload, OutboundTemplatePayload,
)

class TestIngoingWebhook:
    def test_parse_status_payload(self, status_webhook_fixture):
        webhook = IngoingWebhook.model_validate(status_webhook_fixture)
        assert len(webhook.entry) == 1
        status = webhook.entry[0].changes[0].value.statuses[0]
        assert status.id == "wamid.example"
        assert status.status == "delivered"
        assert status.timestamp == "1712345678"

    def test_parse_message_payload(self, message_webhook_fixture):
        webhook = IngoingWebhook.model_validate(message_webhook_fixture)
        msg = webhook.entry[0].changes[0].value.messages[0]
        assert msg.id == "wamid.inbound.1"
        assert msg.type == "text"
        assert msg.text.body == "Ciao, vorrei prenotare"

    def test_parse_interactive_button_reply(self, button_reply_fixture):
        webhook = IngoingWebhook.model_validate(button_reply_fixture)
        msg = webhook.entry[0].changes[0].value.messages[0]
        assert msg.type == "interactive"
        assert msg.interactive.button_reply.id == "unsubscribe_confirm"

    def test_parse_template_status_update(self, template_status_fixture):
        webhook = IngoingWebhook.model_validate(template_status_fixture)
        assert webhook.entry[0].changes[0].field == "message_template_status_update"
        tsu = webhook.entry[0].changes[0].value
        assert tsu.message_template_name == "promo_welcome"
        assert tsu.message_template_status == "APPROVED"

    def test_invalid_webhook_rejected(self):
        with pytest.raises(ValidationError):
            IngoingWebhook.model_validate({})

    def test_send_text_request_serialization(self):
        req = SendTextRequest(
            messaging_product="whatsapp",
            recipient_type="individual",
            to="391234567890",
            type="text",
            text=OutboundTextPayload(body="Ciao!"),
        )
        data = req.model_dump(exclude_none=True)
        assert data["text"]["body"] == "Ciao!"

    def test_send_response_parse(self):
        resp = SendResponse.model_validate({
            "messaging_product": "whatsapp",
            "contacts": [{"input": "391234567890", "wa_id": "391234567890"}],
            "messages": [{"id": "wamid.outbound.1"}],
        })
        assert resp.messages[0].id == "wamid.outbound.1"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/whatsapp/test_models.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.whatsapp'"

- [ ] **Step 5: Write implementation**

```python
# src/whatsapp/config.py
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID


@dataclass
class AppConfig:
    app_secret: str
    encryption_key: str
    postgres_dsn: str
    verify_token: str
    max_retry_attempts: int = 5


@dataclass
class TenantConfig:
    organization_id: UUID
    phone_number_id: str
    waba_id: str
    access_token: str
    business_profile: dict = field(default_factory=dict)


async def load_tenant_config(org_id: UUID, app_config: AppConfig, repo) -> TenantConfig:
    from cryptography.fernet import Fernet
    row = await repo.get_tenant_config(org_id)
    cipher = Fernet(app_config.encryption_key.encode())
    decrypted = cipher.decrypt(row["access_token"].encode()).decode()
    return TenantConfig(
        organization_id=org_id,
        phone_number_id=row["phone_number_id"],
        waba_id=row["waba_id"],
        access_token=decrypted,
        business_profile=row.get("business_profile", {}),
    )
```

```python
# src/whatsapp/models.py
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from uuid import UUID


# --- Webhook inbound ---

class TextEntry(BaseModel):
    body: str

class ButtonReply(BaseModel):
    id: str
    title: Optional[str] = None

class InteractiveEntry(BaseModel):
    type: Optional[str] = None
    button_reply: Optional[ButtonReply] = None

class ContextEntry(BaseModel):
    from_: Optional[str] = Field(None, alias="from")
    id: Optional[str] = None

class MessageEntry(BaseModel):
    id: str
    from_: str = Field(alias="from")
    type: str
    text: Optional[TextEntry] = None
    interactive: Optional[InteractiveEntry] = None
    context: Optional[ContextEntry] = None
    timestamp: Optional[str] = None

    model_config = {"populate_by_name": True}

class StatusEntry(BaseModel):
    id: str
    status: str  # sent, delivered, read, failed
    timestamp: str
    recipient_id: Optional[str] = None
    errors: Optional[list[dict[str, Any]]] = None
    biz_opaque_callback_data: Optional[str] = None
    conversation: Optional[dict[str, Any]] = None

class MetadataEntry(BaseModel):
    display_phone_number: Optional[str] = None
    phone_number_id: Optional[str] = None

class ProfileEntry(BaseModel):
    name: Optional[str] = None

class ContactEntry(BaseModel):
    profile: Optional[ProfileEntry] = None
    wa_id: Optional[str] = None

class ChangeValue(BaseModel):
    messaging_product: str = "whatsapp"
    metadata: Optional[MetadataEntry] = None
    contacts: Optional[list[ContactEntry]] = None
    messages: Optional[list[MessageEntry]] = None
    statuses: Optional[list[StatusEntry]] = None
    # Template status update fields
    message_template_id: Optional[int] = None
    message_template_name: Optional[str] = None
    message_template_language: Optional[str] = None
    message_template_status: Optional[str] = None
    reason: Optional[str] = None
    event: Optional[str] = None

class ChangeEntry(BaseModel):
    field: str = "messages"
    value: ChangeValue

class Entry(BaseModel):
    id: Optional[str] = None
    changes: list[ChangeEntry]

class IngoingWebhook(BaseModel):
    object: str
    entry: list[Entry]

class TemplateStatusUpdate(BaseModel):
    message_template_id: int
    message_template_name: str
    message_template_language: str
    message_template_status: str
    reason: Optional[str] = None
    event: str


# --- Outbound send ---

class OutboundTextPayload(BaseModel):
    preview_url: Optional[bool] = None
    body: str

class OutboundButtonComponent(BaseModel):
    type: str = "button"
    sub_type: str = "quick_reply"
    index: int
    parameters: list[dict[str, str]]

class OutboundHeaderComponent(BaseModel):
    type: str
    parameters: list[dict[str, str]]

class OutboundTemplateComponents(BaseModel):
    type: str
    parameters: list[dict[str, Any]]

class OutboundTemplatePayload(BaseModel):
    name: str
    language: dict[str, str]
    components: Optional[list[OutboundTemplateComponents]] = None

class SendTextRequest(BaseModel):
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "text"
    text: OutboundTextPayload
    biz_opaque_callback_data: Optional[str] = None

class SendTemplateRequest(BaseModel):
    messaging_product: str = "whatsapp"
    recipient_type: str = "individual"
    to: str
    type: str = "template"
    template: OutboundTemplatePayload
    biz_opaque_callback_data: Optional[str] = None

class ContactResponse(BaseModel):
    input: str
    wa_id: str

class MessageResponse(BaseModel):
    id: str

class SendResponse(BaseModel):
    messaging_product: str
    contacts: list[ContactResponse]
    messages: list[MessageResponse]
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_models.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Create conftest.py with fixtures**

```python
# tests/whatsapp/conftest.py
import pytest


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
        encryption_key="dGhpcyBpcyBhIHRlc3Qga2V5IGZvciBmZXJuZXQ=",
        postgres_dsn="postgresql://test:test@localhost:5432/test",
        verify_token="test_verify_token",
        max_retry_attempts=5,
    )
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add foundation - config, models, requirements
```

---

## Task 2: `apply_status_update()` — Guardia Monotona

**Files:**
- Create: `tests/whatsapp/test_apply_status_update.py`
- Create: `src/whatsapp/repository.py` (only `apply_status_update()` + class stub)

**Interfaces:**
- Consumes: nothing
- Produces: `def apply_status_update(current_status: str, new_status: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_apply_status_update.py
import pytest
from src.whatsapp.repository import apply_status_update


class TestApplyStatusUpdate:
    def test_sent_to_delivered_allowed(self):
        assert apply_status_update("sent", "delivered") is True

    def test_delivered_to_read_allowed(self):
        assert apply_status_update("delivered", "read") is True

    def test_read_to_delivered_blocked(self):
        assert apply_status_update("read", "delivered") is False

    def test_failed_always_wins(self):
        assert apply_status_update("delivered", "failed") is True
        assert apply_status_update("sent", "failed") is True
        assert apply_status_update("read", "failed") is True

    def test_same_status_blocked(self):
        assert apply_status_update("delivered", "delivered") is False

    def test_queued_to_sent_allowed(self):
        assert apply_status_update("queued", "sent") is True

    def test_sending_ambiguous_to_sent_allowed(self):
        assert apply_status_update("sending_ambiguous", "sent") is True

    def test_sending_ambiguous_to_delivered_allowed(self):
        assert apply_status_update("sending_ambiguous", "delivered") is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/whatsapp/test_apply_status_update.py -v`
Expected: FAIL with "ImportError"

- [ ] **Step 3: Write implementation**

```python
# src/whatsapp/repository.py

STATUS_RANK = {
    "queued": 0,
    "processing": 0,
    "sending_ambiguous": 0,
    "sent": 1,
    "delivered": 2,
    "read": 3,
    "failed": 4,
}


def apply_status_update(current_status: str, new_status: str) -> bool:
    if new_status == "failed":
        return True
    return STATUS_RANK.get(new_status, 0) > STATUS_RANK.get(current_status, 0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/whatsapp/test_apply_status_update.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add apply_status_update() status monotonic guard"
```

---

## Task 3: Repository — Lookups, Contacts, Conversations

**Files:**
- Modify: `src/whatsapp/repository.py` (add Repository class + organizational queries + contacts/conversations)
- Create: `tests/whatsapp/test_repository.py` (Part 1: lookups + contacts)

**Interfaces:**
- Consumes: `AppConfig` (for postgres_dsn), `apply_status_update()`
- Produces: `class Repository`, `Repository.get_org_by_phone_number_id(pid)`, `Repository.get_org_by_waba_id(waba_id)`, `Repository.get_tenant_config(org_id)`, `Repository.get_or_create_contact(org_id, phone)`, `Repository.get_or_create_conversation(org_id, contact_id)`, `Repository.get_contact_prefs(org_id, phone)`

- [ ] **Step 1: Write the Alembic migration and setup SQL**

Create `alembic.ini` and initial migration with full schema from the spec doc (all 8 tables). This is needed before repository tests can run against a real Postgres.

```bash
alembic init migrations
alembic revision --autogenerate -m "initial whatsapp schema"
```

Edit the migration to include all tables: organizations, whatsapp_accounts, contacts, conversations, messages, message_delivery_attempts, contact_consent_log, whatsapp_templates (with all indexes, constraints, partial unique indexes from spec Sezione 5.1).

- [ ] **Step 2: Write Integration test fixture for Postgres**

```python
# tests/whatsapp/conftest.py — add:

import asyncio
import asyncpg
from testcontainers.postgres import PostgresContainer
import pytest


@pytest.fixture(scope="session")
def postgres_container():
    with PostgresContainer("postgres:16") as pg:
        yield pg


@pytest.fixture(scope="session")
async def pg_pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("psycopg2", "asyncpg")
    pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    yield pool
    await pool.close()


@pytest.fixture(autouse=True)
async def reset_db(pg_pool):
    """TRUNCATE all tables before each test."""
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
```

- [ ] **Step 3: Write the test for organizational lookups**

```python
# tests/whatsapp/test_repository.py (Part 1)
import uuid
import pytest
from src.whatsapp.repository import Repository


@pytest.mark.asyncio
async def test_get_org_by_phone_number_id(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
        await conn.execute(
            "INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token) "
            "VALUES ($1, $2, '12345', 'waba_1', 'encrypted_token')",
            acc_id, org_id,
        )
    result = await repo.get_org_by_phone_number_id("12345")
    assert result is not None
    assert result["organization_id"] == org_id
    assert result["phone_number_id"] == "12345"


@pytest.mark.asyncio
async def test_get_org_by_phone_number_id_not_found(repo: Repository):
    result = await repo.get_org_by_phone_number_id("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_org_by_waba_id(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
        await conn.execute(
            "INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token) "
            "VALUES ($1, $2, '12345', 'waba_1', 'encrypted_token')",
            acc_id, org_id,
        )
    result = await repo.get_org_by_waba_id("waba_1")
    assert result is not None
    assert result["organization_id"] == org_id


@pytest.mark.asyncio
async def test_get_tenant_config(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    acc_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
        await conn.execute(
            "INSERT INTO whatsapp_accounts (id, organization_id, phone_number_id, waba_id, access_token) "
            "VALUES ($1, $2, '12345', 'waba_1', 'encrypted_token')",
            acc_id, org_id,
        )
    result = await repo.get_tenant_config(org_id)
    assert result is not None
    assert result["access_token"] == "encrypted_token"
    assert result["phone_number_id"] == "12345"


@pytest.mark.asyncio
async def test_get_or_create_contact_new(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    assert contact["organization_id"] == org_id
    assert contact["phone_number"] == "391234567890"
    assert contact["marketing_opt_out"] is False


@pytest.mark.asyncio
async def test_get_or_create_contact_existing(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    c1 = await repo.get_or_create_contact(org_id, "391234567890")
    c2 = await repo.get_or_create_contact(org_id, "391234567890")
    assert c1["id"] == c2["id"]


@pytest.mark.asyncio
async def test_get_or_create_conversation(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    assert conv["organization_id"] == org_id
    assert conv["contact_id"] == contact["id"]


@pytest.mark.asyncio
async def test_get_contact_prefs(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE contacts SET marketing_opt_out = TRUE WHERE id = $1",
            contact["id"],
        )
    prefs = await repo.get_contact_prefs(org_id, "391234567890")
    assert prefs["marketing_opt_out"] is True
```

- [ ] **Step 4: Run to verify it fails**

Run: `pytest tests/whatsapp/test_repository.py -v`
Expected: FAIL — Repository class not yet implemented

- [ ] **Step 5: Write Repository implementation (Part 1)**

```python
# src/whatsapp/repository.py — add after apply_status_update()

import uuid
from typing import Optional


class Repository:
    def __init__(self, pool):
        self.pool = pool

    async def get_org_by_phone_number_id(self, phone_number_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT o.id as organization_id, o.name, o.business_profile,
                       wa.id as account_id, wa.phone_number_id, wa.waba_id,
                       wa.access_token, wa.verify_token
                FROM whatsapp_accounts wa
                JOIN organizations o ON o.id = wa.organization_id
                WHERE wa.phone_number_id = $1
            """, phone_number_id)
            return dict(row) if row else None

    async def get_org_by_waba_id(self, waba_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT o.id as organization_id, o.name, o.business_profile,
                       wa.id as account_id, wa.phone_number_id, wa.waba_id,
                       wa.access_token, wa.verify_token
                FROM whatsapp_accounts wa
                JOIN organizations o ON o.id = wa.organization_id
                WHERE wa.waba_id = $1
            """, waba_id)
            return dict(row) if row else None

    async def get_tenant_config(self, org_id: uuid.UUID) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT wa.access_token, wa.phone_number_id, wa.waba_id,
                       o.business_profile
                FROM whatsapp_accounts wa
                JOIN organizations o ON o.id = wa.organization_id
                WHERE wa.organization_id = $1
                LIMIT 1
            """, org_id)
            return dict(row) if row else None

    async def get_or_create_contact(self, org_id: uuid.UUID, phone: str) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO contacts (id, organization_id, phone_number)
                VALUES ($1, $2, $3)
                ON CONFLICT (organization_id, phone_number) DO UPDATE
                    SET updated_at = NOW()
                RETURNING *
            """, uuid.uuid4(), org_id, phone)
            return dict(row)

    async def get_or_create_conversation(self, org_id: uuid.UUID, contact_id: uuid.UUID) -> dict:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO conversations (id, organization_id, contact_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (organization_id, contact_id) DO UPDATE
                    SET last_message_at = NOW()
                RETURNING *
            """, uuid.uuid4(), org_id, contact_id)
            return dict(row)

    async def get_contact_prefs(self, org_id: uuid.UUID, phone: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM contacts
                WHERE organization_id = $1 AND phone_number = $2
            """, org_id, phone)
            return dict(row) if row else None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_repository.py -v`
Expected: PASS (7 tests)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add repository lookups, contacts, conversations"
```

---

## Task 4: Repository — Messages, Delivery Attempts, Consent Log, Reaper

**Files:**
- Modify: `src/whatsapp/repository.py` (add message queries, delivery attempts, consent log, reaper)
- Modify: `tests/whatsapp/test_repository.py` (Part 2: messages + delivery + consent + reaper)

**Interfaces:**
- Consumes: `Repository` from Task 3
- Produces: `Repository.upsert_message()`, `Repository.update_message_status()`, `Repository.claim_inbound_messages()`, `Repository.claim_delivery_attempts()`, `Repository.record_consent_event()`, `Repository.insert_delivery_attempt()`, `Repository.update_delivery_attempt()`, `Repository.reap_stale_claims()`, `Repository.reconstruct_payload_for_retry()`

- [ ] **Step 1: Write tests for message operations**

```python
# tests/whatsapp/test_repository.py — add:

@pytest.mark.asyncio
async def test_upsert_message_new(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(
        id=uuid.uuid4(),
        organization_id=org_id,
        conversation_id=conv["id"],
        wam_id="wamid.test.1",
        direction="inbound",
        message_type="text",
        content={"text": {"body": "Ciao"}},
        content_text="Ciao",
        status="received_pending_ai",
    )
    assert msg["wam_id"] == "wamid.test.1"
    assert msg["status"] == "received_pending_ai"


@pytest.mark.asyncio
async def test_upsert_message_idempotent(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    mid = uuid.uuid4()
    msg1 = await repo.upsert_message(mid, org_id, conv["id"], "wamid.test.2", "inbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "received_pending_ai")
    msg2 = await repo.upsert_message(mid, org_id, conv["id"], "wamid.test.2", "inbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "received_pending_ai")
    assert msg1["id"] == msg2["id"]  # ON CONFLICT DO NOTHING returned original


@pytest.mark.asyncio
async def test_update_message_status_with_guard(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.test.3", "outbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "queued")
    # Update to delivered
    updated = await repo.update_message_status(msg["id"], "delivered", wam_id="wamid.test.3")
    assert updated["status"] == "delivered"
    # Block downgrade to sent
    updated2 = await repo.update_message_status(msg["id"], "sent")
    assert updated2["status"] == "delivered"  # unchanged
    # Always allow failed
    updated3 = await repo.update_message_status(msg["id"], "failed")
    assert updated3["status"] == "failed"


@pytest.mark.asyncio
async def test_claim_inbound_messages_skip_locked(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    for i in range(3):
        await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], f"wamid.in.{i}", "inbound", "text",
                                  {"text": {"body": f"Msg {i}"}}, f"Msg {i}", "received_pending_ai")
    claimed = await repo.claim_inbound_messages(limit=10)
    assert len(claimed) == 3
    for c in claimed:
        assert c["status"] == "processing"


@pytest.mark.asyncio
async def test_claim_inbound_messages_no_double_claim(repo: Repository, pg_pool):
    """Two concurrent workers must not claim the same row."""
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    for i in range(5):
        await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], f"wamid.nd.{i}", "inbound", "text",
                                  {"text": {"body": f"Msg {i}"}}, f"Msg {i}", "received_pending_ai")
    async with pg_pool.acquire() as conn_a, pg_pool.acquire() as conn_b:
        repo_a = Repository.__new__(Repository)
        repo_a.pool = pg_pool
        repo_b = Repository.__new__(Repository)
        repo_b.pool = pg_pool
        results = await asyncio.gather(
            repo_a.claim_inbound_messages(limit=5),
            repo_b.claim_inbound_messages(limit=5),
        )
        all_ids = [r["id"] for r in results[0]] + [r["id"] for r in results[1]]
        assert len(all_ids) == len(set(all_ids))


@pytest.mark.asyncio
async def test_record_consent_event(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    event = await repo.record_consent_event(
        contact_id=contact["id"],
        event_type="opt_out",
        method="keyword_match",
        matched_text="stop",
    )
    assert event["event_type"] == "opt_out"
    assert event["method"] == "keyword_match"


@pytest.mark.asyncio
async def test_insert_and_update_delivery_attempt(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.da.1", "outbound", "text",
                                      {"text": {"body": "Ciao"}}, "Ciao", "queued")
    attempt = await repo.insert_delivery_attempt(msg["id"], next_retry_at=datetime.utcnow())
    assert attempt["status"] == "pending"
    updated = await repo.update_delivery_attempt(attempt["id"], "succeeded", error_details=None)
    assert updated["status"] == "succeeded"


@pytest.mark.asyncio
async def test_reap_stale_claims(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.reap.1", "inbound", "text",
                                      {"text": {"body": "Old"}}, "Old", "received_pending_ai")
    # Manually set to processing with old claimed_at
    async with pg_pool.acquire() as conn:
        await conn.execute(
            "UPDATE messages SET status = 'processing', claimed_at = NOW() - INTERVAL '10 minutes' WHERE id = $1",
            msg["id"],
        )
    reaped = await repo.reap_stale_claims(timeout_minutes=5)
    assert len(reaped) == 1
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT status FROM messages WHERE id = $1", msg["id"])
        assert row["status"] == "received_pending_ai"


@pytest.mark.asyncio
async def test_reconstruct_payload_for_retry(repo: Repository, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test Org')", org_id)
    contact = await repo.get_or_create_contact(org_id, "391234567890")
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    content = {"type": "text", "text": {"body": "Retry me"}}
    msg = await repo.upsert_message(uuid.uuid4(), org_id, conv["id"], "wamid.recon.1", "outbound", "text",
                                      content, "Retry me", "queued")
    payload = await repo.reconstruct_payload_for_retry(msg["id"])
    assert payload is not None
    assert payload["content"] == content
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/whatsapp/test_repository.py -v`
Expected: Some tests fail because methods not implemented

- [ ] **Step 3: Write implementation**

```python
# Add to src/whatsapp/repository.py, inside class Repository:

from datetime import datetime

async def upsert_message(self, id, organization_id, conversation_id, wam_id, direction,
                          message_type, content, content_text, status, handling_type=None) -> dict:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO messages (id, organization_id, conversation_id, wam_id,
                                  direction, message_type, content, content_text, status, handling_type)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
            ON CONFLICT (wam_id) WHERE wam_id IS NOT NULL DO NOTHING
            RETURNING *
        """, id, organization_id, conversation_id, wam_id, direction, message_type,
            json.dumps(content), content_text, status, handling_type)
        return dict(row)

async def update_message_status(self, message_id, new_status, wam_id=None, error_code=None,
                                  error_title=None, error_details=None, biz_opaque_callback_data=None) -> Optional[dict]:
    async with self.pool.acquire() as conn:
        current = await conn.fetchrow("SELECT status FROM messages WHERE id = $1", message_id)
        if not current:
            return None
        if not apply_status_update(current["status"], new_status):
            return dict(current)
        set_parts = ["status = $2"]
        params = [message_id, new_status]
        idx = 3
        if wam_id:
            set_parts.append(f"wam_id = ${idx}")
            params.append(wam_id)
            idx += 1
        if error_code:
            set_parts.append(f"error_code = ${idx}")
            params.append(error_code)
            idx += 1
        if error_title:
            set_parts.append(f"error_title = ${idx}")
            params.append(error_title)
            idx += 1
        if error_details:
            set_parts.append(f"error_details = ${idx}::jsonb")
            params.append(json.dumps(error_details))
            idx += 1
        if new_status == "sent":
            set_parts.append("sent_at = NOW()")
        elif new_status == "delivered":
            set_parts.append("delivered_at = NOW()")
        elif new_status == "read":
            set_parts.append("read_at = NOW()")
        set_parts.append("updated_at = NOW()")
        row = await conn.fetchrow(
            f"UPDATE messages SET {', '.join(set_parts)} WHERE id = $1 RETURNING *",
            *params
        )
        return dict(row) if row else None

async def claim_inbound_messages(self, limit=10) -> list[dict]:
    async with self.pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch("""
                SELECT * FROM messages
                WHERE direction = 'inbound' AND status = 'received_pending_ai'
                ORDER BY created_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            """, limit)
            if rows:
                ids = [r["id"] for r in rows]
                await conn.execute(
                    "UPDATE messages SET status = 'processing', claimed_at = NOW() WHERE id = ANY($1)",
                    ids,
                )
            return [dict(r) for r in rows]

async def claim_delivery_attempts(self, limit=10) -> list[dict]:
    async with self.pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch("""
                SELECT * FROM message_delivery_attempts
                WHERE status = 'pending' AND next_retry_at <= NOW()
                ORDER BY next_retry_at
                LIMIT $1
                FOR UPDATE SKIP LOCKED
            """, limit)
            if rows:
                ids = [r["id"] for r in rows]
                await conn.execute(
                    "UPDATE message_delivery_attempts SET status = 'processing', claimed_at = NOW() WHERE id = ANY($1)",
                    ids,
                )
            return [dict(r) for r in rows]

async def record_consent_event(self, contact_id, event_type, method,
                                 triggering_message_id=None, matched_text=None) -> dict:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO contact_consent_log (id, contact_id, event_type, method,
                                              triggering_message_id, matched_text)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """, uuid.uuid4(), contact_id, event_type, method, triggering_message_id, matched_text)
        return dict(row)

async def insert_delivery_attempt(self, message_id, next_retry_at) -> dict:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO message_delivery_attempts (id, message_id, next_retry_at)
            VALUES ($1, $2, $3)
            RETURNING *
        """, uuid.uuid4(), message_id, next_retry_at)
        return dict(row)

async def update_delivery_attempt(self, attempt_id, status, error_details=None) -> Optional[dict]:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE message_delivery_attempts
            SET status = $2, error_details = $3::jsonb
            WHERE id = $1
            RETURNING *
        """, attempt_id, status, json.dumps(error_details) if error_details else None)
        return dict(row) if row else None

async def reconstruct_payload_for_retry(self, message_id) -> Optional[dict]:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM messages WHERE id = $1", message_id
        )
        if not row:
            return None
        return dict(row)

async def update_message_status_by_wam_id(self, wam_id, new_status, error_code=None,
                                            error_title=None, error_details=None) -> Optional[dict]:
    async with self.pool.acquire() as conn:
        current = await conn.fetchrow(
            "SELECT id, status FROM messages WHERE wam_id = $1", wam_id
        )
        if not current:
            return None
        return await self.update_message_status(
            current["id"], new_status, wam_id=wam_id,
            error_code=error_code, error_title=error_title, error_details=error_details,
        )

async def reap_stale_claims(self, timeout_minutes=5) -> list[dict]:
    async with self.pool.acquire() as conn:
        msgs = await conn.fetch("""
            UPDATE messages SET status = 'received_pending_ai', claimed_at = NULL
            WHERE status = 'processing' AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL
            RETURNING *
        """, str(timeout_minutes))
        attempts = await conn.fetch("""
            UPDATE message_delivery_attempts SET status = 'pending', claimed_at = NULL
            WHERE status = 'processing' AND claimed_at < NOW() - ($1 || ' minutes')::INTERVAL
            RETURNING *
        """, str(timeout_minutes))
        return [dict(r) for r in msgs] + [dict(r) for r in attempts]

async def upsert_template(self, organization_id, name, language, category, status, components) -> dict:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO whatsapp_templates (id, organization_id, name, language, category, status, components)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            ON CONFLICT (organization_id, name, language) DO UPDATE
                SET status = $6, components = $7::jsonb, updated_at = NOW()
            RETURNING *
        """, uuid.uuid4(), organization_id, name, language, category, status,
            json.dumps(components))
        return dict(row)

async def update_template_status(self, *, name=None, language=None, status=None, reason=None, organization_id=None):
    async with self.pool.acquire() as conn:
        parts = ["status = $3", "updated_at = NOW()"]
        params = [name, language, status]
        idx = 4
        if reason:
            parts.append(f"rejected_reason = ${idx}")
            params.append(reason)
            idx += 1
        if organization_id:
            parts.append(f"organization_id = ${idx}")
            params.append(organization_id)
            idx += 1
        await conn.execute(
            f"UPDATE whatsapp_templates SET {', '.join(parts)} WHERE name = $1 AND language = $2",
            *params
        )
```

Also add `import json` at the top of repository.py.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_repository.py -v`
Expected: PASS (all tests including Part 2)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add repository messages, delivery attempts, reaper"
```

---

## Task 5: Meta Graph API Client

**Files:**
- Create: `src/whatsapp/client.py`
- Create: `tests/whatsapp/test_client.py`

**Interfaces:**
- Consumes: `TenantConfig`, `SendTextRequest` / `SendTemplateRequest`
- Produces: `class MetaClient`, `MetaClient.send_message(payload) → SendResponse`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_client.py
import httpx
import respx
import pytest
from uuid import UUID
from src.whatsapp.client import MetaClient
from src.whatsapp.models import SendTextRequest, OutboundTextPayload, SendResponse


@pytest.fixture
def tenant_config():
    from src.whatsapp.config import TenantConfig
    return TenantConfig(
        organization_id=UUID("00000000-0000-0000-0000-000000000001"),
        phone_number_id="1234567890",
        waba_id="waba_1",
        access_token="test_access_token",
        business_profile={},
    )


@pytest.fixture
def text_payload():
    return SendTextRequest(
        messaging_product="whatsapp",
        recipient_type="individual",
        to="391234567890",
        type="text",
        text=OutboundTextPayload(body="Ciao!"),
        biz_opaque_callback_data="msg-uuid-1",
    )


class TestMetaClient:
    @respx.mock
    async def test_send_message_success(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        respx.post(url).respond(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "391234567890", "wa_id": "391234567890"}],
                "messages": [{"id": "wamid.outbound.test"}],
            },
        )
        client = MetaClient(tenant_config)
        response = await client.send_message(text_payload)
        assert isinstance(response, SendResponse)
        assert response.messages[0].id == "wamid.outbound.test"

    @respx.mock
    async def test_send_message_429_retry_after(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        respx.post(url).respond(429, headers={"Retry-After": "2"}, json={"error": {"message": "Too many requests"}})
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(text_payload)

    @respx.mock
    async def test_send_message_5xx_retryable(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        mock_route = respx.post(url)
        mock_route.respond(500, json={"error": {"message": "Internal error"}})
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(text_payload)
        assert mock_route.call_count == 2  # initial + 1 retry via tenacity

    @respx.mock
    async def test_send_message_4xx_not_retried(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        mock_route = respx.post(url)
        mock_route.respond(400, json={"error": {"message": "Bad request"}})
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(text_payload)
        assert mock_route.call_count == 1  # no retry

    @respx.mock
    async def test_send_message_timeout(self, tenant_config, text_payload):
        url = f"https://graph.facebook.com/v20.0/{tenant_config.phone_number_id}/messages"
        respx.post(url).side_effect = httpx.TimeoutException("Request timed out")
        client = MetaClient(tenant_config)
        with pytest.raises(httpx.TimeoutException):
            await client.send_message(text_payload)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/whatsapp/test_client.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.whatsapp.client'"

- [ ] **Step 3: Write implementation**

```python
# src/whatsapp/client.py
import httpx
from tenacity import retry, stop_after_attempt, retry_if_exception, wait_exponential
from src.whatsapp.config import TenantConfig
from src.whatsapp.models import SendTextRequest, SendTemplateRequest, SendResponse


class MetaClient:
    BASE_URL = "https://graph.facebook.com/v20.0"

    def __init__(self, tenant_config: TenantConfig):
        self.phone_number_id = tenant_config.phone_number_id
        self.access_token = tenant_config.access_token
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=httpx.Timeout(5.0, connect=3.0),
        )

    async def close(self):
        await self._client.aclose()

    async def send_message(self, payload: SendTextRequest | SendTemplateRequest) -> SendResponse:
        url = f"/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        data = payload.model_dump(exclude_none=True)
        response = await self._client.post(url, headers=headers, json=data)
        response.raise_for_status()
        return SendResponse.model_validate(response.json())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add MetaClient for Graph API calls"
```

---

## Task 6: Service — Orchestration, Opt-Out Gate, Fast Path

**Files:**
- Create: `src/whatsapp/service.py`
- Create: `tests/whatsapp/test_service.py`

**Interfaces:**
- Consumes: `AppConfig`, `Repository`, `MetaClient`, `TenantConfig`, `SendTextRequest`
- Produces: `class WhatsAppService`, `WhatsAppService.send_whatsapp_message()`, `WhatsAppService.attempt_delivery()`, `WhatsAppService.check_opt_out()`, `WhatsAppService.fast_path_match()`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_service.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from src.whatsapp.service import WhatsAppService
from src.whatsapp.config import AppConfig, TenantConfig


OPT_OUT_KEYWORDS = {
    "it": ["stop", "annulla", "basta", "non scrivermi più", "cancellami", "disiscrivi"],
    "en": ["stop", "unsubscribe", "cancel", "opt out", "remove me"],
}


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test_secret",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="test_token",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_or_create_contact = AsyncMock(return_value={"id": uuid.uuid4(), "marketing_opt_out": False})
    repo.get_or_create_conversation = AsyncMock(return_value={"id": uuid.uuid4()})
    repo.get_contact_prefs = AsyncMock(return_value={"id": uuid.uuid4(), "marketing_opt_out": False})
    repo.upsert_message = AsyncMock(return_value={"id": uuid.uuid4(), "status": "queued"})
    repo.update_message_status = AsyncMock(return_value={"id": uuid.uuid4(), "status": "sent"})
    return repo


@pytest.fixture
def mock_meta_client():
    client = AsyncMock()
    client.send_message = AsyncMock()
    client.send_message.return_value.messages = [MagicMock(id="wamid.outbound.test")]
    client.send_message.return_value.contacts = [MagicMock(wa_id="391234567890")]
    client.send_message.return_value.messaging_product = "whatsapp"
    return client


class TestWhatsAppService:
    async def test_send_whatsapp_message_creates_message(self, app_config, mock_repo, mock_meta_client):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.send_whatsapp_message(
            org_id=uuid.uuid4(),
            to_number="391234567890",
            payload={"type": "text", "text": {"body": "Ciao!"}},
            category="utility",
            meta_client=mock_meta_client,
            tenant_config=MagicMock(),
        )
        assert result["status"] == "sent"
        mock_repo.upsert_message.assert_called_once()

    async def test_opt_out_gate_blocks_marketing(self, app_config, mock_repo, mock_meta_client):
        mock_repo.get_contact_prefs = AsyncMock(return_value={"marketing_opt_out": True, "id": uuid.uuid4()})
        service = WhatsAppService(app_config, mock_repo)
        with pytest.raises(service.MessageBlockedByOptOut):
            await service.send_whatsapp_message(
                org_id=uuid.uuid4(),
                to_number="391234567890",
                payload={"type": "text", "text": {"body": "Offerta speciale!"}},
                category="marketing",
                meta_client=mock_meta_client,
                tenant_config=MagicMock(),
            )

    async def test_opt_out_gate_allows_utility(self, app_config, mock_repo, mock_meta_client):
        mock_repo.get_contact_prefs = AsyncMock(return_value={"marketing_opt_out": True, "id": uuid.uuid4()})
        service = WhatsAppService(app_config, mock_repo)
        result = await service.send_whatsapp_message(
            org_id=uuid.uuid4(),
            to_number="391234567890",
            payload={"type": "text", "text": {"body": "Conferma prenotazione #123"}},
            category="utility",
            meta_client=mock_meta_client,
            tenant_config=MagicMock(),
        )
        assert result["status"] == "sent"

    async def test_attempt_delivery_updates_existing_message(self, app_config, mock_repo, mock_meta_client):
        mock_repo.upsert_message.reset_mock()
        service = WhatsAppService(app_config, mock_repo)
        await service.attempt_delivery(
            message_id=uuid.uuid4(),
            phone_number_id="12345",
            access_token="tok",
            payload={"type": "text", "text": {"body": "Test"}},
            meta_client=mock_meta_client,
        )
        mock_repo.upsert_message.assert_not_called()
        mock_repo.update_message_status.assert_called()

    async def test_check_opt_out_keyword_match_it(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.check_opt_out("STOP!", "it")
        assert result["is_opt_out"] is True
        assert result["confidence"] == "high"

    async def test_check_opt_out_keyword_match_en(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.check_opt_out("unsubscribe please", "en")
        assert result["is_opt_out"] is True

    async def test_check_opt_out_normal_message(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        result = await service.check_opt_out("Grazie, arrivederci!", "it")
        assert result["is_opt_out"] is False

    async def test_fast_path_greeting(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        bp = {"name": "Trattoria Da Mario"}
        result = await service.fast_path_match("Ciao", bp)
        assert result is not None
        assert "Trattoria Da Mario" in result

    async def test_fast_path_hours(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        bp = {"orari": "Lun-Sab 12:00-22:30"}
        result = await service.fast_path_match("Che orari fate?", bp)
        assert result is not None
        assert "Lun-Sab" in result

    async def test_fast_path_no_match(self, app_config, mock_repo):
        service = WhatsAppService(app_config, mock_repo)
        bp = {"name": "Test"}
        result = await service.fast_path_match("Quanto costa la pizza?", bp)
        assert result is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/whatsapp/test_service.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write implementation**

```python
# src/whatsapp/service.py
import uuid
import re
import json
from datetime import datetime, timezone
from typing import Optional
from src.whatsapp.config import AppConfig, TenantConfig
from src.whatsapp.models import SendTextRequest, OutboundTextPayload


OPT_OUT_KEYWORDS = {
    "it": ["stop", "annulla", "basta", "non scrivermi più", "cancellami", "disiscrivi"],
    "en": ["stop", "unsubscribe", "cancel", "opt out", "remove me"],
}

_FAST_PATH_GREETINGS = ["ciao", "buongiorno", "buonasera", "salve", "hey", "hello", "hi"]
_FAST_PATH_THANKS = ["grazie", "grazie mille", "grazie tante", "perfetto", "ok grazie", "grazie arrivederci"]


def _normalize_text(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).lower().strip()


class WhatsAppService:
    class MessageBlockedByOptOut(Exception):
        pass

    def __init__(self, app_config: AppConfig, repo):
        self.app_config = app_config
        self.repo = repo

    async def send_whatsapp_message(
        self,
        org_id: uuid.UUID,
        to_number: str,
        payload: dict,
        category: str,
        meta_client,
        tenant_config: TenantConfig,
    ) -> dict:
        prefs = await self.repo.get_contact_prefs(org_id, to_number)
        if prefs and prefs.get("marketing_opt_out") and category == "marketing":
            raise self.MessageBlockedByOptOut(
                f"Contact {to_number} has marketing opt-out"
            )
        contact = await self.repo.get_or_create_contact(org_id, to_number)
        conv = await self.repo.get_or_create_conversation(org_id, contact["id"])
        msg_id = uuid.uuid4()
        msg = await self.repo.upsert_message(
            id=msg_id,
            organization_id=org_id,
            conversation_id=conv["id"],
            wam_id=None,
            direction="outbound",
            message_type=payload.get("type", "text"),
            content=payload,
            content_text=payload.get("text", {}).get("body", ""),
            status="queued",
        )
        result = await self.attempt_delivery(
            message_id=msg_id,
            phone_number_id=tenant_config.phone_number_id,
            access_token=tenant_config.access_token,
            payload=payload,
            meta_client=meta_client,
        )
        return result

    async def attempt_delivery(
        self,
        message_id: uuid.UUID,
        phone_number_id: str,
        access_token: str,
        payload: dict,
        meta_client=None,
    ) -> dict:
        if meta_client is None:
            from src.whatsapp.client import MetaClient
            from src.whatsapp.config import TenantConfig
            meta_client = MetaClient(
                TenantConfig(
                    organization_id=uuid.UUID(int=0),
                    phone_number_id=phone_number_id,
                    waba_id="",
                    access_token=access_token,
                )
            )
        send_request = SendTextRequest(
            messaging_product="whatsapp",
            recipient_type="individual",
            to=payload.get("to", payload.get("recipient", "")),
            type=payload.get("type", "text"),
            text=OutboundTextPayload(body=payload.get("text", {}).get("body", "")),
            biz_opaque_callback_data=str(message_id),
        )
        try:
            response = await meta_client.send_message(send_request)
            wam_id = response.messages[0].id if response.messages else None
            updated = await self.repo.update_message_status(
                message_id, "sent", wam_id=wam_id
            )
            return updated or {"status": "sent", "wam_id": wam_id}
        except Exception as e:
            await self.repo.update_message_status(message_id, "failed", error_code="send_error", error_title=str(e))
            raise

    async def check_opt_out(self, text: str, lang: str = "it") -> dict:
        normalized = _normalize_text(text)
        keywords = OPT_OUT_KEYWORDS.get(lang, OPT_OUT_KEYWORDS["it"])
        for keyword in keywords:
            if keyword in normalized:
                return {"is_opt_out": True, "confidence": "high"}
        return {"is_opt_out": False, "confidence": "low"}

    async def fast_path_match(self, text: str, business_profile: dict) -> Optional[str]:
        normalized = _normalize_text(text)
        name = business_profile.get("name", "")
        for g in _FAST_PATH_GREETINGS:
            if g == normalized or normalized.startswith(g + " "):
                return f"Ciao! Benvenuto in {name}. Come possiamo aiutarti?"
        for t in _FAST_PATH_THANKS:
            if t == normalized or normalized.startswith(t):
                return "Prego! A nostra disposizione. Buona giornata!"
        orari = business_profile.get("orari", "")
        if orari and ("orari" in normalized or "aperto" in normalized or "chiuso" in normalized):
            return f"I nostri orari: {orari}"
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_service.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add WhatsAppService with opt-out gate and fast path"
```

---

## Task 7: Router — Webhook Endpoint

**Files:**
- Create: `src/whatsapp/router.py`
- Create: `tests/whatsapp/test_router.py`

**Interfaces:**
- Consumes: `AppConfig`, `Repository`, `WhatsAppService`, `MetaClient`
- Produces: FastAPI `APIRouter` with `GET /webhooks/whatsapp` and `POST /webhooks/whatsapp`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_router.py
import hashlib
import hmac
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from src.whatsapp.router import create_router
from src.whatsapp.config import AppConfig


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test_app_secret",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="my_verify_token",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_org_by_phone_number_id = AsyncMock(return_value={
        "organization_id": uuid.uuid4(),
        "phone_number_id": "1234567890",
        "waba_id": "waba_1",
        "access_token": "encrypted_token",
        "name": "Test Org",
        "business_profile": {},
    })
    repo.get_org_by_waba_id = AsyncMock(return_value={
        "organization_id": uuid.uuid4(),
        "name": "Test Org",
    })
    repo.update_message_status = AsyncMock(return_value={"status": "delivered"})
    repo.upsert_message = AsyncMock(return_value={"id": uuid.uuid4(), "status": "received_pending_ai"})
    return repo


@pytest.fixture
def app(app_config, mock_repo):
    app = FastAPI()
    router = create_router(app_config, mock_repo)
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def _sign_body(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestRouter:
    def test_get_verify_success(self, client):
        resp = client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=my_verify_token&hub.challenge=123456789")
        assert resp.status_code == 200
        assert resp.text == "123456789"

    def test_get_verify_fail(self, client):
        resp = client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong_token&hub.challenge=123456789")
        assert resp.status_code == 403

    def test_post_status_update(self, client, app_config):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1234567890"},
                        "statuses": [{
                            "id": "wamid.status.1",
                            "status": "delivered",
                            "timestamp": "1712345678",
                            "recipient_id": "391234567890",
                        }],
                    },
                }],
            }],
        }
        body = json.dumps(payload).encode()
        sig = _sign_body(body, app_config.app_secret)
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200

    def test_post_invalid_signature(self, client, app_config):
        payload = {"object": "whatsapp_business_account", "entry": []}
        body = json.dumps(payload).encode()
        sig = "sha256=invalid"
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 403

    def test_post_message_inbound(self, client, app_config):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "1234567890"},
                        "contacts": [{"profile": {"name": "Mario"}, "wa_id": "391234567890"}],
                        "messages": [{
                            "from": "391234567890",
                            "id": "wamid.inbound.1",
                            "timestamp": "1712345678",
                            "type": "text",
                            "text": {"body": "Ciao"},
                        }],
                    },
                }],
            }],
        }
        body = json.dumps(payload).encode()
        sig = _sign_body(body, app_config.app_secret)
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200

    def test_post_unknown_phone_number_id_logged(self, client, app_config, mock_repo):
        mock_repo.get_org_by_phone_number_id = AsyncMock(return_value=None)
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "123456789",
                "changes": [{
                    "field": "messages",
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "unknown_pid"},
                        "statuses": [{
                            "id": "wamid.s.1",
                            "status": "delivered",
                            "timestamp": "1712345678",
                        }],
                    },
                }],
            }],
        }
        body = json.dumps(payload).encode()
        sig = _sign_body(body, app_config.app_secret)
        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200  # Meta must not retry
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/whatsapp/test_router.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write implementation**

```python
# src/whatsapp/router.py
import hashlib
import hmac
import json
import logging
from fastapi import APIRouter, Request, Response, HTTPException, Query
from src.whatsapp.config import AppConfig
from src.whatsapp.models import IngoingWebhook

logger = logging.getLogger(__name__)


def create_router(app_config: AppConfig, repo):
    router = APIRouter(prefix="/webhooks", tags=["whatsapp"])

    @router.get("/whatsapp")
    async def verify_webhook(
        hub_mode: str = Query(None, alias="hub.mode"),
        hub_verify_token: str = Query(None, alias="hub.verify_token"),
        hub_challenge: str = Query(None, alias="hub.challenge"),
    ):
        if hub_mode == "subscribe" and hub_verify_token == app_config.verify_token:
            return Response(content=hub_challenge, media_type="text/plain")
        raise HTTPException(status_code=403, detail="Verify token mismatch")

    @router.post("/whatsapp")
    async def receive_webhook(request: Request):
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        if not _verify_hmac(body, signature, app_config.app_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        webhook = IngoingWebhook.model_validate(data)
        for entry in webhook.entry:
            for change in entry.changes:
                value = change.value
                if change.field == "message_template_status_update":
                    await _handle_template_status_update(repo, value, entry_id=entry.id)
                    continue

                pid = None
                if value.metadata and value.metadata.phone_number_id:
                    pid = value.metadata.phone_number_id
                if not pid:
                    continue
                org_data = await repo.get_org_by_phone_number_id(pid)
                if not org_data:
                    logger.warning("Unknown phone_number_id: %s", pid)
                    continue
                org_id = org_data["organization_id"]

                if value.statuses:
                    for status in value.statuses:
                        await _handle_status_update(repo, org_id, status)
                if value.messages:
                    for msg in value.messages:
                        await _handle_inbound_message(repo, org_id, msg, value.contacts)

        return Response(status_code=200)

    return router


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


async def _handle_status_update(repo, org_id, status):
    wam_id = status.id
    new_status = status.status
    biz_data = getattr(status, "biz_opaque_callback_data", None)
    errors = getattr(status, "errors", None)

    # Try to find by wam_id first, then by biz_opaque_callback_data
    if wam_id:
        updated = await repo.update_message_status_by_wam_id(
            wam_id, new_status,
            error_code=str(errors[0]["code"]) if errors else None,
            error_title=errors[0]["title"] if errors else None,
            error_details=errors,
        )
        if updated:
            return

    if biz_data:
        await repo.update_message_status(
            uuid.UUID(biz_data), new_status,
            wam_id=wam_id,
            error_code=str(errors[0]["code"]) if errors else None,
            error_title=errors[0]["title"] if errors else None,
            error_details=errors,
        )


async def _handle_inbound_message(repo, org_id, msg, contacts):
    contact_name = contacts[0].profile.name if contacts and contacts[0].profile else None
    from_number = msg.from_
    contact = await repo.get_or_create_contact(org_id, from_number)
    conv = await repo.get_or_create_conversation(org_id, contact["id"])
    import uuid
    await repo.upsert_message(
        id=uuid.uuid4(),
        organization_id=org_id,
        conversation_id=conv["id"],
        wam_id=msg.id,
        direction="inbound",
        message_type=msg.type,
        content=msg.model_dump(exclude_none=True),
        content_text=msg.text.body if msg.text else None,
        status="received_pending_ai",
    )


async def _handle_template_status_update(repo, value, entry_id=None):
    waba_id = entry_id  # entry[].id is the WhatsApp Business Account ID
    if waba_id:
        org_data = await repo.get_org_by_waba_id(waba_id)
    else:
        org_data = None
    if not org_data:
        logger.warning("Unknown waba_id for template status update: %s", waba_id)
        return
    await repo.update_template_status(
        org_data["organization_id"],
        value.message_template_name,
        value.message_template_language,
        value.message_template_status,
        reason=getattr(value, "reason", None),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_router.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add webhook router with HMAC verification"
```

---

## Task 8: Template Sync

**Files:**
- Create: `src/whatsapp/templates.py`
- Create: `tests/whatsapp/test_templates.py`

**Interfaces:**
- Consumes: `AppConfig`, `Repository`, `MetaClient`
- Produces: `class TemplateSyncer`, `TemplateSyncer.pull_sync()`, `TemplateSyncer.process_push_update()`, `Repository.update_template_status()`, `Repository.upsert_template()`

- [ ] **Step 1: Write the failing test**

```python
# tests/whatsapp/test_templates.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import respx
import httpx
from src.whatsapp.templates import TemplateSyncer
from src.whatsapp.config import AppConfig


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="test",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.get_tenant_config = AsyncMock(return_value={
        "access_token": "encrypted_token",
        "phone_number_id": "12345",
        "waba_id": "waba_1",
        "business_profile": {},
    })
    repo.upsert_template = AsyncMock(return_value={"id": uuid.uuid4()})
    repo.update_template_status = AsyncMock(return_value={"id": uuid.uuid4()})
    return repo


class TestTemplateSyncer:
    @respx.mock
    async def test_pull_sync(self, app_config, mock_repo):
        waba_id = "waba_1"
        url = f"https://graph.facebook.com/v20.0/{waba_id}/message_templates"
        respx.get(url).respond(
            200,
            json={
                "data": [
                    {
                        "id": "123",
                        "name": "promo_welcome",
                        "language": "it",
                        "category": "MARKETING",
                        "status": "APPROVED",
                        "components": [{"type": "BODY", "text": "Ciao {{1}}!"}],
                    }
                ],
            },
        )
        syncer = TemplateSyncer(app_config, mock_repo)
        syncer._get_access_token = AsyncMock(return_value="test_token")
        await syncer.pull_sync("waba_1", "org-uuid")
        mock_repo.upsert_template.assert_called_once()

    async def test_process_push_update(self, app_config, mock_repo):
        syncer = TemplateSyncer(app_config, mock_repo)
        await syncer.process_push_update({
            "message_template_name": "promo_welcome",
            "message_template_language": "it",
            "message_template_status": "REJECTED",
            "reason": "INVALID_FORMAT",
        })
        mock_repo.update_template_status.assert_called_once()
        args = mock_repo.update_template_status.call_args[0]
        assert args[2] == "REJECTED"
        assert args[3] == "INVALID_FORMAT"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/whatsapp/test_templates.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation**

```python
# src/whatsapp/templates.py
import logging
import uuid
import httpx
from src.whatsapp.config import AppConfig

logger = logging.getLogger(__name__)


class TemplateSyncer:
    BASE_URL = "https://graph.facebook.com/v20.0"

    def __init__(self, app_config: AppConfig, repo):
        self.app_config = app_config
        self.repo = repo

    async def pull_sync(self, waba_id: str, org_id: uuid.UUID):
        access_token = await self._get_access_token(org_id)
        url = f"{self.BASE_URL}/{waba_id}/message_templates"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            for tpl in data.get("data", []):
                await self.repo.upsert_template(
                    organization_id=org_id,
                    name=tpl["name"],
                    language=tpl.get("language", "it"),
                    category=tpl.get("category", "MARKETING"),
                    status=tpl.get("status", "PENDING"),
                    components=tpl.get("components", []),
                )

    async def process_push_update(self, event: dict):
        status = event.get("message_template_status", "PENDING")
        await self.repo.update_template_status(
            name=event.get("message_template_name"),
            language=event.get("message_template_language"),
            status=status,
            reason=event.get("reason"),
        )

    async def _get_access_token(self, org_id: uuid.UUID) -> str:
        from src.whatsapp.config import load_tenant_config
        tenant = await load_tenant_config(org_id, self.app_config, self.repo)
        return tenant.access_token
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_templates.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add template sync (pull + push)"
```

---

## Task 9: Workers — Inbound Processor + Retry Worker

**Files:**
- Create: `src/whatsapp/inbound_processor.py`
- Create: `src/whatsapp/retry_worker.py`
- Create: `tests/whatsapp/test_inbound_processor.py`
- Create: `tests/whatsapp/test_retry_worker.py`

**Interfaces:**
- Consumes: `AppConfig`, `Repository`, `WhatsAppService`, `MetaClient`, `TenantConfig`
- Produces: Standalone entry points for workers

- [ ] **Step 1: Write the failing test for inbound_processor**

```python
# tests/whatsapp/test_inbound_processor.py
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from src.whatsapp.inbound_processor import InboundProcessor
from src.whatsapp.config import AppConfig


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test",
        encryption_key="dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTA=",
        postgres_dsn="",
        verify_token="test",
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.claim_inbound_messages = AsyncMock(return_value=[
        {"id": uuid.uuid4(), "organization_id": uuid.uuid4(), "content": {},
         "content_text": "Ciao", "message_type": "text", "from_": "391234567890"}
    ])
    repo.reap_stale_claims = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_service():
    service = AsyncMock()
    service.check_opt_out = AsyncMock(return_value={"is_opt_out": False, "confidence": "low"})
    service.fast_path_match = AsyncMock(return_value=None)
    return service


class TestInboundProcessor:
    async def test_process_one_message(self, app_config, mock_repo, mock_service):
        processor = InboundProcessor(app_config, mock_repo, mock_service)
        await processor.process_next_batch()
        mock_repo.claim_inbound_messages.assert_called_once()

    async def test_reaper_called(self, app_config, mock_repo, mock_service):
        processor = InboundProcessor(app_config, mock_repo, mock_service)
        await processor.process_next_batch()
        mock_repo.reap_stale_claims.assert_called_once()

    async def test_opt_out_skips_fast_path(self, app_config, mock_repo, mock_service):
        mock_service.check_opt_out = AsyncMock(return_value={"is_opt_out": True, "confidence": "high"})
        processor = InboundProcessor(app_config, mock_repo, mock_service)
        await processor.process_next_batch()
        mock_service.fast_path_match.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/whatsapp/test_inbound_processor.py -v`
Expected: FAIL

- [ ] **Step 3: Write implementation for inbound_processor**

```python
# src/whatsapp/inbound_processor.py
import asyncio
import logging
import uuid
from src.whatsapp.config import AppConfig

logger = logging.getLogger(__name__)


class InboundProcessor:
    def __init__(self, app_config: AppConfig, repo, service):
        self.app_config = app_config
        self.repo = repo
        self.service = service

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        messages = await self.repo.claim_inbound_messages(limit=10)
        for msg in messages:
            try:
                await self._process_one(msg)
            except Exception as e:
                logger.error("Error processing message %s: %s", msg["id"], e)

    async def _process_one(self, msg: dict):
        org_id = msg["organization_id"]
        text = msg.get("content_text", "")
        content = msg.get("content", {})

        opt_out = await self.service.check_opt_out(text)
        if opt_out["is_opt_out"]:
            # Record consent event, send ack
            from_number = content.get("from", "")
            contact = await self.repo.get_or_create_contact(org_id, from_number)
            await self.repo.record_consent_event(
                contact_id=contact["id"],
                event_type="opt_out",
                method="keyword_match",
                triggering_message_id=msg["id"],
                matched_text=text,
            )
            await self.repo.update_message_status(msg["id"], "handled")
            return

        fast_reply = await self.service.fast_path_match(text, {})
        if fast_reply:
            # Will send via service.send_whatsapp_message in production
            await self.repo.update_message_status(msg["id"], "handled")
            return

        # Placeholder for AI pipeline (intent + RAG + CrewAI)
        # TODO: integrate with classifier, RAG, responder_agent
        logger.info("Message %s requires AI processing (not yet wired)", msg["id"])
        await self.repo.update_message_status(msg["id"], "handled")
```

- [ ] **Step 4: Write the failing test for retry_worker**

```python
# tests/whatsapp/test_retry_worker.py
import uuid
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timedelta
from src.whatsapp.retry_worker import RetryWorker
from src.whatsapp.config import AppConfig


@pytest.fixture
def app_config():
    return AppConfig(
        app_secret="test",
        encryption_key="key",
        postgres_dsn="",
        verify_token="test",
        max_retry_attempts=5,
    )


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.claim_delivery_attempts = AsyncMock(return_value=[
        {"id": uuid.uuid4(), "message_id": uuid.uuid4(), "attempt_number": 1, "status": "processing"},
        {"id": uuid.uuid4(), "message_id": uuid.uuid4(), "attempt_number": 3, "status": "processing"},
    ])
    repo.reap_stale_claims = AsyncMock(return_value=[])
    repo.reconstruct_payload_for_retry = AsyncMock(return_value={
        "id": uuid.uuid4(),
        "content": {},
    })
    repo.update_message_status = AsyncMock()
    repo.update_delivery_attempt = AsyncMock()
    repo.insert_delivery_attempt = AsyncMock()
    return repo


@pytest.fixture
def mock_service():
    service = AsyncMock()
    service.attempt_delivery = AsyncMock(side_effect=Exception("Meta unavailable"))
    return service


class TestRetryWorker:
    async def test_process_batch(self, app_config, mock_repo, mock_service):
        worker = RetryWorker(app_config, mock_repo, mock_service)
        await worker.process_next_batch()
        mock_repo.claim_delivery_attempts.assert_called_once()

    async def test_reaper_called(self, app_config, mock_repo, mock_service):
        worker = RetryWorker(app_config, mock_repo, mock_service)
        await worker.process_next_batch()
        mock_repo.reap_stale_claims.assert_called_once()

    async def test_failed_attempt_increments(self, app_config, mock_repo, mock_service):
        worker = RetryWorker(app_config, mock_repo, mock_service)
        await worker.process_next_batch()
        assert mock_repo.update_delivery_attempt.call_count == 2

    async def test_attempt_success(self, app_config, mock_repo):
        mock_service = AsyncMock()
        mock_service.attempt_delivery = AsyncMock(return_value={"status": "sent", "wam_id": "wamid.test"})
        worker = RetryWorker(app_config, mock_repo, mock_service)
        await worker.process_next_batch()
        assert mock_repo.update_delivery_attempt.call_count == 2

    async def test_dead_letter_after_max_retries(self, app_config, mock_repo):
        mock_repo.claim_delivery_attempts = AsyncMock(return_value=[
            {"id": uuid.uuid4(), "message_id": uuid.uuid4(),
             "attempt_number": 5, "status": "processing"},
        ])
        mock_service = AsyncMock()
        mock_service.attempt_delivery = AsyncMock(side_effect=Exception("Still failing"))
        worker = RetryWorker(app_config, mock_repo, mock_service)
        await worker.process_next_batch()
        # Should update message to failed
        mock_repo.update_message_status.assert_called_once()
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/whatsapp/test_retry_worker.py -v`
Expected: FAIL

- [ ] **Step 6: Write implementation for retry_worker**

```python
# src/whatsapp/retry_worker.py
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from src.whatsapp.config import AppConfig

logger = logging.getLogger(__name__)

BACKOFF_SCHEDULE = [
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(hours=1),
    timedelta(hours=6),
]


class RetryWorker:
    def __init__(self, app_config: AppConfig, repo, service):
        self.app_config = app_config
        self.repo = repo
        self.service = service
        self.max_retries = app_config.max_retry_attempts

    async def process_next_batch(self):
        await self.repo.reap_stale_claims()
        attempts = await self.repo.claim_delivery_attempts(limit=10)
        for attempt in attempts:
            try:
                await self._process_one(attempt)
            except Exception as e:
                logger.error("Error processing delivery attempt %s: %s", attempt["id"], e)

    async def _process_one(self, attempt: dict):
        message_id = attempt["message_id"]
        payload = await self.repo.reconstruct_payload_for_retry(message_id)
        if not payload:
            await self.repo.update_delivery_attempt(attempt["id"], "failed", {"error": "message not found"})
            return

        org_id = payload["organization_id"]
        tenant = await load_tenant_config(org_id, self.app_config, self.repo)

        attempt_num = attempt["attempt_number"]
        try:
            from src.whatsapp.client import MetaClient
            client = MetaClient(tenant)
            result = await self.service.attempt_delivery(
                message_id=message_id,
                phone_number_id=tenant.phone_number_id,
                access_token=tenant.access_token,
                payload=payload.get("content", {}),
                meta_client=client,
            )
            await self.repo.update_delivery_attempt(attempt["id"], "succeeded")
        except Exception as e:
            logger.warning("Delivery attempt %d failed for %s: %s", attempt_num, message_id, e)
            if attempt_num >= self.max_retries:
                await self.repo.update_delivery_attempt(attempt["id"], "failed", {"error": str(e)})
                await self.repo.update_message_status(message_id, "failed", error_code="max_retries", error_title=str(e))
            else:
                next_retry = datetime.now(timezone.utc) + BACKOFF_SCHEDULE[min(attempt_num, len(BACKOFF_SCHEDULE) - 1)]
                await self.repo.update_delivery_attempt(attempt["id"], "pending", {"error": str(e)})
                await self.repo.insert_delivery_attempt(message_id, next_retry)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/whatsapp/test_inbound_processor.py tests/whatsapp/test_retry_worker.py -v`
Expected: PASS (7 tests)

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): add inbound processor and retry worker"
```

---

## Task 10: Wiring — Mount Router in main.py

**Files:**
- Modify: `src/api/main.py` (add startup/shutdown events, mount whatsapp router, register scheduler)


**Interfaces:**
- Consumes: all previous tasks
- Produces: fully integrated FastAPI app

- [ ] **Step 1: Write a test for main.py integration**

```python
# tests/whatsapp/test_main_integration.py
from fastapi.testclient import TestClient
from src.api.main import app

def test_health_check():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
```

- [ ] **Step 2: Update main.py**

In `src/api/main.py`:

```python
# Add imports at top
from src.whatsapp.router import create_router
from src.whatsapp.config import AppConfig

# Near the existing startup code, add:
@app.on_event("startup")
async def startup_whatsapp():
    # Load AppConfig from env
    import os
    app_config = AppConfig(
        app_secret=os.getenv("META_APP_SECRET", ""),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        postgres_dsn=os.getenv("POSTGRES_DSN", ""),
        verify_token=os.getenv("META_VERIFY_TOKEN", ""),
    )
    # Create asyncpg pool
    import asyncpg
    pool = await asyncpg.create_pool(dsn=app_config.postgres_dsn, min_size=2, max_size=10)
    app.state.pg_pool = pool
    app.state.whatsapp_config = app_config
    # Create repository, service, router
    from src.whatsapp.repository import Repository
    from src.whatsapp.service import WhatsAppService
    repo = Repository(pool)
    service = WhatsAppService(app_config, repo)
    router = create_router(app_config, repo)
    app.include_router(router)
    app.state.whatsapp_repo = repo
    app.state.whatsapp_service = service

@app.on_event("shutdown")
async def shutdown_whatsapp():
    if hasattr(app.state, "pg_pool"):
        await app.state.pg_pool.close()
```

- [ ] **Step 3: Run tests to verify integration**

Run: `pytest tests/whatsapp/test_main_integration.py -v`
Expected: PASS

- [ ] **Step 4: Add worker entry points**

Create `run_inbound_processor.py` at project root:
```python
#!/usr/bin/env python3
import asyncio
import os
import asyncpg
from src.whatsapp.config import AppConfig
from src.whatsapp.repository import Repository
from src.whatsapp.service import WhatsAppService
from src.whatsapp.inbound_processor import InboundProcessor


async def main():
    app_config = AppConfig(
        app_secret=os.getenv("META_APP_SECRET", ""),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        postgres_dsn=os.getenv("POSTGRES_DSN", ""),
        verify_token=os.getenv("META_VERIFY_TOKEN", ""),
    )
    pool = await asyncpg.create_pool(dsn=app_config.postgres_dsn)
    repo = Repository(pool)
    service = WhatsAppService(app_config, repo)
    processor = InboundProcessor(app_config, repo, service)
    while True:
        await processor.process_next_batch()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
```

Create `run_retry_worker.py` at project root:
```python
#!/usr/bin/env python3
import asyncio
import os
import asyncpg
from src.whatsapp.config import AppConfig
from src.whatsapp.repository import Repository
from src.whatsapp.service import WhatsAppService
from src.whatsapp.retry_worker import RetryWorker


async def main():
    app_config = AppConfig(
        app_secret=os.getenv("META_APP_SECRET", ""),
        encryption_key=os.getenv("ENCRYPTION_KEY", ""),
        postgres_dsn=os.getenv("POSTGRES_DSN", ""),
        verify_token=os.getenv("META_VERIFY_TOKEN", ""),
        max_retry_attempts=5,
    )
    pool = await asyncpg.create_pool(dsn=app_config.postgres_dsn)
    repo = Repository(pool)
    service = WhatsAppService(app_config, repo)
    worker = RetryWorker(app_config, repo, service)
    while True:
        await worker.process_next_batch()
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(whatsapp): wire router into main.py, add worker entry points"
```
