# Google Calendar Freebusy Availability Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** L'AI e la dashboard, prima di confermare una prenotazione, consultano anche gli eventi esistenti su Google Calendar (freebusy), così gli eventi creati direttamente su Google bloccano la capacità come quelli interni.

**Architecture:** `GoogleCalendarService.get_busy_intervals(org_id, data)` interroga l'endpoint `freebusy.query` (una chiamata per giorno, finestra 00:00–24:00 nel fuso dell'organizzazione) e restituisce intervalli occupati come aware datetime. `BookingService` introduce il check `_google_slot_occupato` (overlap tra [ora, ora+60min) e gli intervalli) invocato in `create_booking` e `update_booking` PRIMA del lock di fascia (chiamata di rete fuori dalla sezione critica, per non allungare il lock). Il check è **fail-open**: errori Google o credenziali assenti non bloccano la prenotazione — il DB resta la fonte autorevole, coerente con il design push-only esistente.

**Tech Stack:** google-api-python-client (`freebusy().query`), zoneinfo (fuso org), pytest con fake calendar service (nessuna rete nei test).

**Spec:** Audit dashboard 2026-09-01 — problema "Disponibilità mai verificata su Google Calendar (no freebusy)" (ALTA). Vincolo AGENTS.md: fail-closed solo per opt-out/suspension; qui la disponibilità esterna è best-effort per design (documentare nel codice).

## Global Constraints

- Fail-open documentato: qualsiasi errore Google (credenziali assenti, API ko, fuso invalido) → check saltato, prenotazione procede su sola capacità DB. Nessuna eccezione deve propagarsi al chiamante.
- La chiamata freebusy NON deve stare dentro `slot_lock` (lock di fascia: tenere una connessione pool durante una chiamata di rete aggraverebbe la nested-acquire già segnalata in review).
- Tenant isolation: `get_busy_intervals` usa solo credenziali/org-scoped esistenti (`_get_credentials`, `google_calendar_credentials WHERE organization_id = $1`).
- Zero modifiche al contratto degli endpoint esistenti.

---

### Task 1: `get_busy_intervals` su `GoogleCalendarService`

**Files:**
- Modify: `src/core/calendar/service.py` (dopo `delete_event`, prima di `sync_booking_state`)
- Test: `tests/core/calendar/test_freebusy.py` (nuovo)

**Interfaces:**
- Consumes: `_build_service(org_id)`, `_get_calendar_id(org_id)`, `_get_org_timezone(org_id)` esistenti.
- Produces: `async def get_busy_intervals(self, org_id, data) -> list[tuple[datetime, datetime]]` — intervalli `(start, end)` aware nel fuso org; `[]` se credenziali assenti o errore. Consumato dal Task 2.

- [ ] **Step 1: Scrivere il test che fallisce**

`tests/core/calendar/test_freebusy.py` (creare anche `tests/core/calendar/__init__.py` vuoto se assente):

```python
"""Test unitari freebusy GoogleCalendarService (nessuna rete)."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.calendar.service import GoogleCalendarService


def _svc():
    return GoogleCalendarService(repo=MagicMock(), encryption_key=FERNET_KEY)


FERNET_KEY = "kRGp1x9vZq3n0Tt8Wq2mI7cE5sYhA4uJ6bXzC1dVfNg="  # chiave fernet valida di test


def _fake_service(busy_payload):
    fake = MagicMock()
    fake.freebusy.return_value.query.return_value.execute.return_value = busy_payload
    return fake


@pytest.mark.asyncio
async def test_get_busy_intervals_parso_e_convertito(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(svc, "_build_service", AsyncMock(return_value=_fake_service({
        "calendars": {"primary": {"busy": [
            {"start": "2026-09-02T10:00:00Z", "end": "2026-09-02T11:30:00Z"},
            {"start": "malformed", "end": "x"},
        ]}}
    })))
    monkeypatch.setattr(svc, "_get_calendar_id", AsyncMock(return_value="primary"))
    monkeypatch.setattr(svc, "_get_org_timezone", AsyncMock(return_value="Europe/Rome"))

    intervals = await svc.get_busy_intervals("org-1", "2026-09-02")

    assert len(intervals) == 1  # l'intervallo malformed viene scartato
    start, end = intervals[0]
    assert start.utcoffset() is not None
    assert start.hour == 12  # 10:00Z -> 12:00 CEST


@pytest.mark.asyncio
async def test_get_busy_intervals_failopen_senza_credenziali(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(svc, "_build_service", AsyncMock(return_value=None))
    assert await svc.get_busy_intervals("org-1", "2026-09-02") == []


@pytest.mark.asyncio
async def test_get_busy_intervals_failopen_su_errore_api(monkeypatch):
    svc = _svc()
    fake = MagicMock()
    fake.freebusy.return_value.query.return_value.execute.side_effect = RuntimeError("api down")
    monkeypatch.setattr(svc, "_build_service", AsyncMock(return_value=fake))
    monkeypatch.setattr(svc, "_get_calendar_id", AsyncMock(return_value="primary"))
    monkeypatch.setattr(svc, "_get_org_timezone", AsyncMock(return_value="Europe/Rome"))
    assert await svc.get_busy_intervals("org-1", "2026-09-02") == []


@pytest.mark.asyncio
async def test_get_busy_intervals_fuso_invalido_failopen(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(svc, "_build_service", AsyncMock(return_value=_fake_service({"calendars": {}})))
    monkeypatch.setattr(svc, "_get_calendar_id", AsyncMock(return_value="primary"))
    monkeypatch.setattr(svc, "_get_org_timezone", AsyncMock(return_value="Mars/Olympus_Mons"))
    assert await svc.get_busy_intervals("org-1", "2026-09-02") == []
```

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run: `python -m pytest tests/core/calendar/test_freebusy.py -v`
Expected: FAIL con `AttributeError: 'GoogleCalendarService' object has no attribute 'get_busy_intervals'`

