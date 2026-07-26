# Booking Standalone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the booking module from Airtable+RAM global variables into a standalone product with confirm/reject WhatsApp notifications, 24h reminder, no-show tracking, and optional Stripe deposit.

**Architecture:** New `src/core/bookings/` package with `BookingService` using `CoreRepository` (extended) + `WhatsAppService` for messaging. Old `prenotazioni.py` global variables removed, replaced by DB queries filtered by `organization_id`. Scheduler jobs iterate per-org. Reminder reply hook in inbound_processor pipeline (opt-out → reminder → AI).

**Tech Stack:** Python 3.12, FastAPI, asyncpg, APScheduler, Stripe, pytest + testcontainers (pgvector/pg16)

**Design doc:** `docs/superpowers/specs/2026-07-26-booking-standalone-design.md`

## Global Constraints

- Every DB query includes `WHERE organization_id = $1` (app-level isolation, no RLS for bookings tables — pattern accepted, same as conversations/messages)
- All async functions use `async/await` with asyncpg
- WhatsApp messages sent via existing `WhatsAppService.send_whatsapp_message()` requiring `tenant_config` (loaded per-org)
- Pipeline order in inbound_processor: opt-out (GDPR) → reminder reply → fast_path_match → AI responder
- Stripe webhook routing: `mode = subscription` → billing logic; `mode = payment` → booking deposit logic
- `past_due` orgs excluded from scheduler jobs (`subscription_status NOT IN ('canceled','incomplete','past_due')`)
- Two separate repositories in scheduler jobs: `WhatsAppRepository(pool)` for messaging, `CoreRepository(pool)` for booking data
- All existing tests must continue to pass

---

### Task 1: DB Migration 007 + CoreRepository Extension

**Files:**
- Create: `src/core/db/migrations/007_booking_standalone.sql`
- Modify: `src/core/db/repository.py`
- Modify: `tests/core/conftest.py` (load new migration)
- Create: `tests/core/test_repository_bookings_extended.py`

**Interfaces:**
- Produces: migration SQL, new repo methods `update_booking_payment()`, `list_bookings_by_stato()`, `list_bookings_for_reminder()`, `update_booking_reminder_status()`, `list_bookings_da_verificare()`, `upsert_booking_settings_config()`

- [ ] **Step 1: Create migration SQL**

```sql
-- src/core/db/migrations/007_booking_standalone.sql

ALTER TABLE bookings ADD COLUMN IF NOT EXISTS tipo_evento            TEXT NOT NULL DEFAULT '';
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS richiede_deposito      BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_link           TEXT NOT NULL DEFAULT '';
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_link_created_at TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_status         TEXT NOT NULL DEFAULT 'none'
    CHECK (payment_status IN ('none','pending','paid','refunded','expired'));
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_sent_at       TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_status        TEXT NOT NULL DEFAULT 'none'
    CHECK (reminder_status IN ('none','sent','confirmed','rejected','cancelled','flagged'));
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_responded_at  TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS completata_at          TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS no_show_at             TIMESTAMPTZ;

ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_stato_check;
ALTER TABLE bookings ADD CONSTRAINT bookings_stato_check
    CHECK (stato IN ('in_attesa','confermata','rifiutata','cancellata','no_show','completata','da_verificare'));

ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}';
```

- [ ] **Step 2: Add migration to test conftest**

In `tests/core/conftest.py`, inside the `pg_pool` fixture, after the `006_hitl.sql` line:

```python
with open("src/core/db/migrations/007_booking_standalone.sql") as f:
    await conn.execute(f.read())
```

- [ ] **Step 3: Write failing test for new repo methods**

```python
# tests/core/test_repository_bookings_extended.py
from datetime import date, time, datetime, timedelta, timezone
import uuid
import pytest


@pytest.mark.asyncio
async def test_update_booking_payment(repo, sample_org):
    created = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="Test",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=2,
    )
    updated = await repo.update_booking_payment(
        sample_org["id"], created["id"], "paid", session_id="cs_test_123"
    )
    assert updated["payment_status"] == "paid"
    fetched = await repo.get_booking(sample_org["id"], created["id"])
    assert fetched["payment_status"] == "paid"


@pytest.mark.asyncio
async def test_list_bookings_by_stato(repo, sample_org):
    b1 = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="A",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=2, stato="confermata")
    b2 = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="B",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=2, stato="in_attesa")
    confermate = await repo.list_bookings_by_stato(sample_org["id"], "confermata")
    assert len(confermate) == 1
    assert confermate[0]["id"] == b1["id"]


@pytest.mark.asyncio
async def test_list_bookings_for_reminder(repo, sample_org):
    tomorrow = date(2026, 8, 2)
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="A",
        data=tomorrow, ora=time(20, 0), coperti=2, stato="confermata")
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="B",
        data=tomorrow, ora=time(20, 0), coperti=2, stato="in_attesa")  # no reminder
    reminders = await repo.list_bookings_for_reminder(sample_org["id"], tomorrow)
    assert len(reminders) == 1
    assert reminders[0]["nome_cliente"] == "A"


@pytest.mark.asyncio
async def test_update_booking_reminder_status(repo, sample_org):
    created = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Test",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=2, stato="confermata")
    updated = await repo.update_booking_reminder_status(
        sample_org["id"], created["id"], "sent", datetime.now(timezone.utc)
    )
    assert updated["reminder_status"] == "sent"


@pytest.mark.asyncio
async def test_list_bookings_da_verificare(repo, sample_org):
    today = date(2026, 8, 1)
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="A",
        data=today, ora=time(20, 0), coperti=2, stato="confermata")
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="B",
        data=today, ora=time(20, 0), coperti=2, stato="completata",
        completata_at=datetime.now(timezone.utc))
    pending = await repo.list_bookings_da_verificare(sample_org["id"], today)
    assert len(pending) == 1
    assert pending[0]["nome_cliente"] == "A"


@pytest.mark.asyncio
async def test_upsert_booking_settings_config(repo, sample_org):
    config = {"deposito": {"enabled": True, "importo_default": 15.0}}
    result = await repo.upsert_booking_settings_config(sample_org["id"], config)
    assert result["config"]["deposito"]["enabled"] is True
    assert result["config"]["deposito"]["importo_default"] == 15.0
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/core/test_repository_bookings_extended.py -v`
Expected: FAIL (methods not defined)

- [ ] **Step 5: Implement repo methods**

Add to `CoreRepository` in `src/core/db/repository.py`:

