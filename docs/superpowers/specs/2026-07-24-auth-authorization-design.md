# Auth & Authorization — Design

## Provider: Supabase Auth
Già su Supabase per il DB. Zero cost aggiuntivo, zero vendor lock-in.

---

## 1. Schema DB — Nuove tabelle

### user_profiles
Mirror di `auth.users` di Supabase con dati extra.

```sql
CREATE TABLE IF NOT EXISTS user_profiles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id    UUID NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    nome            TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### organization_memberships
Legame molti-a-molti utente → organizzazione con ruolo.

```sql
CREATE TABLE IF NOT EXISTS organization_memberships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES user_profiles(id) ON DELETE CASCADE,
    ruolo           TEXT NOT NULL CHECK (ruolo IN ('owner', 'manager', 'staff')),
    invited_at      TIMESTAMPTZ DEFAULT NOW(),
    joined_at       TIMESTAMPTZ,
    UNIQUE(organization_id, user_id)
);
```

### Trigger: auth.users → user_profiles automatico
```sql
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
```

### Row Level Security
```sql
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_profiles_self ON user_profiles
    FOR ALL USING (auth_user_id = auth.uid());

ALTER TABLE organization_memberships ENABLE ROW LEVEL SECURITY;
CREATE POLICY memberships_self ON organization_memberships
    FOR SELECT USING (
        user_id IN (SELECT id FROM user_profiles WHERE auth_user_id = auth.uid())
    );
```

---

## 2. Auth Flow — Dependency Injection (FastAPI)

### Dipendenze componibili in `src/core/auth/dependencies.py`

```
get_token()                      -- estrae Authorization: Bearer o X-API-Key
    ↓
get_current_user()               -- verifica JWT (Supabase JWKS) o API Key (.env)
    ↓
get_organization_context()       -- incrocia JWT + X-Organization-Id → ruolo
    ↓
require_ruolo("owner",...)       -- guard check sul ruolo
```

### get_token
```python
async def get_token(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
) -> str
```
Accetta Bearer JWT o API Key (X-API-Key). Nessun token → 401.

### get_current_user
- Se `apikey:<valore>` matcha `API_KEY_SERVICE` in `.env` → `{ruolo: "service_role", source: "api_key"}`
- Se JWT → verifica con Supabase JWKS endpoint → estrae `sub` (auth_user_id)
- Token invalido → 403

### get_organization_context
- Prende `X-Organization-Id` dall'header
- Query: `SELECT ruolo FROM organization_memberships WHERE user_id = $1 AND organization_id = $2`
- Nessuna membership → 403
- Attacca `organization_id` e `ruolo` al dict utente

### require_ruolo(*ruoli)
```python
def require_ruolo(*ruoli: str):
    async def _check(user = Depends(get_organization_context)):
        if user["ruolo"] not in ruoli and user["source"] != "api_key":
            raise HTTPException(403)
        return user
    return _check
```

### Applicazione
- Route admin: `Depends(require_ruolo("owner", "manager"))`
- Route staff (sola lettura): `Depends(require_ruolo("owner", "manager", "staff"))`
- Webhook WhatsApp: nessun Depends (usa HMAC invariato)
- Health: nessun Depends (pubblico)

---

## 3. API Key Server-to-Server
```env
API_KEY_SERVICE=sk-wa-<uuid-casuale>
```
Usata con header `X-API-Key`. Assegna ruolo `service_role` che bypassa tutti i controlli ruolo.

---

## 4. Rate Limiting — Per tenant (in-memory)

- Sliding window in `collections.defaultdict[tenant_key, list[timestamp]]`
- Default: 100 richieste / 60 secondi
- `tenant_key` = `X-Organization-Id` o IP se assente
- Esclude `/api/health` e `/webhooks/whatsapp`

> **Limitazione nota (single-process):** lo stato è in-memory nel processo
> Python. Con più worker/repliche il limite effettivo per tenant scala
> circa linearmente col numero di processi, perché ogni processo conta in
> modo indipendente. Accettabile per un singolo processo/demo; per
> deployment multi-processo servirebbe uno store condiviso (Redis) — vedi
> sezione "Futuro".

```python
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path in ("/api/health", "/webhooks/whatsapp"):
        return await call_next(request)

    tenant = request.headers.get("X-Organization-Id") or request.client.host
    now = time.time()
    window = request.app.state.rate_windows[tenant]
    window[:] = [t for t in window if t > now - RATE_LIMIT_WINDOW]
    if len(window) >= RATE_LIMIT_LIMIT:
        return JSONResponse(status_code=429, content={"detail": "Rate limit superato. Riprova tra poco."})
    window.append(now)
    return await call_next(request)
```

---

## 5. CORS
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "X-Organization-Id", "X-API-Key", "Content-Type"],
)
```

---

## 6. Audit Log
Tabella `audit_log` separata (in `002_auth_tables.sql`), non `event_log` — per non violare l'invariante che event_log è popolato solo da trigger DB.

```sql
CREATE TABLE IF NOT EXISTS audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id),
    user_id         UUID REFERENCES user_profiles(id),
    auth_user_id    TEXT,
    action          TEXT NOT NULL,
    target_table    TEXT,
    target_id       UUID,
    details         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

Azioni sensibili da auditare:
- `profilo_modificato` → user_profiles
- `risposta_manuale` → messages
- `ruolo_cambiato` → organization_memberships
- `prenotazione_eliminata` → bookings

Trigger DB (già in `triggers.sql`) continuano a popolare event_log per messaggi e recensioni.

### Repository injection
`get_organization_context()` usa `Depends(get_repo)`, che legge `request.app.state.repo` inizializzato nel lifespan di FastAPI. Non più `Depends(lambda: None)`.

### RLS policies
`user_profiles` e `organization_memberships` hanno RLS attivo con policy per self-access.

---

## Futuro (non implementato ora)
- Cache LRU in-memory per membership queries (fase 2)
- Rate limiting persistente su Postgres se necessario
