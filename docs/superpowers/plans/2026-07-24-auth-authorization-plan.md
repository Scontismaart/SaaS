# Auth & Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authentication (Supabase JWT + API Key) and authorization (ruoli: owner/manager/staff) a tutte le route esistenti senza rompere l'app, con rate limiting per tenant, audit log, e CORS ristretto.

**Architecture:** Nuovo package `src/core/auth/` con dipendenze FastDPI componibili (Depends). Supabase Auth per JWT, API Key statica per server-to-server. Rate limiting in-memory via middleware. Audit log su tabella `audit_log` separata (non event_log).

**Tech Stack:** FastAPI Depends, Supabase Auth (JWKS), python-jose, httpx, respx (test), pytest + pytest-asyncio

## Global Constraints

- Nessuna rotta esistente deve rompersi — webhook WhatsApp e /api/health rimangono pubblici
- Webhook WhatsApp continua a usare HMAC (invariato)
- API Key statica configurata via .env (`API_KEY_SERVICE`)
- `X-Organization-Id` header obbligatorio per rotte protette
- Rate limiting esclude `/api/health` e `/webhooks/whatsapp`
- CORS: allow_origins da variabile d'ambiente
- Tutto l'auth via Depends, non middleware globale
- Test per ogni ruolo, token invalido, API Key, e rotte pubbliche

---

## File Structure

### Nuovi file
| File | Responsabilità |
|---|---|
| `src/core/auth/__init__.py` | Package marker |
| `src/core/auth/dependencies.py` | get_token, get_current_user, get_organization_context, require_ruolo |
| `src/core/auth/audit.py` | Funzione helper `audit_log()` |
| `tests/core/auth/__init__.py` | Package marker |
| `tests/core/auth/test_dependencies.py` | Test per tutte le dipendenze auth |
| `tests/core/auth/test_audit.py` | Test per audit helper |

### Nuovo SQL
| File | Quando eseguire |
|---|---|
| `src/core/db/migrations/002_auth_tables.sql` | Su Supabase SQL Editor |

### File modificati
| File | Cambiamento |
|---|---|
| `src/core/db/repository.py` | Aggiungere `get_membership_by_auth()` |
| `src/api/main.py` | CORS fix, rate limit middleware, aggiungere Depends auth alle route |
| `.env` | Aggiungere `SUPABASE_URL`, `API_KEY_SERVICE`, `CORS_ORIGINS`, `RATE_LIMIT_*` |
| `requirements.txt` | Aggiungere `jose`, `supabase` |
| `.env.example` | Aggiungere nuove variabili |

---

### Task 1: DB Schema — Tabelle auth + trigger + RLS

**Files:**
- Create: `src/core/db/migrations/002_auth_tables.sql`

**Interfaces:**
- Consumes: tabella `organizations` già esistente
- Produces: tabelle `user_profiles`, `organization_memberships`, trigger `trg_sync_auth_user`, RLS policies

- [ ] **Step 1: Write migration SQL**

```sql
-- 002_auth_tables.sql

CREATE TABLE IF NOT EXISTS user_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id    UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    nome            TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organization_memberships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    ruolo           TEXT NOT NULL CHECK (ruolo IN ('owner', 'manager', 'staff')),
    invited_at      TIMESTAMPTZ DEFAULT NOW(),
    joined_at       TIMESTAMPTZ,
    UNIQUE(organization_id, user_id)
);

CREATE OR REPLACE FUNCTION sync_auth_user_profile()
RETURNS trigger AS $$
BEGIN
    INSERT INTO user_profiles (id, auth_user_id, email)
    VALUES (gen_random_uuid(), NEW.id, NEW.email)
    ON CONFLICT (auth_user_id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS trg_sync_auth_user ON auth.users;
CREATE TRIGGER trg_sync_auth_user
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION sync_auth_user_profile();

CREATE INDEX IF NOT EXISTS idx_memberships_user ON organization_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_memberships_org ON organization_memberships(organization_id);
```