```python
# ── Booking extensions ──────────────────────────────────────────

async def update_booking_payment(self, organization_id, booking_id,
                                  payment_status, session_id=None):
    async with self.pool.acquire() as conn:
        if session_id:
            row = await conn.fetchrow("""
                UPDATE bookings SET payment_status = $3, payment_link = $4,
                    payment_link_created_at = NOW(), updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, payment_status, session_id)
        else:
            row = await conn.fetchrow("""
                UPDATE bookings SET payment_status = $3, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, payment_status)
        return dict(row) if row else None

async def list_bookings_by_stato(self, organization_id, stato):
    async with self.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM bookings WHERE organization_id = $1 AND stato = $2 ORDER BY data, ora",
            organization_id, stato,
        )
        return [dict(r) for r in rows]

async def list_bookings_for_reminder(self, organization_id, target_date):
    async with self.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM bookings
            WHERE organization_id = $1 AND data = $2
              AND stato = 'confermata' AND reminder_status = 'none'
            ORDER BY ora
        """, organization_id, target_date)
        return [dict(r) for r in rows]

async def update_booking_reminder_status(self, organization_id, booking_id,
                                          reminder_status, responded_at=None):
    async with self.pool.acquire() as conn:
        if responded_at:
            row = await conn.fetchrow("""
                UPDATE bookings SET reminder_status = $3,
                    reminder_responded_at = $4, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, reminder_status, responded_at)
        else:
            row = await conn.fetchrow("""
                UPDATE bookings SET reminder_status = $3, updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, organization_id, booking_id, reminder_status)
        return dict(row) if row else None

async def list_bookings_da_verificare(self, organization_id, target_date):
    async with self.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM bookings
            WHERE organization_id = $1 AND data = $2
              AND stato = 'confermata'
              AND completata_at IS NULL AND no_show_at IS NULL
            ORDER BY ora
        """, organization_id, target_date)
        return [dict(r) for r in rows]

async def upsert_booking_settings_config(self, organization_id, config):
    async with self.pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO booking_settings (id, organization_id, config)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (organization_id) DO UPDATE
                SET config = $3::jsonb, updated_at = NOW()
            RETURNING *
        """, uuid.uuid4(), organization_id, json.dumps(config))
        result = dict(row)
        if isinstance(result.get("config"), str):
            result["config"] = json.loads(result["config"])
        return result
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/core/test_repository_bookings_extended.py -v`
Expected: 6 PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/db/migrations/007_booking_standalone.sql src/core/db/repository.py tests/core/conftest.py tests/core/test_repository_bookings_extended.py
git commit -m "feat(bookings): add migration 007 + repo methods for reminder/deposito/no-show"
```

---

### Task 2: BookingService — Core Availability + Lifecycle

**Files:**
- Create: `src/core/bookings/__init__.py`
- Create: `src/core/bookings/service.py`
- Create: `tests/core/bookings/__init__.py`
- Create: `tests/core/bookings/conftest.py` (shared fixtures)
- Create: `tests/core/bookings/test_booking_service.py`

**Interfaces:**
- Consumes: `CoreRepository` (from Task 1), `WhatsAppService`, `AppConfig`, `load_tenant_config()`
- Produces: `BookingService` with methods: `verifica_disponibilita()`, `semaforo_giorno()`, `prossimi_giorni_semaforo()`, `create_booking()`, `confirm()`, `reject()`, `cancel()`, `mark_no_show()`, `mark_completed()`

- [ ] **Step 0: Create shared fixtures for all booking tests**

```python
# tests/core/bookings/conftest.py
from datetime import datetime, timezone
import pytest


@pytest.fixture
async def settings(repo, sample_org):
    fasce = [f"{h:02d}:00" for h in range(24)]
    capienze = {f: 40 for f in fasce}
    return await repo.upsert_booking_settings(
        organization_id=sample_org["id"],
        fasce_orarie=fasce, capienze_orarie=capienze,
    )


@pytest.fixture
def booking_service(repo, sample_org, settings):
    from src.core.bookings.service import BookingService
    return BookingService(repo, None, None)


@pytest.fixture
def tomorrow():
    from datetime import date, timedelta
    return date.today() + timedelta(days=1)
```

- [ ] **Step 1: Write failing tests for availability logic**

```python
# tests/core/bookings/test_booking_service.py
from datetime import date, time
import uuid
import pytest

pytestmark = pytest.mark.asyncio


async def test_verifica_disponibilita_slot_libero(booking_service, sample_org):
    disp = await booking_service.verifica_disponibilita(
        sample_org["id"], "2026-08-01", "20:00"
    )
    assert disp.coperti_liberi == 40
    assert disp.stato == "verde"


async def test_verifica_disponibilita_esclude_cancellata(booking_service, repo, sample_org):
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="X",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=10, stato="cancellata")
    disp = await booking_service.verifica_disponibilita(
        sample_org["id"], "2026-08-01", "20:00"
    )
    assert disp.coperti_liberi == 40  # cancellata non occupa


async def test_verifica_disponibilita_esclude_no_show(booking_service, repo, sample_org):
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="X",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=10, stato="no_show")
    disp = await booking_service.verifica_disponibilita(
        sample_org["id"], "2026-08-01", "20:00"
    )
    assert disp.coperti_liberi == 40


async def test_verifica_disponibilita_include_completata(booking_service, repo, sample_org):
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="X",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=10, stato="completata",
        completata_at=datetime.now(timezone.utc))
    disp = await booking_service.verifica_disponibilita(
        sample_org["id"], "2026-08-01", "20:00"
    )
    assert disp.coperti_liberi == 30  # completata occupa ancora


async def test_semaforo_giorno_restituisce_slot(booking_service, sample_org):
    slots = await booking_service.semaforo_giorno(sample_org["id"], "2026-08-01")
    assert len(slots) == 24
    assert all(s.coperti_massimi == 40 for s in slots)


async def test_create_booking_success(booking_service, repo, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario", telefono="+393331234567",
        data="2026-08-01", ora="20:00", coperti=4,
    )
    assert b["stato"] == "in_attesa"
    assert b["nome_cliente"] == "Mario"


async def test_create_booking_slot_full(booking_service, repo, sample_org):
    # Occupa tutto lo slot
    for i in range(4):
        await repo.create_booking(organization_id=sample_org["id"], nome_cliente=f"G{i}",
            data=date(2026, 8, 1), ora=time(20, 0), coperti=10, stato="confermata")
    with pytest.raises(ValueError, match="slot pieno"):
        await booking_service.create_booking(
            sample_org["id"], nome_cliente="X",
            data="2026-08-01", ora="20:00", coperti=2,
        )


async def test_confirm_changes_stato(booking_service, repo, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario",
        data="2026-08-01", ora="20:00", coperti=4,
    )
    confirmed = await booking_service.confirm(sample_org["id"], b["id"])
    assert confirmed["stato"] == "confermata"


async def test_reject_changes_stato(booking_service, repo, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario",
        data="2026-08-01", ora="20:00", coperti=4,
    )
    rejected = await booking_service.reject(sample_org["id"], b["id"], "Siamo al completo")
    assert rejected["stato"] == "rifiutata"


async def test_reject_frees_capacity(booking_service, repo, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario",
        data="2026-08-01", ora="20:00", coperti=40,
    )
    await booking_service.reject(sample_org["id"], b["id"], "Completo")
    disp = await booking_service.verifica_disponibilita(
        sample_org["id"], "2026-08-01", "20:00"
    )
    assert disp.coperti_liberi == 40


async def test_mark_no_show(booking_service, repo, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario",
        data="2026-08-01", ora="20:00", coperti=4,
    )
    await booking_service.confirm(sample_org["id"], b["id"])
    ns = await booking_service.mark_no_show(sample_org["id"], b["id"])
    assert ns["stato"] == "no_show"
    assert ns["no_show_at"] is not None


async def test_mark_completed(booking_service, repo, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario",
        data="2026-08-01", ora="20:00", coperti=4,
    )
    await booking_service.confirm(sample_org["id"], b["id"])
    c = await booking_service.mark_completed(sample_org["id"], b["id"])
    assert c["stato"] == "completata"
    assert c["completata_at"] is not None