- [ ] **Step 3: Implementare**

In `src/core/calendar/service.py` aggiungere gli import in testa (`from zoneinfo import ZoneInfo`) e il metodo prima di `sync_booking_state`:

```python
    async def get_busy_intervals(self, org_id, data):
        """Intervalli occupati del calendario Google per la data (YYYY-MM-DD)
        come lista di (start, end) aware nel fuso dell'organizzazione.

        Fail-open per design (audit 2026-09-01): credenziali assenti, API in
        errore o fuso invalido -> lista vuota; il check e' best-effort e la
        capacita' DB resta la fonte autorevole."""
        service = await self._build_service(org_id)
        if not service:
            return []
        calendar_id = await self._get_calendar_id(org_id)
        tz_name = await self._get_org_timezone(org_id)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            logger.warning("calendar=invalid_timezone org_id=%s tz=%s", org_id, tz_name)
            return []
        giorno = datetime.fromisoformat(f"{data}T00:00:00").replace(tzinfo=tz)
        body = {
            "timeMin": giorno.isoformat(),
            "timeMax": (giorno + timedelta(days=1)).isoformat(),
            "items": [{"id": calendar_id}],
        }
        try:
            resp = await asyncio.to_thread(
                service.freebusy().query(body=body).execute
            )
        except Exception:
            logger.exception("calendar=freebusy_fail org_id=%s data=%s", org_id, data)
            return []
        intervals = []
        for cal in (resp.get("calendars") or {}).values():
            for b in cal.get("busy") or []:
                try:
                    bs = datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
                    be = datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
                except (KeyError, AttributeError, ValueError):
                    continue
                intervals.append((bs.astimezone(tz), be.astimezone(tz)))
        return intervals
```

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `python -m pytest tests/core/calendar/test_freebusy.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit** (se il working tree lo consente; altrimenti registrare nel changelog di sessione)

```bash
git add src/core/calendar/service.py tests/core/calendar/
git commit -m "feat(calendar): freebusy.query per intervalli occupati Google Calendar"
```

---

### Task 2: Check pre-prenotazione in `BookingService`

**Files:**
- Modify: `src/core/bookings/service.py`
- Test: `tests/core/bookings/test_booking_service.py`

**Interfaces:**
- Consumes: `get_busy_intervals(org_id, data)` (Task 1); costante `DEFAULT_SLOT_MINUTES = 60` (stessa durata di `create_event`).
- Produces: `async def _google_slot_occupato(self, org_id, data, ora) -> bool` — fail-open (False su errore/assenza). Usata in `create_booking` (pre-lock) e `update_booking` (quando `schedule_changed`, pre-verifica).

- [ ] **Step 1: Scrivere i test che falliscono**

Aggiungere in fondo a `tests/core/bookings/test_booking_service.py`:

```python
from datetime import timedelta
import pytest

from src.core.bookings.service import SlotPienoError


class FakeCalendarGoogle:
    """Fake del solo metodo usato dal check disponibilità; sync_booking_state
    no-op perché create_booking la invoca dopo l'INSERT."""

    def __init__(self, busy=None, error=False):
        self.busy = busy or []
        self.error = error
        self.synced = []

    async def get_busy_intervals(self, org_id, data):
        if self.error:
            raise RuntimeError("google down")
        return self.busy

    async def sync_booking_state(self, booking, org_id):
        self.synced.append(booking)


def _domani_iso():
    return (date.today() + timedelta(days=1)).isoformat()


async def test_create_booking_blocca_su_evento_google(repo, sample_org, settings):
    data = _domani_iso()
    # Intervallo che copre le 20:00 locali (offset fittizio, l'overlap è
    # calcolato su aware datetime): usiamo un intervallo a cavallo di mezzanotte
    # locale per renderlo indipendente dal fuso della macchina.
    busy = [
        (
            datetime.fromisoformat(f"{data}T00:00:00+00:00"),
            datetime.fromisoformat(f"{data}T23:59:00+00:00"),
        )
    ]
    svc = BookingService(repo, None, None, calendar_service=FakeCalendarGoogle(busy=busy))
    with pytest.raises(SlotPienoError):
        await svc.create_booking(
            org_id=sample_org["id"], nome_cliente="Mario", telefono="+393331112223",
            data=data, ora="20:00", coperti=2,
        )