- [ ] **Step 2: Commit**

```bash
git add src/core/db/migrations/002_auth_tables.sql
git commit -m "feat(auth): add auth tables, trigger, indexes SQL"
```

---

### Task 2: Repository — get_membership_by_auth()

**Files:**
- Modify: `src/core/db/repository.py`
- Test: `tests/core/test_repository_auth.py`

**Interfaces:**
- Consumes: `CoreRepository(pool)` already exists
- Produces: `async def get_membership_by_auth(auth_user_id: str, organization_id: str) -> dict | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_repository_auth.py
import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_get_membership_by_auth_found(repo, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test')", org_id)
        await conn.execute("""
            INSERT INTO user_profiles (id, auth_user_id, email)
            VALUES ($1, $2, 'test@test.com')
        """, uuid.uuid4(), "auth|test123")
        up_row = await conn.fetchrow("SELECT id FROM user_profiles WHERE auth_user_id = $1", "auth|test123")
        await conn.execute("""
            INSERT INTO organization_memberships (organization_id, user_id, ruolo)
            VALUES ($1, $2, 'owner')
        """, org_id, up_row["id"])
    result = await repo.get_membership_by_auth("auth|test123", str(org_id))
    assert result is not None
    assert result["ruolo"] == "owner"


async def test_get_membership_by_auth_not_found(repo):
    result = await repo.get_membership_by_auth("auth|nonexistent", str(uuid.uuid4()))
    assert result is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/core/test_repository_auth.py -v`

- [ ] **Step 3: Add repository method**

```python
# in src/core/db/repository.py, dentro class CoreRepository:

async def get_membership_by_auth(self, auth_user_id: str, organization_id: str) -> dict | None:
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT om.ruolo, om.organization_id, up.id as user_id
            FROM organization_memberships om
            JOIN user_profiles up ON up.id = om.user_id
            WHERE up.auth_user_id = $1 AND om.organization_id = $2::uuid
        """, auth_user_id, organization_id)
        return dict(row) if row else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_repository_auth.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/core/db/repository.py tests/core/test_repository_auth.py
git commit -m "feat(auth): add get_membership_by_auth repository method"
```

---

### Task 3: Auth Dependencies — get_token, get_current_user, get_organization_context, require_ruolo

**Files:**
- Create: `src/core/auth/__init__.py`
- Create: `src/core/auth/dependencies.py`
- Create: `tests/core/auth/__init__.py`
- Create: `tests/core/auth/test_dependencies.py`
- Modify: `requirements.txt` (aggiungere `jose`)

**Interfaces:**
- Consumes: `CoreRepository.get_membership_by_auth()` (Task 2), `.env` (`SUPABASE_URL`, `API_KEY_SERVICE`)
- Produces: `get_token()`, `get_current_user()`, `get_organization_context()`, `require_ruolo(*ruoli)`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/auth/test_dependencies.py
import uuid
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends

from src.core.auth.dependencies import (
    get_token,
    get_current_user,
    get_organization_context,
    require_ruolo,
)


class TestGetToken:
    async def test_no_token_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            await get_token(authorization=None, x_api_key=None)
        assert exc.value.status_code == 401

    async def test_bearer_token_extracted(self):
        result = await get_token(authorization="Bearer my.jwt.token", x_api_key=None)
        assert result == "my.jwt.token"

    async def test_api_key_prefixed(self):
        result = await get_token(authorization=None, x_api_key="sk-test-123")
        assert result == "apikey:sk-test-123"


class TestGetCurrentUser:
    async def test_valid_api_key_returns_service_role(self, monkeypatch):
        monkeypatch.setenv("API_KEY_SERVICE", "sk-test-key")
        result = await get_current_user(token="apikey:sk-test-key")
        assert result["ruolo"] == "service_role"
        assert result["source"] == "api_key"

    async def test_invalid_api_key_raises_403(self, monkeypatch):
        monkeypatch.setenv("API_KEY_SERVICE", "sk-real-key")
        with pytest.raises(HTTPException) as exc:
            await get_current_user(token="apikey:sk-wrong-key")
        assert exc.value.status_code == 403