async def test_cross_tenant_isolation(booking_service, repo, sample_org, other_org):
    await booking_service.create_booking(
        sample_org["id"], nome_cliente="Org1",
        data="2026-08-01", ora="20:00", coperti=2,
    )
    disp_other = await booking_service.verifica_disponibilita(
        other_org["id"], "2026-08-01", "20:00"
    )
    assert disp_other.coperti_liberi == 40  # Org2 non vede prenotazioni Org1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/bookings/test_booking_service.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement BookingService — availability + lifecycle**

```python
# src/core/bookings/service.py
from datetime import datetime, date, timezone
import logging

logger = logging.getLogger(__name__)

STATI_OCCUPATI = {'in_attesa', 'confermata', 'da_verificare', 'completata'}
STATI_LIBERI = {'cancellata', 'cancellato', 'rifiutata', 'no_show'}
SLOT_ORE = [f"{h:02d}:00" for h in range(24)]


class BookingService:
    def __init__(self, repo, whatsapp_service=None, app_config=None):
        self.repo = repo
        self.whatsapp = whatsapp_service
        self.app_config = app_config

    async def _coperti_prenotati(self, org_id, data, ora):
        bookings = await self.repo.list_bookings(org_id, data)
        fascia = f"{int(ora[:2]):02d}:00"
        occupati = 0
        for b in bookings:
            if b["stato"] in STATI_LIBERI:
                continue
            ora_b = b["ora"]
            if isinstance(ora_b, time):
                ora_b = ora_b.strftime("%H:%M")
            b_fascia = f"{int(ora_b[:2]):02d}:00"
            if b_fascia == fascia:
                occupati += (b["coperti"] or 0)
        return occupati

    async def _get_capienze(self, org_id):
        settings = await self.repo.get_booking_settings(org_id)
        if settings and settings.get("capienze_orarie"):
            return settings["capienze_orarie"]
        return {f: 40 for f in SLOT_ORE}

    async def verifica_disponibilita(self, org_id, data, ora, coperti=None):
        from src.models.schemas import DisponibilitaSlot
        prenotati = await self._coperti_prenotati(org_id, data, ora)
        fascia = f"{int(ora[:2]):02d}:00"
        capienze = await self._get_capienze(org_id)
        massimi = capienze.get(fascia, 40)
        liberi = max(massimi - prenotati, 0)
        alternative = []
        if coperti and coperti > liberi:
            alternative = [
                f for f in SLOT_ORE
                if f != fascia and (capienze.get(f, 0) - await self._coperti_prenotati(org_id, data, f)) >= coperti
            ][:2]
        if liberi <= 0:
            stato = "rosso"
        elif liberi <= max(4, round(massimi * 0.2)):
            stato = "giallo"
        else:
            stato = "verde"
        return DisponibilitaSlot(
            data=data, ora=ora,
            coperti_massimi=massimi, coperti_prenotati=prenotati,
            coperti_liberi=liberi, stato=stato, alternative=alternative,
        )

    async def semaforo_giorno(self, org_id, data):
        capienze = await self._get_capienze(org_id)
        bookings = await self.repo.list_bookings(org_id, data)
        slots = []
        for fascia in SLOT_ORE:
            if capienze.get(fascia, 0) <= 0:
                continue
            prenotati = 0
            for b in bookings:
                if b["stato"] in STATI_LIBERI:
                    continue
                ora_b = b["ora"]
                if isinstance(ora_b, time):
                    ora_b = ora_b.strftime("%H:%M")
                b_fascia = f"{int(ora_b[:2]):02d}:00"
                if b_fascia == fascia:
                    prenotati += (b["coperti"] or 0)
            massimi = capienze[fascia]
            liberi = max(massimi - prenotati, 0)
            if liberi <= 0:
                stato = "rosso"
            elif liberi <= max(4, round(massimi * 0.2)):
                stato = "giallo"
            else:
                stato = "verde"
            slots.append(DisponibilitaSlot(
                data=data, ora=fascia,
                coperti_massimi=massimi, coperti_prenotati=prenotati,
                coperti_liberi=liberi, stato=stato, alternative=[],
            ))
        return slots

    async def prossimi_giorni_semaforo(self, org_id, giorni=7):
        from datetime import timedelta
        oggi = datetime.now().date()
        slots = []
        for offset in range(giorni):
            giorno = (oggi + timedelta(days=offset)).strftime("%Y-%m-%d")
            slots.extend(await self.semaforo_giorno(org_id, giorno))
        return slots

    async def create_booking(self, org_id, nome_cliente, data, ora, coperti,
                              telefono="", note="", tipo_evento="", origine="Dashboard"):
        disp = await self.verifica_disponibilita(org_id, data, ora, coperti)
        if coperti > disp.coperti_liberi:
            raise ValueError(f"slot pieno per {coperti} coperti alle {ora}")
        return await self.repo.create_booking(
            organization_id=org_id, nome_cliente=nome_cliente,
            telefono=telefono, data=data, ora=ora, coperti=coperti,
            note=note, stato="in_attesa", origine=origine,
        )

    async def _get_booking_or_raise(self, org_id, booking_id):
        b = await self.repo.get_booking(org_id, booking_id)
        if not b:
            raise ValueError(f"booking {booking_id} non trovato")
        return b

    async def _load_tenant_config(self, org_id):
        if not self.app_config or not self.whatsapp:
            return None
        from src.whatsapp.config import load_tenant_config
        return await load_tenant_config(org_id, self.app_config, self.whatsapp.repo)

    async def _send_whatsapp(self, org_id, to_number, text, category="service"):
        if not self.whatsapp or not to_number:
            return
        tenant = await self._load_tenant_config(org_id)
        if not tenant:
            return
        try:
            await self.whatsapp.send_whatsapp_message(
                org_id=org_id, to_number=to_number,
                payload={"to": to_number, "type": "text", "text": {"body": text}},
                category=category, meta_client=None, tenant_config=tenant,
            )
        except Exception as e:
            logger.error("WhatsApp send failed for org %s: %s", org_id, e)

    async def confirm(self, org_id, booking_id):
        b = await self._get_booking_or_raise(org_id, booking_id)
        updated = await self.repo.update_booking_status(org_id, booking_id, "confermata")
        msg = f"La tua prenotazione del {b['data']} alle {b['ora']} per {b['coperti']} persone e' confermata!"
        await self._send_whatsapp(org_id, b["telefono"], msg)
        return updated

    async def reject(self, org_id, booking_id, motivo=""):
        b = await self._get_booking_or_raise(org_id, booking_id)
        updated = await self.repo.update_booking_status(org_id, booking_id, "rifiutata")
        msg = f"La tua prenotazione del {b['data']} alle {b['ora']} non puo' essere confermata."
        if motivo:
            msg += f" Motivo: {motivo}"
        await self._send_whatsapp(org_id, b["telefono"], msg)
        return updated

    async def cancel(self, org_id, booking_id):
        return await self.repo.update_booking_status(org_id, booking_id, "cancellata")

    async def mark_no_show(self, org_id, booking_id):
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = 'no_show', no_show_at = NOW(), updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, org_id, booking_id)
            return dict(row) if row else None

    async def mark_completed(self, org_id, booking_id):
        async with self.repo.pool.acquire() as conn:
            row = await conn.fetchrow("""
                UPDATE bookings SET stato = 'completata', completata_at = NOW(), updated_at = NOW()
                WHERE organization_id = $1 AND id = $2
                RETURNING *
            """, org_id, booking_id)
            return dict(row) if row else None

    async def aggiorna_impostazioni(self, org_id, capienze_orarie=None,
                                     coperti_massimi=40, fasce_orarie=None, config=None):
        if capienze_orarie is None and fasce_orarie is None:
            return await self.repo.upsert_booking_settings_config(org_id, config or {})
        if config:
            current = await self.repo.get_booking_settings(org_id)
            merged = dict(current.get("config") or {}) if current else {}
            merged.update(config)
            await self.repo.upsert_booking_settings_config(org_id, merged)
        if capienze_orarie is not None or fasce_orarie is not None:
            await self.repo.upsert_booking_settings(
                org_id,
                fasce_orarie=fasce_orarie or [f"{h:02d}:00" for h in range(24)],
                capienze_orarie=capienze_orarie or {f: coperti_massimi for f in SLOT_ORE},
            )
        return await self.repo.get_booking_settings(org_id)
```

