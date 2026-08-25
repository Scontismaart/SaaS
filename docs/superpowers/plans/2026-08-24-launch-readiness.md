# Piano Launch Readiness — Melpis SaaS

> **Per agentic workers:** REQUIRED SUB-SKILL: usare superpowers:subagent-driven-development (consigliato) o superpowers:executing-plans per implementare questo piano task-per-task. Step con sintassi checkbox (`- [ ]`).

**Goal:** Soddisfare al 100% `CHECKLIST-LANCIO-DEFINITIVA.md` — prodotto sicuro, tracciato, monetizzato e verificato prima del primo utente reale.

**Architecture:** 5 fasi sequenziali: (A) bloccanti sicurezza Day-0 con TDD, (B) landing/CRO/SEO, (C) account recovery, (D) config produzione/ops, (E) validazione e go-to-market. Task codice seguono i pattern esistenti del repo (FastAPI + asyncpg + Valkey, test pytest in `tests/core/...`).

**Tech Stack:** FastAPI/uvicorn, asyncpg (Supabase Postgres), Valkey (Redis-compatible), Stripe SDK, nginx (container web), Plausible (proxied same-origin), Supabase Auth (BFF cookie).

## Decisioni confermate (con l'utente)
| Decisione | Valore |
|---|---|
| Prezzi canonici | **€29/€69/€149** mensili; annuo **€24/€59/€129** (-25%); overage **€0,10** |
| Analytics | **Plausible cloud proxied same-origin** (CSP invariata: `script-src 'self'`) |
| Password reset | **Incluso** (endpoint BFF + UI su /accedi/) |

