# Security & GDPR Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remediate security vulnerabilities and implement GDPR compliance (retention, encryption, PII redaction, data rights API).

**Architecture:** 8 tasks — .gitignore fix, token encryption (WhatsApp + Gmail), PII strict whitelist, data retention with math-correct soft→purge, GDPR data rights API with external propagation, consent tracking, audit.log separate file, DPA template. Each module independently testable.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, cryptography (Fernet), pytest, httpx (for outbound webhooks)

## Global Constraints

- ENCRYPTION_KEY must be a valid Fernet key (44 base64 chars). Fail hard if unset — no empty string fallback.
- All repository read queries must filter `WHERE deleted_at IS NULL` for soft-deleted records.
- GDPR data export is JSON via pre-signed/protected URL, owner-only, audit-logged, 15-min expiry.
- GDPR hard-delete propagates to Airtable + Softr via webhook/API calls.
- CORS already dynamic from CORS_ORIGINS env var — no wildcard, no change needed in code.
- Migration files go to `src/core/db/migrations/004_gdpr.sql`.
- FERNET KEY ROTATION: any `cryptography.fernet.InvalidToken` must be caught with graceful fallback (log + alert, not crash).

---

### Task 1: .gitignore fix + git rm --cached + email_config.json -> env

**Files:**
- Modify: `.gitignore`
- Modify: `.env.example`
- Delete: `data/email_config.json` (content migrated to env)
- Other: `git rm --cached` for sensitive files

**Interfaces:**
- Consumes: nothing
- Produces: clean git tracking, new .gitignore, updated .env.example

- [ ] **Step 1: Update .gitignore**

Append to `.gitignore`:
```
# Secrets & credentials
data/*.json
data/gmail_tokens/
*.token
credentials.json
service-account*.json
*.pem
*.key
.env.local
.env.production

# OS
Thumbs.db
.DS_Store
```

- [ ] **Step 2: git rm --cached sensitive files**

```bash
git rm --cached data/client_secret.json data/gmail_oauth_session.json data/email_config.json data/gmail_tokens/faischifo287_at_gmail_dot_com.token
```

- [ ] **Step 3: Update .env.example**

```
ENCRYPTION_KEY=
# Generate a Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

CORS_ORIGINS=http://localhost:5173,http://localhost:3000,https://tua-dashboard.softr.app

# External services for GDPR hard-delete propagation
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=
SOFTR_API_KEY=
SOFTR_WEBHOOK_URL=
```

- [ ] **Step 4: Read email_config.json content, print env vars to add, remove file**

```bash
cat data/email_config.json
```

- [ ] **Step 5: Verify + commit**

```bash
git status
git add .gitignore .env.example
git commit -m "fix(security): update .gitignore, rm cached secrets, add env vars for GDPR propagation"
```

---

### Task 2: Token encryption — WhatsApp access_token encrypt-on-save

**Files:**
- Modify: `src/whatsapp/repository.py` — add `_encrypt_token()` helper, apply to all access_token writes
- Modify: `src/core/db/repository.py` — encrypt in `save_tenant_config`
- Test: `tests/whatsapp/test_repository.py` — existing + new encryption tests
- Modify: `src/whatsapp/config.py` — add InvalidToken handling in `load_tenant_config`

**Interfaces:**
- Consumes: `ENCRYPTION_KEY` from env
- Produces: encrypted `access_token` stored in DB

- [ ] **Step 1: Write failing tests**

Add to `tests/whatsapp/test_repository.py`:

```python
async def test_access_token_encrypted_at_rest(repo):
    from cryptography.fernet import Fernet
    key = os.environ["ENCRYPTION_KEY"]
    cipher = Fernet(key.encode())
    raw = "EAAxTestToken123"
    org_id = await repo.create_organization("Test")
    await repo.save_tenant_config(org_id, "12345", "waba_1", raw)
    row = await repo.get_tenant_config(org_id)
    assert row["access_token"] != raw
    decrypted = cipher.decrypt(row["access_token"].encode()).decode()
    assert decrypted == raw

async def test_encryption_key_rotation_still_decrypts_old(repo):
    """Simulate key rotation: old key decrypts, new key crashes gracefully"""
    from cryptography.fernet import Fernet, InvalidToken
    old_key = os.environ["ENCRYPTION_KEY"]
    new_key = Fernet.generate_key().decode()
    raw = "EAAxOldKeyToken"
    org_id = await repo.create_organization("Test2")
    await repo.save_tenant_config(org_id, "12345", "waba_2", raw)
    row = await repo.get_tenant_config(org_id)
    # Decrypt with old key works
    cipher_old = Fernet(old_key.encode())
    assert cipher_old.decrypt(row["access_token"].encode()).decode() == raw
    # Decrypt with new key fails gracefully (simulates rotation)
    with pytest.raises(InvalidToken):
        Fernet(new_key.encode()).decrypt(row["access_token"].encode())
```

- [ ] **Step 2: Add InvalidToken handling in config.py**

```python
async def load_tenant_config(org_id: UUID, app_config: AppConfig, repo) -> TenantConfig:
    from cryptography.fernet import Fernet, InvalidToken
    row = await repo.get_tenant_config(org_id)
    try:
        cipher = Fernet(app_config.encryption_key.encode())
        decrypted = cipher.decrypt(row["access_token"].encode()).decode()
    except InvalidToken:
        logger.error("INVALID_TOKEN: encryption key may have been rotated. org_id=%s", org_id)
        raise
    ...
```

- [ ] **Step 3: Implement `_encrypt_token` in repository.py**

```python
import os
from cryptography.fernet import Fernet

def _encrypt_token(plaintext: str) -> str:
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not set")
    return Fernet(key.encode()).encrypt(plaintext.encode()).decode()
```

Apply `_encrypt_token(access_token)` before all INSERT/UPDATE of `access_token`.

- [ ] **Step 4: Run tests**

```bash
pytest tests/whatsapp/test_repository.py::test_access_token_encrypted_at_rest tests/whatsapp/test_repository.py::test_encryption_key_rotation_still_decrypts_old -v
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(security): encrypt WhatsApp access_token at rest with Fernet + InvalidToken guard for rotation"
```

---

### Task 3: Token encryption — Gmail token pickle -> Fernet

**Files:**
- Modify: `src/core/gmail_token_store.py`

**Interfaces:**
- Consumes: `ENCRYPTION_KEY` from env
- Produces: encrypted Gmail tokens on disk

- [ ] **Step 1: Write failing test**

```python
async def test_gmail_token_encrypted_at_rest():
    from src.core.gmail_token_store import save_credentials, load_credentials
    from cryptography.fernet import Fernet
    import os, tempfile, pickle

    key = os.environ["ENCRYPTION_KEY"]
    cipher = Fernet(key.encode())

    email = "test@example.com"
    creds = MagicMock()
    creds.token = "ya29.test_token"
    creds.refresh_token = "1//test_refresh"

    save_credentials(email, creds)
    token_path = f"data/gmail_tokens/test_at_example_dot_com.token"
    with open(token_path, "rb") as f:
        raw = f.read()
    with pytest.raises(Exception):
        pickle.loads(raw)
    decrypted = cipher.decrypt(raw)
    assert b"ya29.test_token" in decrypted
```

- [ ] **Step 2: Rewrite save/load/delete with Fernet + InvalidToken fallback**

```python
from cryptography.fernet import Fernet, InvalidToken

def _get_cipher():
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY not set")
    return Fernet(key.encode())

def save_credentials(email: str, creds):
    os.makedirs(_TOKENS_DIR, exist_ok=True)
    cipher = _get_cipher()
    encrypted = cipher.encrypt(pickle.dumps(creds))
    with open(_token_path(email), "wb") as f:
        f.write(encrypted)

def load_credentials(email: str) -> Optional[Credentials]:
    path = _token_path(email)
    if not os.path.exists(path):
        return None
    try:
        cipher = _get_cipher()
        with open(path, "rb") as f:
            encrypted = f.read()
        creds = pickle.loads(cipher.decrypt(encrypted))
    except InvalidToken:
        logger.error("GMAIL_INVALID_TOKEN: cannot decrypt token for %s. Key may have been rotated.", email)
        return None
    ...
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/core/test_gmail_token_store.py -v
```