```python
# src/core/bookings/__init__.py
from src.core.bookings.service import BookingService

__all__ = ["BookingService"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/bookings/test_booking_service.py -v`
Expected: 12 PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/bookings/ tests/core/bookings/
git commit -m "feat(bookings): BookingService with availability + lifecycle (confirm/reject/no-show/completed)"
```

---

### Task 3: BookingService — Reminder Reply Hook

**Files:**
- Modify: `src/core/bookings/service.py`
- Create: `tests/core/bookings/test_reminder_reply.py`

**Interfaces:**
- Consumes: `CoreRepository` (reminder methods from Task 1)
- Produces: `BookingService.handle_reminder_reply()` — returns `str | None`

- [ ] **Step 1: Write failing tests for reminder reply**

```python
# tests/core/bookings/test_reminder_reply.py
from datetime import date, time, datetime, timezone
import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def confirmed_booking(repo, sample_org):
    b = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="Mario",
        telefono="+393331234567", data=date(2026, 8, 2), ora=time(20, 0),
        coperti=4, stato="confermata",
    )
    await repo.update_booking_reminder_status(
        sample_org["id"], b["id"], "sent",
    )
    return await repo.get_booking(sample_org["id"], b["id"])


async def test_reminder_reply_confirm(booking_service, sample_org, confirmed_booking):
    result = await booking_service.handle_reminder_reply(
        sample_org["id"], "+393331234567", "Si confermo"
    )
    assert result is not None
    updated = await booking_service.repo.get_booking(sample_org["id"], confirmed_booking["id"])
    assert updated["reminder_status"] == "confirmed"


async def test_reminder_reply_reject(booking_service, sample_org, confirmed_booking):
    result = await booking_service.handle_reminder_reply(
        sample_org["id"], "+393331234567", "No annulla"
    )
    assert result is not None
    updated = await booking_service.repo.get_booking(sample_org["id"], confirmed_booking["id"])
    assert updated["reminder_status"] == "rejected"
    assert updated["stato"] == "cancellata"


async def test_reminder_reply_ambiguous(booking_service, sample_org, confirmed_booking):
    result = await booking_service.handle_reminder_reply(
        sample_org["id"], "+393331234567", "Forse non so"
    )
    assert result is not None
    updated = await booking_service.repo.get_booking(sample_org["id"], confirmed_booking["id"])
    assert updated["reminder_status"] == "flagged"


async def test_reminder_reply_no_pending(booking_service, sample_org, confirmed_booking):
    result = await booking_service.handle_reminder_reply(
        sample_org["id"], "+393331234568", "Si confermo"
    )
    assert result is None  # numero diverso, nessun reminder pendente


async def test_reminder_reply_wrong_org(booking_service, sample_org, other_org, confirmed_booking):
    result = await booking_service.handle_reminder_reply(
        other_org["id"], "+393331234567", "Si confermo"
    )
    assert result is None  # altro org, nessun reminder pendente
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/bookings/test_reminder_reply.py -v`
Expected: FAIL (handle_reminder_reply not defined)

- [ ] **Step 3: Implement handle_reminder_reply**

Add to `BookingService` in `service.py`:

```python
    REMINDER_CONFIRM_KEYWORDS = {"si", "confermo", "conferma", "ok", "okay", "certo", "sicuro"}
    REMINDER_REJECT_KEYWORDS = {"no", "annulla", "cancella", "non vengo", "non posso"}

    async def handle_reminder_reply(self, org_id, from_number, text):
        bookings = await self.repo.list_bookings_by_stato(org_id, "confermata")
        pending = [
            b for b in bookings
            if b.get("reminder_status") == "sent"
               and b.get("telefono", "").strip() == from_number.strip()
        ]
        if not pending:
            return None
        b = pending[0]
        text_lower = text.lower().strip()
        confirmed = any(kw in text_lower for kw in self.REMINDER_CONFIRM_KEYWORDS)
        rejected = any(kw in text_lower for kw in self.REMINDER_REJECT_KEYWORDS)
        if confirmed and not rejected:
            await self.repo.update_booking_reminder_status(
                org_id, b["id"], "confirmed", datetime.now(timezone.utc)
            )
            await self._send_whatsapp(org_id, from_number,
                "Grazie, la tua prenotazione e' confermata! Ti aspettiamo.")
            return "confirmed"
        elif rejected:
            await self.repo.update_booking_status(org_id, b["id"], "cancellata")
            await self.repo.update_booking_reminder_status(
                org_id, b["id"], "rejected", datetime.now(timezone.utc)
            )
            await self._send_whatsapp(org_id, from_number,
                "Prenotazione cancellata. Per qualsiasi altra richiesta, siamo a disposizione.")
            return "rejected"
        else:
            await self.repo.update_booking_reminder_status(
                org_id, b["id"], "flagged", datetime.now(timezone.utc)
            )
            return "flagged"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/bookings/test_reminder_reply.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/bookings/service.py tests/core/bookings/test_reminder_reply.py
git commit -m "feat(bookings): handle_reminder_reply with keyword matching + HITL flag for ambiguous"
```

---

### Task 4: BookingService — Deposito/Stripe Payment Links

**Files:**
- Modify: `src/core/bookings/service.py`
- Create: `tests/core/bookings/test_deposito.py`

**Interfaces:**
- Consumes: `CoreRepository` (settings config + payment methods from Task 1), `stripe` library
- Produces: `BookingService._valuta_richiede_deposito()`, `BookingService._genera_payment_link()`, deposit logic in `confirm()`

- [ ] **Step 1: Write failing tests for deposito**

```python
# tests/core/bookings/test_deposito.py
from datetime import date, time
import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.asyncio


async def _setup_deposito_settings(repo, sample_org, config_overrides=None):
    config = {
        "deposito": {
            "enabled": True,
            "importo_default": 10.00,
            "valuta": "EUR",
            "criteri": {
                "coperti_min": 6,
                "tipi_evento": ["evento_speciale", "cena_di_gala"],
                "fasce": ["20:00", "21:00"],
                "date": ["2026-12-31"],
            },
        }
    }
    if config_overrides:
        deep_update(config, config_overrides)
    await repo.upsert_booking_settings_config(sample_org["id"], config)