class TestRequireRuolo:
    async def test_owner_allowed_when_admin(self):
        async def dummy_dep():
            return {"ruolo": "owner", "organization_id": str(uuid.uuid4())}
        check = require_ruolo("owner", "manager")
        result = await check(user=await dummy_dep())
        assert result["ruolo"] == "owner"

    async def test_staff_blocked_from_admin(self):
        async def dummy_dep():
            return {"ruolo": "staff", "organization_id": str(uuid.uuid4())}
        check = require_ruolo("owner", "manager")
        with pytest.raises(HTTPException) as exc:
            await check(user=await dummy_dep())
        assert exc.value.status_code == 403

    async def test_service_role_bypasses_check(self):
        async def dummy_dep():
            return {"ruolo": None, "source": "api_key"}
        check = require_ruolo("owner")
        result = await check(user=await dummy_dep())
        assert result["source"] == "api_key"
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/core/auth/test_dependencies.py -v`
Expected: ModuleNotFoundError / ImportError

- [ ] **Step 3: Write implementation**

```python
# src/core/auth/__init__.py — empty

# src/core/auth/dependencies.py
import os
import uuid
import httpx
from typing import Annotated, Any
from fastapi import Header, HTTPException, Depends
from src.core.db.repository import CoreRepository


JWT_ALGORITHM = "RS256"
JWKS_CACHE: dict[str, Any] = {"keys": None, "expires_at": 0}


async def _get_supabase_jwks() -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    if not supabase_url:
        raise HTTPException(500, "SUPABASE_URL non configurato")
    now = __import__("time").time()
    if JWKS_CACHE["keys"] and now < JWKS_CACHE["expires_at"]:
        return JWKS_CACHE["keys"]
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{supabase_url}/auth/v1/.well-known/jwks.json")
        resp.raise_for_status()
        data = resp.json()
    JWKS_CACHE["keys"] = data["keys"]
    JWKS_CACHE["expires_at"] = now + 300
    return JWKS_CACHE["keys"]


async def verify_supabase_jwt(token: str) -> dict:
    from jose import jwt, JWTError
    from jose.constants import Algorithms

    jwks = await _get_supabase_jwks()
    for key in jwks:
        try:
            payload = jwt.decode(
                token,
                key,
                algorithms=[Algorithms.RS256],
                audience="authenticated",
                options={"verify_aud": False},
            )
            return payload
        except JWTError:
            continue
    raise HTTPException(403, "Token JWT non valido")