## Global Constraints (da AGENTS.md, vincolanti per ogni task)
- Mai loggare segreti o contenuti sensibili; ogni log porta `organization_id`/`trace_id`
- Ogni side-effect visibile deve essere idempotente; token store one-time
- LLM mai autorizzato a mutazioni dirette; scope tenant server-side dal JWT
- Webhook Meta: ack HTTP 200 immediato, mai attendere LLM
- Dopo ogni task codice: `ruff check src tests` + pytest mirato verdi; a fine Fasi A/C: `graphify update .`
- Un commit per task; mai commettare segreti (`.env.production` è git-ignored)
- Tenant isolation: nessun dato cross-org; token store org-scoped
- Prezzi verbatim: 29/69/149 mensili; 24/59/129 annui (288/708/1548 all'anno); overage 0,10€

---

# FASE A — Bloccanti Day-0 (TDD)

## Task 1: B1 — DEMO_MODE fail-closed

**Files:**
- Modify: `src/core/auth/dependencies.py:35-37`
- Create: `src/core/startup_guard.py`
- Modify: `src/api/main.py:99` (inizio `lifespan`)
- Test: `tests/core/auth/test_demo_mode_guard.py`

- [ ] **Step 1: Test fallente**

```python
"""Bloccante B1: DEMO_MODE e' fail-closed in produzione."""
import pytest
from src.core.auth import dependencies
from src.core.startup_guard import assert_production_safe


def test_demo_mode_ignorato_in_produzione(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "true")
    assert dependencies.is_demo_mode() is False


def test_demo_mode_attivo_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "1")
    assert dependencies.is_demo_mode() is True


def test_startup_bloccato_demo_in_prod(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "1")
    with pytest.raises(RuntimeError, match="B1"):
        assert_production_safe()


def test_startup_ok_in_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    assert_production_safe()  # non alza
```

- [ ] **Step 2: Run** `pytest tests/core/auth/test_demo_mode_guard.py -v` → FAIL (`ModuleNotFoundError: startup_guard`)
- [ ] **Step 3: Implementazione** — in `dependencies.py`:

```python
def is_demo_mode() -> bool:
    _load_project_env()
    # Bloccante B1 (fail-closed): in produzione l'accesso anonimo demo e'
    # sempre negato, qualunque sia il valore di DEMO_MODE nell'ambiente.
    from src.core.security.docs import is_production
    if is_production():
        return False
    return os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
```

Nuovo `src/core/startup_guard.py` (esteso in Task 3 con B4):

```python
"""Guardie fail-fast all'avvio in produzione (Bloccanti B1/B4)."""
import os


def assert_production_safe() -> None:
    from src.core.security.docs import is_production

    if not is_production():
        return
    demo = os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
    if demo:
        raise RuntimeError(
            "AVVIO BLOCCATO: DEMO_MODE attivo con APP_ENV=production (B1). "
            "Rimuovi DEMO_MODE dalla configurazione di produzione."
        )
```

In `main.py`, primissima riga di `lifespan()`:

```python
    from src.core.startup_guard import assert_production_safe
    assert_production_safe()
```

- [ ] **Step 4: Run** → PASS; poi `pytest tests/core/auth/ -v` → nessuna regressione
- [ ] **Step 5: Commit** `feat(security): B1 fail-closed DEMO_MODE in produzione`

## Task 2: B3 — Export token GDPR su Redis (TTL 15 min)

**Files:**
- Create: `src/core/gdpr/token_store.py`
- Modify: `src/core/gdpr/routes.py` (rimuovere `_export_tokens` alle righe 20-28, sostituire usi a righe 202-209)
- Test: `tests/core/gdpr/test_token_store.py`

**Interfaces:** Produces `save_token(token: str, org_id: str, data: dict) -> None` e `pop_token(token: str) -> dict | None` (one-time, atomico).

- [ ] **Step 1: Test fallente**

```python
"""Bloccante B3: i token di export GDPR vivono in Redis con TTL 15 min."""
import pytest
from src.core.gdpr import token_store


class FakeRedis:
    def __init__(self):
        self.d = {}

    async def set(self, key, value, ex=None):
        self.d[key] = value

    async def getdel(self, key):
        return self.d.pop(key, None)


@pytest.fixture(autouse=True)
def _reset_store(monkeypatch):
    monkeypatch.setattr(token_store, "_memory", {})
    monkeypatch.setattr(token_store, "_redis", None)


def _use(fake, monkeypatch):
    async def _get():
        return fake
    monkeypatch.setattr(token_store, "_get_redis", _get)


@pytest.mark.asyncio
async def test_token_consumo_one_time(monkeypatch):
    fake = FakeRedis()
    _use(fake, monkeypatch)
    await token_store.save_token("t1", "org-1", {"dati": [1]})
    meta = await token_store.pop_token("t1")
    assert meta["org_id"] == "org-1"
    assert await token_store.pop_token("t1") is None  # one-time


@pytest.mark.asyncio
async def test_token_sconosciuto(monkeypatch):
    _use(FakeRedis(), monkeypatch)
    assert await token_store.pop_token("nope") is None


@pytest.mark.asyncio
async def test_fallback_memory_senza_redis(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    await token_store.save_token("t2", "org-2", {})
    assert (await token_store.pop_token("t2"))["org_id"] == "org-2"


@pytest.mark.asyncio
async def test_token_scaduto(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    await token_store.save_token("t3", "org-3", {})
    token_store._memory["t3"]["expires"] = 0  # forzato scaduto
    assert await token_store.pop_token("t3") is None
```

- [ ] **Step 2: Run** `pytest tests/core/gdpr/test_token_store.py -v` → FAIL
- [ ] **Step 3: Implementazione** — nuovo `src/core/gdpr/token_store.py`:

```python
"""Store dei token di export GDPR (Bloccante B3).

Il dict in-memory per-processo e' stato rimosso: i token devono sopravvivere
ai restart ed essere condivisi tra i worker uvicorn. Con REDIS_URL usano
Redis/Valkey con TTL 15 minuti; in dev/test senza Redis si degrada sul
backend in-memory (stesso contratto, stessi TTL)."""
import json
import os
import time
from typing import Any

TOKEN_TTL_SECONDS = 15 * 60
_PREFIX = "gdpr:export:"
_memory: dict[str, dict[str, Any]] = {}
_redis = None


async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL", "").strip()
    if not url:
        return None
    from redis.asyncio import Redis

    _redis = Redis.from_url(url, decode_responses=True)
    return _redis


async def save_token(token: str, org_id: str, data: dict) -> None:
    payload = json.dumps(
        {"org_id": org_id, "data": data, "expires": time.time() + TOKEN_TTL_SECONDS}
    )
    r = await _get_redis()
    if r is not None:
        await r.set(_PREFIX + token, payload, ex=TOKEN_TTL_SECONDS)
    else:
        _memory[token] = {
            "org_id": org_id, "data": data,
            "expires": time.time() + TOKEN_TTL_SECONDS,
        }


async def pop_token(token: str) -> dict | None:
    """Consuma il token (one-time). None se assente o scaduto."""
    r = await _get_redis()
    if r is not None:
        raw = await r.getdel(_PREFIX + token)  # atomico: un solo consumo
        if raw is None:
            return None
        meta = json.loads(raw)
    else:
        meta = _memory.pop(token, None)
        if meta is None:
            return None
    if meta.get("expires", 0) < time.time():
        return None
    return meta
```

In `routes.py`: eliminare `_export_tokens` e il blocco di inizializzazione (righe 20-28); dove il token viene creato → `await token_store.save_token(token, str(org_id), data)`; nel GET di consumazione sostituire il blocco (righe 202-209) con:

```python
    meta = await token_store.pop_token(token)
    if meta is None:
        raise HTTPException(status_code=404, detail="Link di export scaduto o non valido")
    org_id = meta["org_id"]
    data = meta["data"]
```

Adattare i nomi variabili al codice circostante reale mantenendo la risposta HTTP identica.

- [ ] **Step 4: Run** → PASS; `pytest tests/core/gdpr/ -v` → verdi
- [ ] **Step 5: Commit** `feat(gdpr): B3 export token store su Redis con TTL 15min`

## Task 3: B4 — ENCRYPTION_KEY fail-fast + generazione

**Files:**
- Modify: `src/core/startup_guard.py` (estende `assert_production_safe`)
- Test: `tests/core/auth/test_demo_mode_guard.py` (aggiunge 3 test)

- [ ] **Step 1: Test** (aggiungere al file del Task 1):

```python
def test_startup_bloccato_senza_encryption_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="B4"):
        assert_production_safe()


def test_startup_bloccato_chiave_invalida(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENCRYPTION_KEY", "non-una-chiave")
    with pytest.raises(RuntimeError, match="B4"):
        assert_production_safe()


def test_startup_ok_con_chiave_valida(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert_production_safe()
```

- [ ] **Step 2: Run** → FAIL. **Step 3:** aggiungere in fondo a `assert_production_safe()` (dopo il blocco B1):

```python
    key = os.getenv("ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "AVVIO BLOCCATO: ENCRYPTION_KEY mancante in produzione (B4). "
            "Genera con: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    from cryptography.fernet import Fernet
    try:
        Fernet(key)
    except Exception as exc:
        raise RuntimeError(
            "AVVIO BLOCCATO: ENCRYPTION_KEY non e' una chiave Fernet valida (B4)."
        ) from exc
```

- [ ] **Step 4: Run** → PASS. **Step 5 (OPS, utente):** genera la chiave col comando dell'errore, inseriscila nel secrets manager di produzione (mai in git). **Step 6: Commit** `feat(security): B4 fail-fast ENCRYPTION_KEY in produzione`

## Task 4: B2 — Rate limiting Redis (config + verifica)

Codice già completo (`src/core/rate_limit.py`). Config-only:

- [ ] In `.env.production` (Task 13): `RATE_LIMIT_BACKEND=redis`, `REDIS_URL=redis://valkey:6379/0` (nome servizio compose; con password: `redis://:<password>@valkey:6379/0`)
- [ ] Verifica distribuita: chiamare `get_rate_limiter()` + `limiter.hit("test:b2", 5, 60)` due volte → seconda chiamata counter=2; `docker compose restart api` → contatore persiste (prova che NON è in-memory)
- [ ] Spunta verifica (nessun commit atteso)

## Task 5: B5a — Prezzi backend €29/€69/€149 + fatturazione annuale (TDD)

**Files:**
- Modify: `src/core/billing/plans.py` (intero)
- Modify: `src/core/billing/routes.py:16-20, 62-77`
- Test: `tests/core/billing/test_plans_pricing.py`

- [ ] **Step 0: Mappa consumatori** — cercare `price_monthly_eur`, `stripe_price_id`, `Plan(` in `src/` e `tests/`; aggiornare ogni costruttore/uso (i test che istanziano `Plan` posizionale vanno migrati a keyword args)
- [ ] **Step 1: Test fallente**

```python
"""B5: griglia prezzi Essenziale/Crescita/Scala + supporto annuale."""
import pytest
from src.core.billing.plans import PLANS


def test_prezzi_canonici():
    assert PLANS["starter"].price_monthly_eur == 29
    assert PLANS["pro"].price_monthly_eur == 69
    assert PLANS["business"].price_monthly_eur == 149


def test_prezzi_annuali_25_percento():
    assert PLANS["starter"].price_yearly_eur == 288   # 24*12
    assert PLANS["pro"].price_yearly_eur == 708       # 59*12
    assert PLANS["business"].price_yearly_eur == 1548 # 129*12


def test_nomi_commerciali():
    assert PLANS["starter"].name == "Essenziale"
    assert PLANS["pro"].name == "Crescita"
    assert PLANS["business"].name == "Scala"


def test_limiti_invariati():
    assert PLANS["starter"].messages_limit == 300
    assert PLANS["pro"].messages_limit == 1200
    assert PLANS["business"].messages_limit == 5000
    assert PLANS["pro"].has_reviews is True
    assert PLANS["business"].has_rag is True


def test_resolve_price_id():
    from src.core.billing.routes import _resolve_price_id
    p = PLANS["pro"]
    p.stripe_price_id = "price_m"
    p.stripe_price_id_yearly = "price_y"
    assert _resolve_price_id(p, "monthly") == "price_m"
    assert _resolve_price_id(p, "yearly") == "price_y"


def test_resolve_price_id_intervallo_invalido():
    from src.core.billing.routes import _resolve_price_id
    with pytest.raises(ValueError):
        _resolve_price_id(PLANS["pro"], "settimanale")
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implementazione** — `plans.py`: `Plan` guadagna `stripe_price_id_yearly: str` e `price_yearly_eur: int`; nomi `Essenziale/Crescita/Scala`; prezzi 29/69/149 e 288/708/1548; env `STRIPE_PRICE_STARTER_YEARLY`, `STRIPE_PRICE_PRO_YEARLY`, `STRIPE_PRICE_BUSINESS_YEARLY`. Slug invariati (`starter/pro/business`) per compatibilità API/DB. Limiti e feature flag invariati (300/1200/5000, has_reviews, has_rag).

In `routes.py`:

```python
class CheckoutSessionRequest(BaseModel):
    plan: str
    success_url: str
    cancel_url: str
    interval: str = "monthly"  # "monthly" | "yearly"


def _resolve_price_id(plan, interval: str) -> str:
    if interval not in ("monthly", "yearly"):
        raise ValueError(f"interval non valido: {interval}")
    return plan.stripe_price_id_yearly if interval == "yearly" else plan.stripe_price_id
```

In `create_checkout_session`, sostituire il blocco di lookup price con:

```python
    plan = PLANS[req.plan]
    try:
        price_id = _resolve_price_id(plan, req.interval)
    except ValueError:
        raise HTTPException(status_code=400, detail="interval non valido: monthly|yearly")
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Stripe price ID ({req.interval}) non configurato per: {req.plan}",
        )