def deep_update(d, u):
    for k, v in u.items():
        if isinstance(v, dict) and k in d and isinstance(d[k], dict):
            deep_update(d[k], v)
        else:
            d[k] = v


async def test_deposito_disabled(booking_service, repo, sample_org):
    config = {"deposito": {"enabled": False}}
    await repo.upsert_booking_settings_config(sample_org["id"], config)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=10, tipo_evento="normale", ora="20:00", data="2026-08-15"
    )
    assert result is False


async def test_deposito_matcha_coperti_min(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=6, tipo_evento="", ora="12:00", data="2026-08-15"
    )
    assert result is True


async def test_deposito_non_matcha_coperti_sotto_soglia(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=4, tipo_evento="", ora="12:00", data="2026-08-15"
    )
    assert result is False


async def test_deposito_matcha_tipo_evento(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=2, tipo_evento="cena_di_gala", ora="12:00", data="2026-08-15"
    )
    assert result is True


async def test_deposito_matcha_fascia_oraria(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=2, tipo_evento="", ora="20:30", data="2026-08-15"
    )
    assert result is True  # 20:30 rientra in fascia 20:00


async def test_deposito_matcha_data(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    result = await booking_service._valuta_richiede_deposito(
        sample_org["id"], coperti=2, tipo_evento="", ora="12:00", data="2026-12-31"
    )
    assert result is True


async def test_deposito_genera_payment_link(booking_service, repo, sample_org):
    await _setup_deposito_settings(repo, sample_org)
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario", telefono="+393331234567",
        data="2026-08-01", ora="20:00", coperti=8,
    )
    with patch("stripe.PaymentLink.create") as mock_create:
        mock_create.return_value = type("obj", (), {"url": "https://pay.stripe.com/test_123"})()
        confirmed = await booking_service.confirm(sample_org["id"], b["id"])
    assert confirmed["payment_status"] == "pending"
    assert confirmed["payment_link"] == "https://pay.stripe.com/test_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/bookings/test_deposito.py -v`
Expected: FAIL (_valuta_richiede_deposito not defined)

- [ ] **Step 3: Implement deposito logic**

Add to `BookingService`:

```python
    async def _get_deposito_config(self, org_id):
        settings = await self.repo.get_booking_settings(org_id)
        if not settings:
            return None
        config = settings.get("config") or {}
        return config.get("deposito")

    async def _valuta_richiede_deposito(self, org_id, coperti=0, tipo_evento="", ora="", data=""):
        cfg = await self._get_deposito_config(org_id)
        if not cfg or not cfg.get("enabled"):
            return False
        criteri = cfg.get("criteri") or {}
        coperti_min = criteri.get("coperti_min")
        if coperti_min is not None and coperti >= coperti_min:
            return True
        tipi = criteri.get("tipi_evento") or []
        if tipo_evento and tipo_evento in tipi:
            return True
        fasce = criteri.get("fasce") or []
        ora_fascia = f"{int(ora[:2]):02d}:00"
        if ora_fascia in fasce:
            return True
        date_specifiche = criteri.get("date") or []
        if data in date_specifiche:
            return True
        return False

    async def _genera_payment_link(self, org_id, booking_id, importo, valuta="EUR"):
        import stripe
        link = stripe.PaymentLink.create(
            line_items=[{
                "price_data": {
                    "unit_amount": int(round(importo * 100)),
                    "currency": valuta.lower(),
                    "product_data": {"name": "Deposito prenotazione"},
                },
                "quantity": 1,
            }],
            metadata={"booking_id": str(booking_id), "organization_id": str(org_id)},
            after_completion={"type": "redirect", "redirect": {"url": ""}},
        )
        return link.url
```

Modify `create_booking` to call `_valuta_richiede_deposito`:

In the `create_booking` method, after creating the booking:

```python
        dep = await self._valuta_richiede_deposito(
            org_id, coperti=coperti, tipo_evento=tipo_evento, ora=ora, data=data
        )
        if dep:
            async with self.repo.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE bookings SET richiede_deposito = TRUE WHERE id = $1
                """, created["id"])
```

Modify `confirm` to generate payment link if `richiede_deposito`:

In the `confirm` method, after confirming:

```python
        if b.get("richiede_deposito"):
            cfg = await self._get_deposito_config(org_id)
            importo = (cfg or {}).get("importo_default", 10.0)
            valuta = (cfg or {}).get("valuta", "EUR")
            try:
                link = await self._genera_payment_link(org_id, booking_id, importo, valuta)
                async with self.repo.pool.acquire() as conn:
                    await conn.execute("""
                        UPDATE bookings SET payment_link = $3,
                            payment_link_created_at = NOW(), payment_status = 'pending'
                        WHERE organization_id = $1 AND id = $2
                    """, org_id, booking_id, link)
                updated["payment_link"] = link
                updated["payment_status"] = "pending"
                await self._send_whatsapp(org_id, b["telefono"],
                    f"Per confermare, versa il deposito di {valuta} {importo:.2f}: {link}")
            except Exception as e:
                logger.error("Failed to generate payment link for booking %s: %s", booking_id, e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/bookings/test_deposito.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/bookings/service.py tests/core/bookings/test_deposito.py
git commit -m "feat(bookings): deposit criteria evaluation + Stripe Payment Link generation"
```

---

### Task 5: Booking API Routes

**Files:**
- Create: `src/core/bookings/routes.py`
- Modify: `src/api/main.py` (mount router)
- Create: `tests/core/bookings/test_routes.py`

**Interfaces:**
- Consumes: `BookingService` from Tasks 2-4, `require_ruolo` auth middleware
- Produces: FastAPI router mounted at `/api/bookings` with correct route order

- [ ] **Step 1: Write failing tests for routes**

```python
# tests/core/bookings/test_routes.py
from datetime import date
import pytest
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from src.core.auth.dependencies import require_ruolo
from unittest.mock import AsyncMock, MagicMock

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(booking_service):
    app = FastAPI()
    from src.core.bookings.routes import router
    app.include_router(router)
    return app


@pytest.fixture
def override_auth():
    # Skippa auth per test
    return {"sub": "test-user", "organization_id": str(sample_org["id"]), "ruolo": "owner"}


async def test_route_semaforo_before_id(app, sample_org):
    # GET /api/bookings/semaforo non deve matchare come {id}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/bookings/semaforo?data=2026-08-01")
    assert resp.status_code in (200, 401)  # se auth skipper, 200


async def test_route_static_order(app, sample_org):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/bookings/settings")
    assert resp.status_code != 404  # non deve matchare come {id}


async def test_route_create_booking(app, sample_org):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/bookings", json={
            "nome_cliente": "Mario", "telefono": "+393331234567",
            "data": "2026-08-01", "ora": "20:00", "coperti": 4,
        })
    assert resp.status_code in (200, 201, 401)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/bookings/test_routes.py -v`
Expected: FAIL (routes module not found)

- [ ] **Step 3: Implement booking routes**