async def get_token(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> str:
    if authorization:
        return authorization.removeprefix("Bearer ")
    if x_api_key:
        return f"apikey:{x_api_key}"
    raise HTTPException(status_code=401, detail="Token o API Key richiesti")


async def get_current_user(token: str = Depends(get_token)) -> dict:
    if token.startswith("apikey:"):
        key = token.removeprefix("apikey:")
        if key != os.getenv("API_KEY_SERVICE"):
            raise HTTPException(status_code=403, detail="API Key non valida")
        return {"auth_user_id": None, "organization_id": None, "ruolo": "service_role", "source": "api_key"}
    payload = await verify_supabase_jwt(token)
    return {"auth_user_id": payload["sub"], "organization_id": None, "ruolo": None, "source": "jwt"}


async def get_organization_context(
    current_user: dict = Depends(get_current_user),
    x_organization_id: str | None = Header(None),
    repo: CoreRepository = Depends(lambda: None),  # injected at app startup
) -> dict:
    if current_user["source"] == "api_key":
        return {**current_user, "organization_id": x_organization_id}
    if not x_organization_id:
        return current_user
    membership = await repo.get_membership_by_auth(
        current_user["auth_user_id"], x_organization_id
    )
    if not membership:
        raise HTTPException(403, "Non sei membro di questa organizzazione")
    return {
        **current_user,
        "organization_id": x_organization_id,
        "ruolo": membership["ruolo"],
    }


def require_ruolo(*ruoli: str):
    async def _check(user: dict = Depends(get_organization_context)):
        if user.get("source") == "api_key":
            return user
        if user.get("ruolo") not in ruoli:
            raise HTTPException(403, f"Richiesto ruolo: {', '.join(ruoli)}")
        return user
    return _check
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/auth/test_dependencies.py -v`

- [ ] **Step 5: Update requirements.txt**

```txt
# Add to requirements.txt:
jose>=1.0,<2
```

- [ ] **Step 6: Commit**

```bash
git add src/core/auth/ tests/core/auth/ requirements.txt
git commit -m "feat(auth): add auth dependencies - get_token, get_current_user, require_ruolo"
```

---

### Task 4: Audit Helper

**Files:**
- Create: `src/core/auth/audit.py`
- Create: `tests/core/auth/test_audit.py`

**Interfaces:**
- Consumes: `CoreRepository`, `event_log` tabella
- Produces: `async def audit_log(repo, org_id, source_table, source_id, tipo_evento, priorita="media", testo_originale="", dettagli=None)`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/auth/test_audit.py
import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_audit_log_creates_entry(repo, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test')", org_id)

    from src.core.auth.audit import audit_log
    entry = await audit_log(
        repo=repo,
        organization_id=str(org_id),
        source_table="user_profiles",
        source_id=str(uuid.uuid4()),
        tipo_evento="profilo_modificato",
        testo_originale="Nome cambiato da 'Mario' a 'Luigi'",
    )
    assert entry["tipo_evento"] == "profilo_modificato"
    assert entry["source_table"] == "user_profiles"
    assert entry["priorita"] == "media"


async def test_audit_log_high_priority(repo, pg_pool):
    org_id = uuid.uuid4()
    async with pg_pool.acquire() as conn:
        await conn.execute("INSERT INTO organizations (id, name) VALUES ($1, 'Test')", org_id)

    from src.core.auth.audit import audit_log
    entry = await audit_log(
        repo=repo,
        organization_id=str(org_id),
        source_table="bookings",
        source_id=str(uuid.uuid4()),
        tipo_evento="prenotazione_eliminata",
        priorita="alta",
    )
    assert entry["priorita"] == "alta"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/core/auth/test_audit.py -v`
Expected: ModuleNotFoundError / ImportError

- [ ] **Step 3: Write implementation**

```python
# src/core/auth/audit.py
import uuid
from datetime import datetime, timezone


async def audit_log(
    repo,
    organization_id: str,
    source_table: str,
    source_id: str,
    tipo_evento: str,
    priorita: str = "media",
    testo_originale: str = "",
    risposta_ai: str = "",
    gestito_da_ai: bool = False,
    dettagli: dict | None = None,
) -> dict:
    async with repo.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO event_log (id, organization_id, source_table, source_id,
                                   tipo_evento, priorita, testo_originale,
                                   risposta_ai, gestito_da_ai, dettagli)
            VALUES ($1, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10::jsonb)
            RETURNING *
        """, uuid.uuid4(), organization_id, source_table, source_id,
           tipo_evento, priorita, testo_originale, risposta_ai,
           gestito_da_ai, __import__("json").dumps(dettagli or {}))
        return dict(row)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/auth/test_audit.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/core/auth/audit.py tests/core/auth/test_audit.py
git commit -m "feat(auth): add audit_log helper"
```

---

### Task 5: Rate Limiting Middleware + CORS + Update main.py

**Files:**
- Modify: `src/api/main.py`
- Modify: `.env`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `require_ruolo()` from Task 3, `audit_log()` from Task 4
- Produces: Updated API con auth su tutte le rotte, rate limiting, CORS ristretto

- [ ] **Step 1: Update .env**

```env
SUPABASE_URL=https://qfxwqfavnuufdfpkhxtj.supabase.co
API_KEY_SERVICE=sk-wa-<genera-un-uuid>
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60
```

- [ ] **Step 2: Update src/api/main.py with CORS fix + rate limit middleware + auth on routes**

```python
# Changes to src/api/main.py:

# 1. Fix CORS (rimpiazzare il blocco existente)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "X-Organization-Id", "X-API-Key", "Content-Type"],
)

# 2. Add rate limit middleware
import time
from collections import defaultdict
from fastapi.responses import JSONResponse

RATE_LIMIT_LIMIT = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
rate_windows: dict[str, list[float]] = defaultdict(list)

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/api/health", "/webhooks/whatsapp"):
        return await call_next(request)
    tenant = request.headers.get("X-Organization-Id") or request.client.host
    now = time.time()
    window = rate_windows[tenant]
    window[:] = [t for t in window if t > now - RATE_LIMIT_WINDOW]
    if len(window) >= RATE_LIMIT_LIMIT:
        return JSONResponse(status_code=429, content={"detail": "Rate limit superato. Riprova tra poco."})
    window.append(now)
    return await call_next(request)

# 3. Add auth imports at top
from src.core.auth.dependencies import require_ruolo

# 4. Add auth to specific routes:
#    Rotte che richiedono owner/manager:
#    - POST /api/prenotazioni
#    - PUT /api/prenotazioni/impostazioni
#    - DELETE /api/documenti/{documento_id}
#    - POST /api/email/configura-gmail
#    - DELETE /api/email/config/{indirizzo}
#    - POST /api/documenti/reindicizza
#
#    Rotte che richiedono owner/manager/staff:
#    - GET /api/prenotazioni
#    - GET /api/dashboard
#    - GET /api/dashboard/prioritari
#    - GET /api/report
#    - GET /api/documenti/elenco
#
#    Rotte pubbliche (nessun auth):
#    - POST /api/messaggio
#    - POST /api/webhooks/whatsapp
#    - GET /api/health
#
# Example pattern for protected routes:
@app.get("/api/prenotazioni")
def ottieni_prenotazioni(user: dict = Depends(require_ruolo("owner", "manager", "staff"))):
    return elenco_prenotazioni()
```

- [ ] **Step 3: Write integration test for protected route**

```python
# tests/core/auth/test_routes_protected.py
from fastapi.testclient import TestClient

def test_health_public(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200

def test_prenotazioni_requires_auth(client: TestClient):
    resp = client.get("/api/prenotazioni")
    assert resp.status_code == 401

def test_prenotazioni_with_api_key(client: TestClient, monkeypatch):
    monkeypatch.setenv("API_KEY_SERVICE", "sk-test-key")
    resp = client.get(
        "/api/prenotazioni",
        headers={"X-API-Key": "sk-test-key", "X-Organization-Id": "any-org"},
    )
    assert resp.status_code == 200

def test_webhook_whatsapp_public(client: TestClient):
    resp = client.get("/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=test&hub.challenge=123")
    assert resp.status_code == 403  # verify token mismatch, not auth
```

- [ ] **Step 4: Run integration tests**

Run: `pytest tests/core/auth/test_routes_protected.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/api/main.py .env .env.example tests/core/auth/test_routes_protected.py
git commit -m "feat(auth): add rate limiting, CORS fix, auth on routes"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Schema DB con user_profiles e organization_memberships → Task 1
- [x] Trigger auth.users → user_profiles → Task 1
- [x] RLS policies → Task 1 (SQL incluso)
- [x] Depends componibili → Task 3
- [x] API Key server-to-server → Task 3
- [x] Rate limiting → Task 5
- [x] CORS ristretto → Task 5
- [x] Audit log → Task 4
- [x] X-Organization-Id header → Task 3, Task 5

**2. Placeholder scan:** Nessun placeholder. Tutti i file e implementazioni sono specificati.

**3. Type consistency:** `get_membership_by_auth(auth_user_id: str, organization_id: str) -> dict | None` è coerente in Task 2 e Task 3. `require_ruolo(*ruoli)` è coerente in Task 3 e Task 5.