```

`line_items=[{"price": price_id, "quantity": 1}]`; audit `details={"plan": req.plan, "interval": req.interval, "session_id": session.id}`.

- [ ] **Step 4: Run** `pytest tests/core/billing/ -v` → PASS (aggiornare eventuali test esistenti sui prezzi vecchi). **Step 5: Commit** `feat(billing): B5 prezzi 29/69/149 + checkout annuale`

## Task 6: B6 — Webhook Meta WhatsApp Live (ops, utente)

- [ ] Meta Business Suite: app creata, prodotto WhatsApp aggiunto, numero reale verificato
- [ ] `META_APP_SECRET` (App Settings → Basic) e `META_VERIFY_TOKEN` (random ≥32 char) nel secrets manager
- [ ] Webhook URL `https://melpis.it/webhooks/whatsapp` (campo `messages`), verify handshake OK
- [ ] Verifica firma: messaggio di test → `X-Hub-Signature-256` validata (router montato solo con entrambe le env: `main.py:138`)
- [ ] Webhook Instagram `/webhooks/instagram` (stessa app)

---

# FASE B — Landing, CRO, SEO

## Task 7: Prezzi landing + overage €0,10

**Files:** Modify `web/landing/index.html` (righe 40-42, 624, 627, 644, 647, 664, 667, 678, 713), `web/landing/termini.html:51`