```python
# src/core/bookings/routes.py
from fastapi import APIRouter, Depends, HTTPException
from src.core.auth.dependencies import require_ruolo
from src.models.schemas import DisponibilitaSlot

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


def _get_booking_service(request):
    return request.app.state.booking_service


@router.get("/semaforo", response_model=list[DisponibilitaSlot])
async def semaforo(data: str | None = None,
                   user: dict = Depends(require_ruolo("owner", "manager", "staff")),
                   service=Depends(_get_booking_service)):
    org_id = user["organization_id"]
    if data:
        return await service.semaforo_giorno(org_id, data)
    return await service.prossimi_giorni_semaforo(org_id)


@router.get("/settings")
async def get_settings(user: dict = Depends(require_ruolo("owner", "manager")),
                       service=Depends(_get_booking_service)):
    return await service.repo.get_booking_settings(user["organization_id"])


@router.put("/settings")
async def update_settings(body: dict,
                          user: dict = Depends(require_ruolo("owner", "manager")),
                          service=Depends(_get_booking_service)):
    return await service.aggiorna_impostazioni(
        user["organization_id"],
        capienze_orarie=body.get("capienze_orarie"),
        config=body.get("config"),
    )


@router.get("")
async def list_bookings(data: str | None = None,
                        user: dict = Depends(require_ruolo("owner", "manager", "staff")),
                        service=Depends(_get_booking_service)):
    return await service.repo.list_bookings(user["organization_id"], data)


@router.post("")
async def create_booking(body: dict,
                         user: dict = Depends(require_ruolo("owner", "manager")),
                         service=Depends(_get_booking_service)):
    try:
        b = await service.create_booking(
            org_id=user["organization_id"],
            nome_cliente=body["nome_cliente"],
            telefono=body.get("telefono", ""),
            data=body["data"],
            ora=body["ora"],
            coperti=body["coperti"],
            note=body.get("note", ""),
            tipo_evento=body.get("tipo_evento", ""),
            origine=body.get("origine", "Dashboard"),
        )
        return b
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/{booking_id}")
async def get_booking(booking_id: str,
                      user: dict = Depends(require_ruolo("owner", "manager", "staff")),
                      service=Depends(_get_booking_service)):
    b = await service.repo.get_booking(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


@router.post("/{booking_id}/confirm")
async def confirm_booking(booking_id: str,
                          user: dict = Depends(require_ruolo("owner", "manager")),
                          service=Depends(_get_booking_service)):
    try:
        return await service.confirm(user["organization_id"], booking_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{booking_id}/reject")
async def reject_booking(booking_id: str, body: dict = {},
                         user: dict = Depends(require_ruolo("owner", "manager")),
                         service=Depends(_get_booking_service)):
    try:
        return await service.reject(user["organization_id"], booking_id, body.get("motivo", ""))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{booking_id}/cancel")
async def cancel_booking(booking_id: str,
                         user: dict = Depends(require_ruolo("owner", "manager")),
                         service=Depends(_get_booking_service)):
    b = await service.cancel(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


@router.post("/{booking_id}/mark-no-show")
async def mark_no_show(booking_id: str,
                       user: dict = Depends(require_ruolo("owner", "manager")),
                       service=Depends(_get_booking_service)):
    b = await service.mark_no_show(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b


@router.post("/{booking_id}/mark-completed")
async def mark_completed(booking_id: str,
                         user: dict = Depends(require_ruolo("owner", "manager")),
                         service=Depends(_get_booking_service)):
    b = await service.mark_completed(user["organization_id"], booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    return b
```

Mount router in `src/api/main.py` in the `lifespan` function (after `app.state.repo` is set):

```python
    if pool:
        from src.core.bookings import BookingService
        core_repo = CoreRepository(pool=pool)
        app.state.booking_service = BookingService(core_repo)
```

And include the router:

```python
from src.core.bookings.routes import router as bookings_router
app.include_router(bookings_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/bookings/test_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/bookings/routes.py src/api/main.py tests/core/bookings/test_routes.py
git commit -m "feat(bookings): API routes with correct order (static before {id}) + mount in main.py"
```

---

### Task 6: Reminder Hook in InboundProcessor

**Files:**
- Modify: `src/whatsapp/inbound_processor.py`
- Create: `tests/whatsapp/test_reminder_inbound.py`

**Interfaces:**
- Consumes: `BookingService` from Tasks 2-3
- Produces: reminder reply hook in `_process_one()`, between opt-out and fast_path_match

- [ ] **Step 1: Write failing test for pipeline position**

```python
# tests/whatsapp/test_reminder_inbound.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_booking_service():
    svc = MagicMock()
    svc.handle_reminder_reply = AsyncMock(return_value=None)
    return svc


@pytest.fixture
def processor(app_config, repo, mock_booking_service):
    from src.whatsapp.inbound_processor import InboundProcessor
    proc = InboundProcessor(app_config, repo, AsyncMock())
    proc.booking_service = mock_booking_service
    return proc


async def test_reminder_hook_called_after_opt_out(processor, mock_booking_service):
    """Il reminder hook viene chiamato dopo opt-out, prima dell'AI."""
    msg = {
        "organization_id": str(processor.repo.pool),
        "content_text": "Si confermo",
        "content": {"from": "+393331234567"},
        "conversation_id": "conv-1",
        "id": "msg-1",
    }
    # Mock check_opt_out = False
    processor.service.check_opt_out = AsyncMock(return_value={"is_opt_out": False})
    processor.service.fast_path_match = AsyncMock(return_value=None)
    mock_booking_service.handle_reminder_reply.return_value = "confirmed"
    await processor._process_one(msg)
    mock_booking_service.handle_reminder_reply.assert_called_once()


async def test_opt_out_wins_over_reminder(processor, mock_booking_service):
    """Opt-out check viene PRIMA del reminder hook."""
    msg = {
        "organization_id": str(processor.repo.pool),
        "content_text": "stop",
        "content": {"from": "+393331234567"},
        "conversation_id": "conv-1",
        "id": "msg-1",
    }
    processor.service.check_opt_out = AsyncMock(return_value={"is_opt_out": True})
    processor.service.fast_path_match = AsyncMock(return_value=None)
    await processor._process_one(msg)
    mock_booking_service.handle_reminder_reply.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/whatsapp/test_reminder_inbound.py -v`
Expected: FAIL (processor has no booking_service)

- [ ] **Step 3: Implement the hook**

In `src/whatsapp/inbound_processor.py`, modify `__init__` to accept `booking_service`:

```python
    def __init__(self, app_config: AppConfig, repo, service, booking_service=None):
        self.app_config = app_config
        self.repo = repo
        self.service = service
        self.booking_service = booking_service
```

In `_process_one`, after opt-out check and before `fast_path_match`:

```python
        # Pipeline: 1) opt-out (GDPR)  2) reminder reply  3) fast_path  4) AI responder

        # ... existing opt-out check ...

        # Reminder reply hook
        if self.booking_service:
            booking_reply = await self.booking_service.handle_reminder_reply(
                org_id, content.get("from", ""), text
            )
            if booking_reply:
                await self.repo.update_message_status(msg["id"], "handled")
                return

        # ... existing fast_path_match and AI responder ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/whatsapp/test_reminder_inbound.py -v`
Expected: 2 PASS

- [ ] **Step 5: Wire booking_service when processor is created**

Find where `InboundProcessor` is instantiated (likely in the whatsapp router) and pass `booking_service`.

Run: `pytest tests/whatsapp/ -v`
Expected: all existing WhatsApp tests still pass

- [ ] **Step 6: Commit**

