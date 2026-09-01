from datetime import datetime, timezone, date, time
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
    assert disp.coperti_liberi == 40


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
    assert disp.coperti_liberi == 30


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
    assert disp_other.coperti_liberi == 40


async def test_update_booking_keeps_status_for_profile_change(booking_service, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario", data="2026-08-01",
        ora="20:00", coperti=4,
    )
    await booking_service.confirm(sample_org["id"], b["id"])

    updated = await booking_service.update_booking(
        sample_org["id"], b["id"], nome_cliente="Mario Rossi", note="Finestra"
    )

    assert updated["stato"] == "confermata"
    assert updated["nome_cliente"] == "Mario Rossi"


async def test_update_booking_schedule_returns_to_pending(booking_service, sample_org):
    b = await booking_service.create_booking(
        sample_org["id"], nome_cliente="Mario", data="2026-08-01",
        ora="20:00", coperti=4,
    )
    await booking_service.confirm(sample_org["id"], b["id"])

    updated = await booking_service.update_booking(
        sample_org["id"], b["id"], data="2026-08-02"
    )

    assert updated["stato"] == "in_attesa"
    assert updated["data"].isoformat() == "2026-08-02"


# ── Check disponibilità Google Calendar (freebusy) ──────────────────────

from datetime import timedelta as _timedelta

from src.core.bookings.memory_repo import InMemoryBookingRepo
from src.core.bookings.service import BookingService, SlotPienoError


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
    return (date.today() + _timedelta(days=1)).isoformat()


async def test_create_booking_blocca_su_evento_google():
    repo = InMemoryBookingRepo()
    data = _domani_iso()
    # Intervallo a cavallo di quasi tutta la giornata, naive nel fuso org
    # (contratto di get_busy_intervals): l'overlap con lo slot 20:00-21:00
    # locale deve essere rilevato.
    busy = [
        (
            datetime.fromisoformat(f"{data}T00:00:00"),
            datetime.fromisoformat(f"{data}T23:59:00"),
        )
    ]
    svc = BookingService(repo, None, None, calendar_service=FakeCalendarGoogle(busy=busy))
    with pytest.raises(SlotPienoError):
        await svc.create_booking(
            org_id="org-1", nome_cliente="Mario", telefono="+393331112223",
            data=data, ora="20:00", coperti=2,
        )


async def test_create_booking_failopen_su_errore_google():
    repo = InMemoryBookingRepo()
    data = _domani_iso()
    svc = BookingService(repo, None, None, calendar_service=FakeCalendarGoogle(error=True))
    booking = await svc.create_booking(
        org_id="org-1", nome_cliente="Mario", telefono="+393331112223",
        data=data, ora="20:00", coperti=2,
    )
    assert booking is not None  # errore Google non blocca la prenotazione


async def test_update_booking_blocca_su_evento_google():
    repo = InMemoryBookingRepo()
    svc = BookingService(repo, None, None, calendar_service=FakeCalendarGoogle(busy=[]))
    data_libera = _domani_iso()
    booking = await svc.create_booking(
        org_id="org-1", nome_cliente="Mario", telefono="+393331112223",
        data=data_libera, ora="12:00", coperti=2,
    )
    # Spostamento su una fascia coperta da un evento Google
    svc.calendar_service.busy = [
        (
            datetime.fromisoformat(f"{data_libera}T00:00:00"),
            datetime.fromisoformat(f"{data_libera}T23:59:00"),
        )
    ]
    with pytest.raises(SlotPienoError):
        await svc.update_booking("org-1", booking["id"], ora="20:00")