- [ ] Card Essenziale (~riga 624): `data-monthly="29" data-yearly="24"`; nota annuo: `Fatturato 288€/anno (risparmi 60€)`
- [ ] Card Crescita (~644): `data-monthly="69" data-yearly="59"`; `Fatturato 708€/anno (risparmi 120€)`
- [ ] Card Scala (~664): `data-monthly="149" data-yearly="129"`; `Fatturato 1.548€/anno (risparmi 240€)`
- [ ] ~Riga 678 e ~713: `0,08€` → `0,10€`; `termini.html:51`: `0,08€` → `0,10€`
- [ ] Verifica coerenza limiti mostrati (300/1.200/5.000 conversazioni) con `plans.py`
- [ ] Verifica visiva su http://localhost:8080 (rebuild web) e screenshot 1440/360
- [ ] Commit `feat(landing): nuovi prezzi 29/69/149 + overage 0,10`

## Task 8: SEO — FAQPage JSON-LD + sitemap

**Files:** Modify `web/landing/index.html:31-45`, `web/landing/sitemap.xml`

- [ ] Sostituire il blocco JSON-LD con **due** script: `SoftwareApplication` (offers aggiornate a 29/69/149) + `FAQPage` con le 6 domande ESATTE già presenti alle righe 691-741 (testo verbatim dagli elementi `<span>` delle domande e `<p>` delle risposte: 1. "Ho bisogno di un account WhatsApp Business?", 2. "Quanto tempo ci vuole per configurare l'assistente?", 3. "Cosa succede se supero le conversazioni incluse nel piano?", 4. "L'AI può inventare risposte o dare informazioni errate?", 5. "Posso disdire l'abbonamento o cambiare piano quando voglio?", 6. "I dati dei miei clienti sono al sicuro e conformi al GDPR?")
- [ ] `sitemap.xml` nuovo contenuto:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://melpis.it/</loc><lastmod>2026-08-24</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>https://melpis.it/privacy/</loc><lastmod>2026-08-24</lastmod><priority>0.3</priority></url>
  <url><loc>https://melpis.it/termini/</loc><lastmod>2026-08-24</lastmod><priority>0.3</priority></url>
  <url><loc>https://melpis.it/cookie/</loc><lastmod>2026-08-24</lastmod><priority>0.3</priority></url>