```bash
git add src/whatsapp/inbound_processor.py tests/whatsapp/test_reminder_inbound.py
git commit -m "feat(bookings): reminder reply hook in inbound_processor pipeline (opt-out -> reminder -> AI)"
```

---

### Task 7: Scheduler Jobs — Reminder + No-Show

**Files:**
- Create: `src/core/bookings/reminder_job.py`
- Create: `src/core/bookings/no_show_job.py`
- Modify: `src/core/scheduler.py`
- Create: `tests/core/bookings/test_reminder_job.py`

**Interfaces:**
- Consumes: `CoreRepository`, `WhatsAppRepository`, `WhatsAppService`, `AppConfig`, `BookingService`
- Produces: 3 cron jobs registered in `avvia_scheduler()`: reminder_check (every 30min), reminder_timeout (every 30min), no_show (23:30 daily)

- [ ] **Step 1: Write failing tests for reminder job logic**

```python
# tests/core/bookings/test_reminder_job.py
from datetime import date, time, datetime, timedelta, timezone
import pytest

pytestmark = pytest.mark.asyncio


async def test_send_reminders_sends_for_tomorrow(booking_service, repo, sample_org, settings):
    tomorrow = date.today() + timedelta(days=1)
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        telefono="+393331234567", data=tomorrow, ora=time(20, 0), coperti=4, stato="confermata")
    from src.core.bookings.reminder_job import send_reminders_for_org
    sent = await send_reminders_for_org(booking_service, sample_org["id"])
    assert len(sent) == 1
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["reminder_status"] == "sent"
    assert updated["reminder_sent_at"] is not None


async def test_send_reminders_skips_in_attesa(booking_service, repo, sample_org, settings):
    tomorrow = date.today() + timedelta(days=1)
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=tomorrow, ora=time(20, 0), coperti=4, stato="in_attesa")
    from src.core.bookings.reminder_job import send_reminders_for_org
    sent = await send_reminders_for_org(booking_service, sample_org["id"])
    assert len(sent) == 0


async def test_reminder_timeout_flags_no_reply(booking_service, repo, sample_org, settings):
    yesterday = datetime.now(timezone.utc) - timedelta(hours=13)
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        telefono="+393331234567", data=date.today(), ora=time(20, 0), coperti=4, stato="confermata")
    await repo.update_booking_reminder_status(sample_org["id"], b["id"], "sent")
    # Force reminder_sent_at to 13h ago
    async with repo.pool.acquire() as conn:
        await conn.execute("""
            UPDATE bookings SET reminder_sent_at = $3 WHERE id = $1 AND organization_id = $2
        """, b["id"], sample_org["id"], yesterday)
    from src.core.bookings.reminder_job import check_timeouts_for_org
    flagged = await check_timeouts_for_org(booking_service, sample_org["id"])
    assert len(flagged) == 1
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["reminder_status"] == "flagged"


async def test_no_show_job_marks_da_verificare(booking_service, repo, sample_org, settings):
    today = date.today()
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=today, ora=time(20, 0), coperti=4, stato="confermata")
    from src.core.bookings.no_show_job import mark_da_verificare_for_org
    marked = await mark_da_verificare_for_org(booking_service, sample_org["id"])
    assert len(marked) == 1
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["stato"] == "da_verificare"


async def test_no_show_job_skips_completata(booking_service, repo, sample_org, settings):
    today = date.today()
    await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=today, ora=time(20, 0), coperti=4, stato="completata",
        completata_at=datetime.now(timezone.utc))
    from src.core.bookings.no_show_job import mark_da_verificare_for_org
    marked = await mark_da_verificare_for_org(booking_service, sample_org["id"])
    assert len(marked) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/bookings/test_reminder_job.py -v`
Expected: FAIL (modules not found)

- [ ] **Step 3: Implement reminder job**

```python
# src/core/bookings/reminder_job.py
from datetime import datetime, timedelta, timezone, date
import logging

logger = logging.getLogger(__name__)

TIMEOUT_HOURS = 12


async def send_reminders_for_org(service, org_id):
    tomorrow = date.today() + timedelta(days=1)
    bookings = await service.repo.list_bookings_for_reminder(org_id, tomorrow)
    sent = []
    for b in bookings:
        try:
            await service.repo.update_booking_reminder_status(
                org_id, b["id"], "sent",
            )
            async with service.repo.pool.acquire() as conn:
                await conn.execute("""
                    UPDATE bookings SET reminder_sent_at = NOW() WHERE id = $1
                """, b["id"])
            msg = (f"Ciao {b['nome_cliente']}! Confermi la prenotazione di domani "
                   f"alle {b['ora']} per {b['coperti']} persone? "
                   f"Rispondi 'Si' per confermare o 'No' per annullare.")
            await service._send_whatsapp(org_id, b["telefono"], msg)
            sent.append(b)
        except Exception as e:
            logger.error("Reminder failed for booking %s: %s", b["id"], e)
    return sent


async def check_timeouts_for_org(service, org_id):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TIMEOUT_HOURS)
    async with service.repo.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM bookings
            WHERE organization_id = $1
              AND reminder_status = 'sent'
              AND reminder_sent_at <= $2
              AND data >= $3::date
        """, org_id, cutoff, date.today())
    flagged = []
    for b in rows:
        try:
            await service.repo.update_booking_reminder_status(
                org_id, b["id"], "flagged", datetime.now(timezone.utc)
            )
            flagged.append(b)
        except Exception as e:
            logger.error("Timeout check failed for booking %s: %s", b["id"], e)
    return flagged
```

```python
# src/core/bookings/no_show_job.py
from datetime import date
import logging

logger = logging.getLogger(__name__)


async def mark_da_verificare_for_org(service, org_id):
    today = date.today()
    bookings = await service.repo.list_bookings_da_verificare(org_id, today)
    marked = []
    for b in bookings:
        try:
            await service.repo.update_booking_status(org_id, b["id"], "da_verificare")
            marked.append(b)
        except Exception as e:
            logger.error("No-show check failed for booking %s: %s", b["id"], e)
    return marked
```

- [ ] **Step 4: Register jobs in scheduler.py**

In `src/core/scheduler.py`, add new `_run_*` functions and register them in `avvia_scheduler()`:

```python
def _run_reminder_check():
    pool = _pool()
    app_config = _get_app_config()
    asyncio.run(_reminder_check_job(pool, app_config))


async def _reminder_check_job(pool, app_config):
    from src.core.bookings import BookingService
    from src.core.bookings.reminder_job import send_reminders_for_org
    from src.whatsapp.repository import Repository as WhatsAppRepository
    from src.whatsapp.service import WhatsAppService
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        wrepo = WhatsAppRepository(pool)
        core_repo = CoreRepository(pool)
        whatsapp = WhatsAppService(app_config, wrepo)
        service = BookingService(core_repo, whatsapp, app_config)
        await send_reminders_for_org(service, org["id"])


def _run_reminder_timeout():
    pool = _pool()
    app_config = _get_app_config()
    asyncio.run(_reminder_timeout_job(pool, app_config))


async def _reminder_timeout_job(pool, app_config):
    from src.core.bookings import BookingService
    from src.core.bookings.reminder_job import check_timeouts_for_org
    from src.whatsapp.repository import Repository as WhatsAppRepository
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        core_repo = CoreRepository(pool)
        service = BookingService(core_repo)
        await check_timeouts_for_org(service, org["id"])


def _run_no_show_check():
    pool = _pool()
    app_config = _get_app_config()
    asyncio.run(_no_show_check_job(pool, app_config))


async def _no_show_check_job(pool, app_config):
    from src.core.bookings import BookingService
    from src.core.bookings.no_show_job import mark_da_verificare_for_org
    from src.core.db.repository import CoreRepository
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        core_repo = CoreRepository(pool)
        service = BookingService(core_repo)
        await mark_da_verificare_for_org(service, org["id"])
```