async def test_create_booking_failopen_su_errore_google(repo, sample_org, settings):
    data = _domani_iso()
    svc = BookingService(repo, None, None, calendar_service=FakeCalendarGoogle(error=True))
    booking = await svc.create_booking(
        org_id=sample_org["id"], nome_cliente="Mario", telefono="+393331112223",
        data=data, ora="20:00", coperti=2,
    )
    assert booking is not None  # errore Google non blocca la prenotazione
```

Nota: importare `BookingService` nel file se non già presente; i fixture `repo`, `sample_org`, `settings` esistono in `tests/core/bookings/conftest.py`.

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `python -m pytest tests/core/bookings/test_booking_service.py -k google -v`
Expected: FAIL (il check non esiste: la prima prenotazione viene creata invece di sollevare SlotPienoError)

- [ ] **Step 3: Implementare**

In `src/core/bookings/service.py` aggiungere la costante modulo e l'helper:

```python
# Stessa durata evento usata dal push Google (calendar/service.py).
DEFAULT_SLOT_MINUTES = 60
```

```python
    async def _google_slot_occupato(self, org_id, data, ora) -> bool:
        """True se un evento Google Calendar copre lo slot [ora, ora+60min).
        Best-effort e fail-open: senza calendar service, su errore o con
        metodo assente (repo fake nei test) la risposta è False — la
        capacità DB resta la fonte autorevole della disponibilità."""
        if not self.calendar_service:
            return False
        if not hasattr(self.calendar_service, "get_busy_intervals"):
            return False
        try:
            busy = await self.calendar_service.get_busy_intervals(org_id, data)
        except Exception:
            logger.warning("calendar=freebusy_check_fail org_id=%s data=%s", org_id, data)
            return False
        ora_str = ora if isinstance(ora, str) else ora.strftime("%H:%M")
        slot_start = datetime.fromisoformat(f"{data}T{ora_str}:00")
        slot_end = slot_start + timedelta(minutes=DEFAULT_SLOT_MINUTES)
        for bs, be in busy:
            if slot_start < be and bs < slot_end:
                return True
        return False
```

In `create_booking`, subito dopo `_validated_booking_values` e PRIMA di `async with self._slot_lock(...)`:

```python
        if await self._google_slot_occupato(org_id, data, ora):
            disp = await self.verifica_disponibilita(org_id, data, ora, coperti)
            raise SlotPienoError(
                f"slot occupato su Google Calendar alle {ora}",
                alternative=disp.alternative,
            )
```

In `update_booking`, come prima istruzione dentro `if schedule_changed:` (prima della verifica DB):

```python
            if await self._google_slot_occupato(org_id, values["data"], values["ora"]):
                raise SlotPienoError(
                    f"slot occupato su Google Calendar alle {values['ora']}",
                )
```

Aggiungere `timedelta` agli import di `service.py` se assente (`from datetime import datetime, date, time, timedelta, timezone`).

- [ ] **Step 4: Eseguire i test e verificare che passino**

Run: `python -m pytest tests/core/bookings/test_booking_service.py -v`
Expected: tutti PASS (esistenti + 2 nuovi; il fixture `booking_service` esistente non ha calendar service → percorso invariato)

- [ ] **Step 5: Compilazione**

Run: `python -m py_compile src/core/bookings/service.py src/core/calendar/service.py`
Expected: OK

---

### Task 3: Chiusura

- [ ] **Step 1: Suite completa booking + calendar**

Run: `python -m pytest tests/core/bookings tests/core/calendar -q`
Expected: PASS (esclusi i test pg_pool che richiedono container Postgres, non disponibile in locale)

- [ ] **Step 2: Code review**

Skill requesting-code-review: dispatch reviewer con DESCRIPTION = piano `docs/superpowers/plans/2026-09-01-google-calendar-freebusy.md`, scope = `src/core/calendar/service.py` (get_busy_intervals), `src/core/bookings/service.py` (_google_slot_occupato + create/update), test nuovi.

---

## Esito (2026-09-01)

Implementato. Deviazioni documentate: gli intervalli freebusy sono NAIVE nel fuso org (contratto coerente con data/ora prenotazioni, evitato il confronto naive-vs-aware); il check in update_booking è stato SPOSTATO FUORI dal slot_lock a seguito di code review (la chiamata di rete dentro il lock teneva connessione pool + advisory lock per la durata della chiamata Google). Fail-open totale anche su eccezioni da _build_service.

Review successiva (cumulativa): 1 Critical (check in lock in update_booking — risolto spostandolo pre-lock + test aggiunto), 4 Important (tutti risolti: alias prezzi modelli default di routing, 403 carica-file prima del file.read(), fallback webhook derivato dal DB, RAG WhatsApp bypass → registrato come follow-up di prodotto), 5 Minor (risolti #6 isinstance guard, #7 _build_service nel try, #8 finestra sospensione documentata; #9/#10 differiti).