</urlset>
```

- [ ] Validazione sintattica JSON (estrarre e `json.loads`); validazione schema post-deploy su Google Rich Results Test
- [ ] Commit `feat(seo): FAQPage JSON-LD + sitemap con pagine legali`

## Task 9: Social proof + micro-stat di fiducia

**Files:** Modify `web/landing/index.html` (nuova sezione prima della sezione prezzi), `web/landing/style.css`, bump `style.css?v=white-theme-7` in tutti gli HTML landing

- [ ] HTML: sezione `id="testimonial"` con griglia 3 `<figure class="testimonial-card">` (blockquote + figcaption con foto/nome/attività-città), attributo `hidden` finché le 3 testimonianze reali (Task 20) non sono pronte — **mai testimonianze finte** (rischio legal/GDPR). Posizionamento: SUBITO PRIMA della sezione prezzi
- [ ] CSS: `.testimonial-grid` 3 colonne (1 su mobile ≤768px), card stile coerente con `.bento-card`
- [ ] Micro-stat sopra il fold: verificare le stat-card esistenti (~righe 287-305: copertura richieste, tempo risposta, intervento operatore) e allinearle ai 3 micro-stat della checklist ("Setup guidato in meno di 10 minuti", "Tempo medio di risposta < 5 secondi", "100% Conforme GDPR & Meta API Ufficiale") — aggiungere/modificare quello mancante
- [ ] Verifica visiva 1440 + 360 su localhost:8080
- [ ] Commit `feat(landing): sezione social proof (nascosta finché non ci sono testimonianze reali)`

## Task 10: Plausible proxied + eventi conversione

**Files:** Modify `web/nginx.conf` (nuova location), `web/landing/index.html` (script tag + `data-track-location` sui 5 pulsanti `data-signup`: ~riga 83 nav, ~107 hero, ~635 essenziale, ~656 crescita, ~754 CTA finale), `web/landing/app.js`

- [ ] `nginx.conf` — aggiungere prima del blocco asset statici:

```nginx
    # Plausible (cloud) proxied same-origin: CSP resta script-src 'self',
    # nessun cookie, nessuna richiesta verso domini terzi dal browser.
    location /plausible/ {
        proxy_pass https://plausible.io/;
        proxy_ssl_server_name on;
        proxy_set_header Host plausible.io;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
```

- [ ] `index.html` `<head>`: `<script defer data-domain="melpis.it" data-api="/plausible/api/event" src="/plausible/js/script.js"></script>`
- [ ] `app.js` — helper in cima all'IIFE:

```js
    function trackEvent(name, props) {
        if (typeof window.plausible === 'function') {
            window.plausible(name, { props: props || {} });
        }
    }
```

- [ ] Wiring (4 eventi): `click_cta` con `location` da `data-track-location` + `plan` da `data-plan`; `open_signup_modal` (dove `modal.hidden = false`); `submit_signup_form` SOLO su risposta OK del POST `/api/auth/register`; `toggle_pricing_annual` con `{enabled: yearly}` nel listener `#pricingToggle`
- [ ] Attributi `data-track-location`: `nav`, `hero`, `pricing_essenziale`, `pricing_crescita`, `footer` (CTA finale)
- [ ] Verifica: `curl -sI http://localhost:8080/plausible/js/script.js` → 200; CSP invariata; nessun errore console
- [ ] OPS utente: account Plausible → aggiungere dominio `melpis.it`
- [ ] Commit `feat(analytics): Plausible same-origin + eventi CTA/signup/toggle`

## Task 11: Cookie notice banner

**Files:** Modify `web/landing/index.html` (prima di `</body>`), `web/landing/app.js`, `web/landing/style.css`

- [ ] HTML:

```html
<div class="cookie-notice" id="cookieNotice" hidden role="region" aria-label="Informativa breve cookie">
    <p>Melpis usa solo cookie tecnici necessari al login. Le statistiche sono anonymous e senza cookie. <a href="/cookie/">Dettagli</a></p>
    <button type="button" id="cookieOk" class="btn-primary">OK</button>
</div>
```

- [ ] JS: mostra se `!localStorage.getItem('cookie_notice_ok')`; click `#cookieOk` → set flag + hide. CSS: barra fissa bottom, z-index sotto il modal signup, responsive mobile
- [ ] Nota: solo cookie tecnico BFF (necessario, esenzione) + Plausible cookieless → banner-informativa sufficiente
- [ ] Verifica visiva + commit `feat(landing): cookie notice minimale conforme`

---

# FASE C — Account

## Task 12: Password reset (recover + reset) — TDD

**Files:**
- Modify: `src/core/auth/routes.py` (2 nuovi endpoint, pattern `_supabase_update_user`/throttle esistenti alle righe 275-354)
- Modify: `web/login.html`, `web/login.js`
- Test: `tests/core/auth/test_password_recovery.py` (mock httpx con `respx`, già in requirements — guardare il pattern di `tests/core/auth/test_bff.py`)

**Interfaces:** `POST /api/auth/recover {email}` → sempre `200 {"ok": true}` (no enumerazione account); `POST /api/auth/reset {access_token, password}` → `200 {"ok": true}` (usa `PUT /auth/v1/user` con il token recovery).

- [ ] **Step 1: Test fallente** — casi: recover email malformata→422; recover risponde sempre 200 anche per email inesistente; recover rate-limitato dopo 5 richieste/ora/IP→429; reset policy password (≥10 + almeno 1 speciale)→422; reset token valido→200 e PUT verso Supabase; reset token scaduto (Supabase 401)→401
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implementazione** — endpoint:

```python
class RecoverRequest(BaseModel):
    email: str


class ResetPassword(BaseModel):
    access_token: str
    password: str


@router.post("/recover")
async def recover_password(body: RecoverRequest, request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Email non valida")
    import httpx
    client = await bff._client()
    try:
        await client.post(
            f"{bff._supabase_url()}/auth/v1/recover",
            json={"email": email},
            headers={"apikey": bff._anon_key(), "Content-Type": "application/json"},
        )
    except httpx.HTTPError:
        pass  # Nessuna enumerazione account: risposta sempre identica.
    return {"ok": True,
            "message": "Se l'email e' registrata riceverai un link di recupero."}


@router.post("/reset")
async def reset_password(body: ResetPassword, request: Request):
    ip = _client_ip(request)
    await _check_account_throttle(ip)
    await throttle.record_event(_account_throttle_key(ip), _ACCOUNT_CHANGE_WINDOW)
    pwd = body.password
    if len(pwd) < _PASSWORD_MIN or not _SPECIAL_RE.search(pwd):
        raise HTTPException(
            422,
            f"La password deve avere almeno {_PASSWORD_MIN} caratteri "
            "e includere almeno un carattere speciale (es. ! @ # $ %)",
        )
    await _supabase_update_user(body.access_token, {"password": pwd})
    return {"ok": True, "message": "Password aggiornata, ora puoi accedere"}
```

- [ ] **Step 4: Frontend** — `login.html`: link `#forgotLink` + `#recoverForm` (email → POST `/api/auth/recover`, messaggio successo neutro) + `#resetForm` (nuova password → POST `/api/auth/reset` con `access_token` estratto da `location.hash` quando presente `access_token=` e `type=recovery`); `login.js` gestisce i tre stati
- [ ] **Step 5: Run** `pytest tests/core/auth/ -v` → PASS
- [ ] **Step 6 (OPS, con Task 15):** Supabase Dashboard → Auth → URL Configuration: Site URL `https://melpis.it/accedi/`; template email "Reset Password" in italiano
- [ ] **Step 7: Commit** `feat(auth): flusso recupero password recover/reset`

---

# FASE D — Config produzione & Ops

## Task 13: `.env.production` + CORS

- [ ] Verifica `.gitignore` contiene `.env.production` (✓ già presente, riga 6)
- [ ] Create `.env.production.example` (commit-abile): parte da `.env.example` + `APP_ENV=production`, `DEMO_MODE` **assente**, `DATABASE_URL=postgresql://user:pass@host:5432/dbname?sslmode=require`, `DB_POOL_MAX_SIZE=10`, `REDIS_URL=redis://valkey:6379/0`, `RATE_LIMIT_BACKEND=redis`, `CORS_ORIGINS=https://melpis.it,https://app.melpis.it`, `ENCRYPTION_KEY=<da Task 3>`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_AUD=authenticated`, 6 `STRIPE_PRICE_*` (3 mensili + 3 yearly), `STRIPE_SECRET_KEY=sk_live_...`, `STRIPE_WEBHOOK_SECRET=whsec_...`, `STRIPE_RETURN_URL=https://app.melpis.it/`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `OPENROUTER_API_KEY`, `SENTRY_DSN`, `SMTP_HOST/PORT/USER/PASSWORD/FROM`, `PUBLIC_APP_URL=https://melpis.it`
- [ ] Nota: `is_production()` legge `APP_ENV` **o** `ENVIRONMENT` (`security/docs.py:16`) — usiamo `APP_ENV` per coerenza con `.env.example`
- [ ] `.env.production` reale compilato SOLO sul server/segreti
- [ ] Commit `chore(config): template env produzione`

## Task 14: Dominio, DNS, SSL (ops, utente)

- [ ] DNS: `A`/`AAAA` `melpis.it`; `A`/`AAAA` `app.melpis.it`; verifica `dig +short`
- [ ] HTTPS forzato + HSTS a livello Traefik (nota in `web/security-headers.conf:7`): `stsSeconds=31536000, includeSubDomains, preload`
- [ ] Email DNS: `SPF` (`v=spf1 include:<provider> ~all`), `DKIM` (record provider), `DMARC` (`v=DMARC1; p=quarantine; rua=mailto:privacy@melpis.it`)
- [ ] Acceptance: SSL Labs ≥ A; mail-tester.com ≥ 10/10; `https://app.melpis.it/api/health` → 200

## Task 15: Email transazionali (ops, utente)

- [ ] Supabase Auth → SMTP custom con le `SMTP_*` di produzione; template IT "Confirm signup" e "Reset Password" (link coerenti con Site URL)
- [ ] Test: registrazione reale → email + link verifica OK; recover (Task 12) → email + reset OK
- [ ] HITL: trigger escalation → email arriva (`email_service.py`); report settimanale: `GET /api/report/settimanale` → email arriva
- [ ] Acceptance: 4 email testate end-to-end

## Task 16: Backup, Sentry, Uptime (ops, utente)

- [ ] Backup giornalieri attivi con **retention 30 giorni** verificata
- [ ] `docker compose run --rm backup-drill` verde (restore testato)
- [ ] Sentry: `SENTRY_DSN` attivo + alert; errore di test visibile su dashboard
- [ ] Uptime esterno (BetterStack/UptimeRobot) su `https://melpis.it/api/health` con alert Telegram/SMS; test: stop api → alert ricevuto

## Task 17: Legal review

- [ ] `privacy.html:61-63`: aggiungere sub-processore **OpenRouter** (`<li><strong>OpenRouter</strong> — instradamento dei modelli AI; i provider sono configurati per non addestrare sui dati.</li>`) e verificare che l'hosting sia elencato
- [ ] Verifica `https://melpis.it/api/gdpr/dpa` raggiungibile (`gdpr/routes.py:112`)
- [ ] Banner cookie (Task 11) + `cookie.html` coerenti col setup finale (Plausible cookieless)
- [ ] Commit `docs(legal): sub-processori completi in privacy policy`

## Task 18: Supporto Day-1 (ops, utente)

- [ ] `support@melpis.it` creato (Google Workspace/Zoho), alias `privacy@` e `sales@` attivi
- [ ] Numero WhatsApp Business assistenza attivo in ore di servizio (footer già linkato: `index.html:792`)

---

# FASE E — Validazione & Go-to-Market

## Task 19: Smoke test E2E in produzione (Go/No-Go, ops, utente)

- [ ] Registrazione da landing (`#signupForm`) → email verifica → primo login dashboard
- [ ] Connessione guidata WhatsApp + orari/menu; messaggio reale → risposta AI < 5s (log `trace_id`)
- [ ] Sottoscrizione Stripe **Live** carta reale (Crescita) → webhook `checkout.session.completed` → `GET /api/billing/subscription` coerente
- [ ] Cancellazione dal portal Stripe → webhook `canceled` → stato sospeso/sola-lettura (`suspension.py`)
- [ ] Opt-out WhatsApp ("STOP") → consenso persistito, nessun invio successivo, audit event
- [ ] Escalation HITL → notifica email ricevuta
- [ ] Rollback plan documentata (restore drill + ritorno a test mode)

## Task 20: Validazione prezzo + testimonianze (settimane 2-3, business, utente)

- [ ] Van Westendorp: 4 domande a 15-20 lead/pilota; analisi PSM → conferma o rettifica 29/69/149 PRIMA dei price ID definitivi in Stripe Live
- [ ] Mini-pilota gratuito 3-5 attività locali in cambio di testimonianza scritta + autorizzazione uso nome/logo
- [ ] 3 citazioni con foto → riempire sezione Task 9, rimuovere `hidden`, rebuild web
- [ ] A/B prezzi sul traffico (eventi Plausible come metrica proxy)

## Task 21: Meta Pixel + campagne (settimana 4+, post-lancio, ops, utente)

- [ ] All'attivazione campagne: Pixel richiede update CSP in `web/security-headers.conf` (`script-src 'self' https://connect.facebook.net; connect-src 'self' https://connect.facebook.net`) + script Pixel con Consent Mode
- [ ] Campagne Lookalike su titolari P.IVA locali; primo case study dai dati del pilota
- [ ] Setup fee onboarding assistito su piano Scala (Stripe product one-off)

---

## Mappatura copertura checklist → task

| Checklist | Task |
|---|---|
| Sez.1 Pricing (29/69/149, annuo -25%, overage 0,10) | 5, 7, 20 |
| Gap #1 Social proof + micro-stat | 9, 20 |
| Gap #2 FAQPage + sitemap | 8 |
| Gap #3 Plausible + 4 eventi (+Meta Pixel) | 10, 21 |
| B1→B6 | 1, 4, 2, 3, 5+13(Stripe ops), 6 |
| DNS/SSL/HSTS/email DNS | 14 |
| `.env.production` completa | 13 |
| Email transazionali (verifica/reset/HITL) | 15, 12 |
| Backup 30gg + drill + Sentry + uptime | 16 |
| Legali (privacy/termini/cookie/DPA) | 7, 11, 17 |
| Smoke test E2E (6 punti) | 19 |
| Supporto Day-1 | 18 |
| Timeline settimane 1/2-3/4+ | Fasi A-B (set.1), Task 20 (set.2-3), Task 21 (set.4+) |