In `avvia_scheduler()`:

```python
    _scheduler.add_job(
        _run_reminder_check,
        CronTrigger(minute="*/30"),
        id="booking_reminder_send",
        name="Invia reminder prenotazioni 24h prima",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_reminder_timeout,
        CronTrigger(minute="*/30"),
        id="booking_reminder_timeout",
        name="Flagga reminder senza risposta dopo 12h",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_no_show_check,
        CronTrigger(hour=23, minute=30),
        id="booking_no_show",
        name="Marca da_verificare prenotazioni non completate",
        replace_existing=True,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/core/bookings/test_reminder_job.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/bookings/reminder_job.py src/core/bookings/no_show_job.py src/core/scheduler.py tests/core/bookings/test_reminder_job.py
git commit -m "feat(bookings): scheduler jobs for reminder send, reminder timeout, and no-show end-of-day"
```

---

### Task 8: Webhook Stripe — Payment Mode for Booking Deposits

**Files:**
- Modify: `src/core/billing/webhook_handler.py`
- Create: `tests/core/billing/test_webhook_deposito.py`

**Interfaces:**
- Consumes: `CoreRepository` (payment methods from Task 1)
- Produces: `checkout.session.completed` handler with `mode = payment` → booking deposit logic

- [ ] **Step 1: Write failing test for payment mode routing**

```python
# tests/core/billing/test_webhook_deposito.py
from datetime import date, time
import pytest
from unittest.mock import AsyncMock, patch

pytestmark = pytest.mark.asyncio


async def test_webhook_payment_mode_updates_booking(repo, sample_org):
    b = await repo.create_booking(organization_id=sample_org["id"], nome_cliente="Mario",
        data=date(2026, 8, 1), ora=time(20, 0), coperti=4, richiede_deposito=True,
        payment_status="pending")
    # Simula evento Stripe checkout.session.completed con mode=payment
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "payment",
                "metadata": {
                    "booking_id": str(b["id"]),
                    "organization_id": str(sample_org["id"]),
                },
                "id": "cs_test_abc123",
            }
        }
    }
    from src.core.billing.webhook_handler import handle_webhook_event
    result = await handle_webhook_event(event, repo)
    assert result is True
    updated = await repo.get_booking(sample_org["id"], b["id"])
    assert updated["payment_status"] == "paid"


async def test_webhook_subscription_mode_unaffected(repo, sample_org):
    """La logica subscription esistente non viene toccata."""
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "mode": "subscription",
                "metadata": {},
                "id": "cs_test_sub_123",
            }
        }
    }
    from src.core.billing.webhook_handler import handle_webhook_event
    result = await handle_webhook_event(event, repo)
    # Deve ritornare False o None (nessun booking matchato)
    assert result is not True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/billing/test_webhook_deposito.py -v`
Expected: FAIL (handle_webhook_event doesn't exist or doesn't handle payment mode)

- [ ] **Step 3: Examine existing webhook handler**

Read and understand current `webhook_handler.py` before modifying it.

```bash
cat src/core/billing/webhook_handler.py
```

- [ ] **Step 4: Implement payment mode routing**

Modify the `checkout.session.completed` handler in `webhook_handler.py`. The exact change depends on current structure, but the logic should be:

```python
if data.get("mode") == "subscription":
    # existing billing logic
    ...
elif data.get("mode") == "payment":
    booking_id = (data.get("metadata") or {}).get("booking_id")
    org_id = (data.get("metadata") or {}).get("organization_id")
    if booking_id and org_id:
        await repo.update_booking_payment(
            org_id, booking_id, "paid",
            session_id=data.get("id"),
        )
        return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/core/billing/test_webhook_deposito.py -v`
Expected: 2 PASS

- [ ] **Step 6: Verify existing billing tests still pass**

Run: `pytest tests/core/billing/ -v`
Expected: all existing billing tests still PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/billing/webhook_handler.py tests/core/billing/test_webhook_deposito.py
git commit -m "feat(bookings): webhook Stripe mode=payment handler for booking deposit confirmation"
```

---

### Task 9: Cleanup — Remove Old prenotazioni.py Global Variables + Airtable Dependency

**Files:**
- Modify: `src/core/prenotazioni.py` (rewrite as thin adapter, then remove)
- Modify: `src/api/main.py` (switch old /api/prenotazioni/* routes to BookingService)
- Remove: `scripts/migrate_airtable_to_bookings.py` (already fixed in Task 0)
- Run: full test suite

- [ ] **Step 1: Rewrite prenotazioni.py as thin adapter**

Replace all global variables and Airtable logic in `src/core/prenotazioni.py` with calls to `BookingService`:

```python
from src.core.db.repository import CoreRepository
from src.core.bookings import BookingService

# Deprecato: usa /api/bookings/*. Mantenuto per backward compat delle route legacy.
_repo_holder = None

def _get_service():
    from src.core.scheduler import _pool
    pool = _pool()
    if pool:
        return BookingService(CoreRepository(pool))
    return None


def get_impostazioni_disponibilita() -> dict:
    svc = _get_service()
    if not svc:
        return {"coperti_massimi_per_slot": 40, "fasce_orarie": [], "capienze_orarie": {}}
    settings = svc.repo.get_booking_settings(None)  # FIXME: need org_id
    ...
```

Actually, since the old routes need an `organization_id` but the legacy API doesn't have auth, a cleaner approach is to update the routes in `main.py` to use a default org ID when no auth is present (backward compat for demo mode), or simply mark the old routes as deprecated and redirect to the new ones.

Better approach: keep the old routes working with a default org_id (the demo org), with a deprecation warning log.

Actually, the simplest and cleanest approach (given the design doc says "remove"):

1. In `main.py`, update `/api/prenotazioni/*` routes to call `BookingService` with the user's organization_id (from auth), or with a fallback default org_id in demo mode
2. Remove all global variables from `prenotazioni.py`
3. Remove the deprecated `airtable_client.py` import from prenotazioni.py

Since the old routes already have `Depends(require_ruolo(...))`, they have `user` with `organization_id`. We can use that.

- [ ] **Step 2: Update legacy routes in main.py**

Replace old `prenotazioni` imports with `BookingService` calls:

```python
from src.core.bookings import BookingService
from src.core.db.repository import CoreRepository

# In the route functions, use:
# service = BookingService(CoreRepository(request.app.state.pool))
# b = await service.create_booking(user["organization_id"], ...)
```

- [ ] **Step 3: Remove `from src.core.prenotazioni import ...` and `from src.core.airtable_client import ...`**

Clean up all imports in `main.py` and other files that reference the old module.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`
Expected: all tests PASS (existing + new booking tests)

- [ ] **Step 5: Commit**

```bash
git add src/core/prenotazioni.py src/api/main.py
git commit -m "refactor(bookings): replace prenotazioni.py globals + Airtable with BookingService; remove deprecated module"
```