- [ ] **Step 4: Re-encrypt existing tokens**

```python
# One-time migration: re-encrypt existing unencrypted pickle tokens
import os, pickle
from cryptography.fernet import Fernet
key = os.environ["ENCRYPTION_KEY"]
cipher = Fernet(key.encode())
for fname in os.listdir("data/gmail_tokens"):
    path = os.path.join("data/gmail_tokens", fname)
    with open(path, "rb") as f:
        data = f.read()
    try:
        pickle.loads(data)
    except:
        continue  # already encrypted
    encrypted = cipher.encrypt(data)
    with open(path, "wb") as f:
        f.write(encrypted)
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(security): encrypt Gmail OAuth tokens at rest with Fernet + InvalidToken fallback"
```

---

### Task 4: PII Redaction — Strict Whitelist (no regex on free text)

**Files:**
- Create: `src/core/logging_filter.py`
- Test: `tests/core/test_logging_filter.py`

**Interfaces:**
- Consumes: nothing
- Produces: `PIIWhitelistFilter(logging.Filter)` applied to root logger in `main.py`

Design change from original plan: NO regex on free-text message bodies or phone numbers. Instead, a strict whitelist approach:
- Loggers throughout the app accept ONLY structured dicts with explicit safe keys
- Any log message containing free-form text fields is automatically blocked unless the key is in the SAFE_KEYS whitelist
- Message body and phone numbers are NEVER passed to logging — if they are, the filter DROPS the record entirely (doesn't just mask)

- [ ] **Step 1: Write failing tests**

```python
def test_whitelist_blocks_message_text():
    from src.core.logging_filter import PIIWhitelistFilter
    import logging
    logger = logging.getLogger("test_whitelist")
    f = PIIWhitelistFilter()
    logger.addFilter(f)
    logger.setLevel(logging.INFO)

    with mock.patch.object(logger, "handle") as mock_handle:
        logger.info("Ciao Mario, il tuo tavolo e' pronto alle 20:00")  # free text with PII
        mock_handle.assert_not_called()

def test_whitelist_allows_safe_metadata():
    from src.core.logging_filter import PIIWhitelistFilter
    import logging
    logger = logging.getLogger("test_whitelist2")
    f = PIIWhitelistFilter()
    logger.addFilter(f)
    logger.setLevel(logging.INFO)

    with mock.patch.object(logger, "handle") as mock_handle:
        logger.info("msg_id=%s org_id=%s status=%s", "msg_123", "org_456", "delivered")
        mock_handle.assert_called_once()

def test_whitelist_blocks_phone_number():
    from src.core.logging_filter import PIIWhitelistFilter
    import logging
    logger = logging.getLogger("test_whitelist3")
    f = PIIWhitelistFilter()
    logger.addFilter(f)
    logger.setLevel(logging.INFO)

    with mock.patch.object(logger, "handle") as mock_handle:
        logger.info("from=%s", "+393401234567")
        mock_handle.assert_not_called()
```

- [ ] **Step 2: Implement PIIWhitelistFilter**

```python
import logging
import re
from typing import Set

# Only these key names are allowed in log messages
SAFE_KEYS: Set[str] = {
    "msg_id", "message_id", "org_id", "organization_id",
    "tenant_id", "timestamp", "event_type", "status",
    "attempt_num", "error_type", "duration_ms", "http_status",
    "phone_number_id", "waba_id", "plan", "action",
}

# Pattern to extract key names from log messages like "key=value key2=value2"
_KEY_PATTERN = re.compile(r'(\w[\w_]*)\s*=')

class PIIWhitelistFilter(logging.Filter):
    """Strict whitelist: drop any log record containing values not in SAFE_KEYS."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        # Extract all key names from structured key=value pairs
        keys_found = _KEY_PATTERN.findall(msg)
        if not keys_found:
            # Unstructured log message with no key=value format — BLOCK
            return False
        for key in keys_found:
            if key not in SAFE_KEYS:
                return False
        return True
```

- [ ] **Step 3: Apply filter to root logger in main.py**

```python
from src.core.logging_filter import PIIWhitelistFilter
logging.getLogger().addFilter(PIIWhitelistFilter())
```

- [ ] **Step 4: Audit all existing logger calls to use structured key=value format**

Check all `logger.info/warning/error` calls across src/ to ensure they use `key=value` format with SAFE_KEYS. Fix any that don't.

- [ ] **Step 5: Run tests**

```bash
pytest tests/core/test_logging_filter.py -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(security): strict PII whitelist filter — drops any log record with non-whitelisted keys"
```

---

### Task 5: Data retention — correct math + async cleanup job

**Files:**
- Create: `src/core/db/migrations/004_gdpr.sql`
- Modify: `src/core/db/repository.py` — add soft-delete methods + `deleted_at` filter on reads
- Create: `src/core/retention_job.py` — async periodic job for retention enforcement
- Modify: `tests/core/conftest.py` — load 004_gdpr.sql
- Test: `tests/core/test_retention_job.py`

**Retention math (corrected):**
- Day 0: message created
- Day 60: soft-delete (set `deleted_at = NOW()`) — message invisible to app
- Day 90: physical DELETE (30 days after soft-delete) — data gone forever
- Total data lifespan: 90 days. NOT 120.

No trigger-based cascade on conversations. Async job runs periodic cleanup: after soft-deleting all messages in a conversation, job checks if conversation has no remaining active messages → soft-delete conversation.

- [ ] **Step 1: Write migration SQL**

```sql
-- 004_gdpr.sql
ALTER TABLE messages ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS message_retention_days INTEGER DEFAULT 90;
```

- [ ] **Step 2: Write failing tests**

```python
async def test_soft_deleted_messages_excluded_from_queries(repo):
    org_id = await repo.create_organization("Test")
    msg = await repo.upsert_message(org_id, ...)
    await repo.soft_delete_message(msg["id"])
    msgs = await repo.get_messages(org_id)
    assert msg["id"] not in [m["id"] for m in msgs]

async def test_retention_job_soft_deletes_expired_messages(repo):
    """Messages older than retention_days get soft-deleted."""
    org_id = await repo.create_organization("Test")
    old_msg = await repo.upsert_message(org_id, created_at=days_ago(61))
    await run_retention_cycle(repo)
    row = await repo.get_message_by_id(old_msg["id"])
    assert row["deleted_at"] is not None

async def test_retention_job_purges_after_grace_period(repo):
    """Messages soft-deleted 30+ days ago get physically deleted."""
    org_id = await repo.create_organization("Test")
    msg = await repo.upsert_message(org_id, created_at=days_ago(91))
    await repo.soft_delete_message(msg["id"], deleted_at=days_ago(31))
    await run_retention_cycle(repo)
    row = await repo.get_message_by_id(msg["id"])
    assert row is None  # physically gone
```

- [ ] **Step 3: Add soft-delete + retention repository methods**

```python
async def soft_delete_message(self, message_id: UUID, deleted_at: datetime = None):
    if deleted_at is None:
        deleted_at = datetime.now(timezone.utc)
    await self.conn.execute("UPDATE messages SET deleted_at = $1 WHERE id = $2", deleted_at, message_id)

async def soft_delete_conversation(self, conversation_id: UUID):
    await self.conn.execute("UPDATE conversations SET deleted_at = NOW() WHERE id = $1", conversation_id)

async def delete_expired_messages(self, retention_days: int):
    """Soft-delete messages older than retention_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    await self.conn.execute("""
        UPDATE messages SET deleted_at = NOW()
        WHERE created_at < $1 AND deleted_at IS NULL
    """, cutoff)

async def purge_soft_deleted_messages(self, grace_days: int = 30):
    """Physically delete messages soft-deleted more than grace_days ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)
    await self.conn.execute("DELETE FROM messages WHERE deleted_at < $1", cutoff)

async def cleanup_empty_conversations(self):
    """Soft-delete conversations with no active (non-deleted) messages."""
    await self.conn.execute("""
        UPDATE conversations SET deleted_at = NOW()
        WHERE deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM messages
            WHERE messages.conversation_id = conversations.id
            AND messages.deleted_at IS NULL
        )
    """)
```

- [ ] **Step 4: Add `WHERE deleted_at IS NULL` to all message/conversation/contact read queries**

- [ ] **Step 5: Create retention_job.py**

```python
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class RetentionJob:
    def __init__(self, repo, interval_hours: int = 24):
        self.repo = repo
        self.interval = interval_hours * 3600

    async def run_once(self):
        logger.info("retention_job=started")
        try:
            await self.repo.delete_expired_messages()
            await self.repo.purge_soft_deleted_messages()
            await self.repo.cleanup_empty_conversations()
            logger.info("retention_job=completed")
        except Exception as e:
            logger.error("retention_job=error error_type=%s", type(e).__name__)

    async def run_forever(self):
        while True:
            await self.run_once()
            await asyncio.sleep(self.interval)
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/core/test_retention_job.py -v
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(gdpr): data retention with math-correct soft-delete day 60 + purge day 90"
```

---

### Task 6: Consent tracking per contact + separate audit.log

**Files:**
- Modify: `src/core/db/migrations/004_gdpr.sql` — add consent columns
- Modify: `src/core/db/repository.py` — add consent methods
- Create: `src/core/audit_logger.py` — separate file logger for security events
- Test: `tests/core/test_audit_logger.py`

- [ ] **Step 1: Add consent columns to migration**

```sql
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS consent_opt_in_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS consent_opt_out_at TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS consent_legal_basis TEXT DEFAULT 'legitimate_interest';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS consent_marketing BOOLEAN DEFAULT false;
```

- [ ] **Step 2: Write failing tests**

```python
async def test_consent_tracking_on_opt_out(repo):
    contact_id = await repo.get_or_create_contact(org_id, "393401234567")
    await repo.record_consent_event(contact_id, opt_out=True)
    prefs = await repo.get_contact_prefs(contact_id)
    assert prefs["consent_opt_out_at"] is not None
    assert prefs["consent_marketing"] is False

async def test_audit_log_writes_separate_file(tmp_path):
    from src.core.audit_logger import SecurityAuditLogger
    log_path = tmp_path / "audit.log"
    logger = SecurityAuditLogger(str(log_path))
    logger.log_unauthorized_access(org_id="org_1", user_id="user_1", endpoint="/api/admin")
    content = log_path.read_text()
    assert "UNAUTHORIZED_ACCESS" in content
    assert "org_1" in content
```

- [ ] **Step 3: Implement repository consent methods**

```python
async def record_consent_event(self, contact_id: UUID, opt_out: bool = False, marketing: bool = False):
    if opt_out:
        await self.conn.execute("""
            UPDATE contacts SET
                consent_opt_out_at = NOW(),
                consent_marketing = false
            WHERE id = $1
        """, contact_id)
    else:
        await self.conn.execute("""
            UPDATE contacts SET
                consent_opt_in_at = NOW(),
                consent_opt_out_at = NULL,
                consent_marketing = $2
            WHERE id = $1
        """, contact_id, marketing)
```

- [ ] **Step 4: Implement SecurityAuditLogger**

```python
import logging
import json
from datetime import datetime, timezone

class SecurityAuditLogger:
    """Separate file logger for security-critical events.
    Writes to logs/audit.log with JSON structure for easy parsing."""

    def __init__(self, path: str = "logs/audit.log"):
        self.logger = logging.getLogger("security_audit")
        handler = logging.FileHandler(path)
        handler.setFormatter(logging.Formatter('%(message)s'))
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False  # Don't duplicate to root logger

    def _log(self, event_type: str, **fields):
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            **fields,
        }
        self.logger.info(json.dumps(record))

    def log_unauthorized_access(self, org_id: str, user_id: str, endpoint: str, reason: str = ""):
        self._log("UNAUTHORIZED_ACCESS", org_id=org_id, user_id=user_id, endpoint=endpoint, reason=reason)

    def log_crypto_failure(self, org_id: str, context: str, error: str):
        self._log("CRYPTO_FAILURE", org_id=org_id, context=context, error=error)

    def log_suspicious_export(self, org_id: str, user_id: str, export_type: str):
        self._log("SUSPICIOUS_EXPORT", org_id=org_id, user_id=user_id, export_type=export_type)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/core/test_audit_logger.py -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(gdpr): add consent tracking per contact + separate security audit.log"
```

---

### Task 7: GDPR Data Rights API — export, hard-delete with propagation, protected links

**Files:**
- Create: `src/core/gdpr/routes.py` — export + delete endpoints
- Create: `src/core/gdpr/propagation.py` — webhook calls to Airtable + Softr
- Create: `tests/core/gdpr/test_routes.py`
- Create: `tests/core/gdpr/test_propagation.py`
- Modify: `src/api/main.py` — include gdpr router

**Interfaces:**
- Consumes: `repo` from app.state, `require_ruolo("owner")` from auth
- Produces: `GET /api/gdpr/export` — pre-signed JSON download, 15-min expiry
- Produces: `POST /api/gdpr/delete` — hard-delete + propagation to Airtable + Softr

- [ ] **Step 1: Write failing tests**

```python
async def test_gdpr_export_returns_pre_signed_url(client, owner_headers):
    resp = await client.get("/api/gdpr/export", headers=owner_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "download_url" in data
    assert "expires_in_minutes" in data
    assert data["expires_in_minutes"] == 15

async def test_gdpr_delete_propagates_to_external_services(repo, respx_mock):
    # Mock Airtable + Softr endpoints
    airtable_route = respx.delete("https://api.airtable.com/org_123").respond(200)
    softr_route = respx.post("https://hooks.softr.app/delete").respond(200)
    # Set env vars for propagation URLs
    import os
    os.environ["AIRTABLE_BASE_ID"] = "test_base"
    os.environ["SOFTR_WEBHOOK_URL"] = "https://hooks.softr.app/delete"
    await gdpr_hard_delete(repo, org_id="org_123", auth_user_id="user_1")
    assert airtable_route.called
    assert softr_route.called

async def test_gdpr_delete_audit_logged(repo, audit_logger):
    await gdpr_hard_delete(repo, org_id="org_123", auth_user_id="user_1")
    # Verify audit.log has the event
    ...

async def test_gdpr_export_fails_without_auth(client):
    resp = await client.get("/api/gdpr/export")
    assert resp.status_code == 401
```

- [ ] **Step 2: Implement propagation.py**

```python
import os
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

async def propagate_delete_to_airtable(org_id: str) -> bool:
    """Notify Airtable to delete records for this organization."""
    api_key = os.getenv("AIRTABLE_API_KEY")
    base_id = os.getenv("AIRTABLE_BASE_ID")
    if not api_key or not base_id:
        logger.warning("propagation=airtable skipped reason=missing_config org_id=%s", org_id)
        return False
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"https://api.airtable.com/v0/{base_id}/organizations/{org_id}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        logger.info("propagation=airtable org_id=%s status=%d", org_id, resp.status_code)
        return resp.is_success

async def propagate_delete_to_softr(org_id: str) -> bool:
    """Notify Softr webhook to delete synced records."""
    webhook_url = os.getenv("SOFTR_WEBHOOK_URL")
    api_key = os.getenv("SOFTR_API_KEY")
    if not webhook_url:
        logger.warning("propagation=softr skipped reason=missing_config org_id=%s", org_id)
        return False
    async with httpx.AsyncClient() as client:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = await client.post(webhook_url, json={"organization_id": org_id, "action": "delete"}, headers=headers)
        logger.info("propagation=softr org_id=%s status=%d", org_id, resp.status_code)
        return resp.is_success

async def propagate_hard_delete(org_id: str):
    """Propagate hard-delete to all external services."""
    results = {
        "airtable": await propagate_delete_to_airtable(org_id),
        "softr": await propagate_delete_to_softr(org_id),
    }
    logger.info("propagation=complete org_id=%s results=%s", org_id, results)
    return results
```

- [ ] **Step 3: Implement export with pre-signed/protected URL**

Generate a short-lived token (JWT or UUID stored in redis/memory with TTL 15min). Return URL containing that token. Token verified on download endpoint.

```python
import secrets
from datetime import datetime, timedelta, timezone

# In-memory store for export tokens (use Redis in production)
_export_tokens: dict[str, dict] = {}

def _generate_export_token(org_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    _export_tokens[token] = {"org_id": org_id, "expires": expires}
    return token, expires

@router.get("/export")
async def gdpr_export(request: Request, user: dict = Depends(require_ruolo("owner"))):
    repo = request.app.state.repo
    org_id = user["organization_id"]
    # Generate export data
    data = await export_tenant_data(repo, org_id)
    # Store in memory with short-lived token
    token, expires = _generate_export_token(org_id)
    _export_tokens[token]["data"] = data
    download_url = str(request.base_url) + f"api/gdpr/download/{token}"
    return {"download_url": download_url, "expires_in_minutes": 15}

@router.get("/download/{token}")
async def gdpr_download(token: str, request: Request):
    if token not in _export_tokens:
        raise HTTPException(404, "Export token not found or expired")
    meta = _export_tokens[token]
    if datetime.now(timezone.utc) > meta["expires"]:
        del _export_tokens[token]
        raise HTTPException(410, "Export token expired")
    data = meta["data"]
    del _export_tokens[token]  # one-time download
    return JSONResponse(content=data)
```

- [ ] **Step 4: Implement hard-delete with propagation**

```python
@router.post("/delete")
async def gdpr_delete(request: Request, user: dict = Depends(require_ruolo("owner"))):
    repo = request.app.state.repo
    org_id = user["organization_id"]

    # Propagate to external services FIRST
    propagation_results = await propagate_hard_delete(org_id)

    # THEN delete local data (ON DELETE CASCADE)
    await repo.delete_organization(org_id)

    # Audit log
    await audit_log(repo, organization_id=org_id, action="gdpr.hard_delete",
                    auth_user_id=user.get("auth_user_id"))

    return {
        "status": "deleted",
        "propagation": propagation_results,
        "message": "All data permanently removed. External services notified."
    }
```

- [ ] **Step 5: Register router in main.py**

```python
from src.core.gdpr.routes import router as gdpr_router
app.include_router(gdpr_router)
```

- [ ] **Step 6: Register SecurityAuditLogger in app lifespan**

```python
from src.core.audit_logger import SecurityAuditLogger
audit_logger = SecurityAuditLogger()
request.app.state.audit_logger = audit_logger
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/core/gdpr/ -v
```

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(gdpr): data export with 15-min pre-signed URL + hard-delete propagation to Airtable/Softr"
```

---

### Task 8: DPA Template with geo-location

**Files:**
- Create: `docs/superpowers/dpa/data-processing-agreement.md`

- [ ] **Step 1: Write DPA template**

Sections:
- Parties (Controller + Processor)
- Scope & Purpose
- Categories of Data Processed
- Sub-processors table with exact geo-location:
  - **Meta (WhatsApp Cloud API)**: USA (Oregon, Virginia), Ireland (Dublin)
  - **Stripe**: USA (multiple regions), Ireland (Dublin) for EU data
  - **OpenRouter/LLM providers**: USA (Oregon, Iowa), EU (Frankfurt, Stockholm)
  - **Neon (Postgres hosting)**: USA (Ohio, Oregon), EU (Frankfurt)
  - **Google (Gmail API)**: USA, EU (Belgium, Netherlands)
- Data Retention: 90 days max, configurable per tenant
- Security Measures: encryption at rest (Fernet AES-128), PII redaction, access control
- Data Subject Rights: export + deletion API endpoints
- DPO Contact placeholder

- [ ] **Step 2: Commit**

```bash
git add -A
git commit -m "docs(gdpr): add Data Processing Agreement template with sub-processor geo-location"
```
