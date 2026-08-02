from datetime import date, time
import pytest
import uuid

from src.core.bookings.memory_repo import InMemoryBookingRepo
from src.core.bookings.service import BookingService

pytestmark = pytest.mark.asyncio


def make_service():
    return BookingService(repo=InMemoryBookingRepo(), whatsapp_service=None, app_config=None)


async def test_memory_repo_create_and_list():
    repo = InMemoryBookingRepo()
    org = uuid.uuid4()
    b = await repo.create_booking(
        organization_id=org, nome_cliente="Mario", telefono="+393331234567",
        data="2026-08-01", ora="20:00", coperti=4,
    )
    assert b["stato"] == "in_attesa"
    assert isinstance(b["data"], date)
    assert isinstance(b["ora"], time)
    rows = await repo.list_bookings(org)
    assert len(rows) == 1
    assert rows[0]["nome_cliente"] == "Mario"


async def test_memory_repo_isolamento_org():
    repo = InMemoryBookingRepo()
    org1, org2 = uuid.uuid4(), uuid.uuid4()
    await repo.create_booking(organization_id=org1, nome_cliente="A", data="2026-08-01", ora="20:00", coperti=2)
    await repo.create_booking(organization_id=org2, nome_cliente="B", data="2026-08-01", ora="20:00", coperti=3)
    assert len(await repo.list_bookings(org1)) == 1
    assert len(await repo.list_bookings(org2)) == 1


async def test_memory_repo_get_booking():
    repo = InMemoryBookingRepo()
    org = uuid.uuid4()
    b = await repo.create_booking(organization_id=org, nome_cliente="X", data="2026-08-01", ora="20:00", coperti=2)
    got = await repo.get_booking(org, b["id"])
    assert got["id"] == b["id"]
    assert await repo.get_booking(uuid.uuid4(), b["id"]) is None


async def test_memory_repo_update_booking_status():
    repo = InMemoryBookingRepo()
    org = uuid.uuid4()
    b = await repo.create_booking(organization_id=org, nome_cliente="X", data="2026-08-01", ora="20:00", coperti=2)
    updated = await repo.update_booking_status(org, b["id"], "confermata")
    assert updated["stato"] == "confermata"
    refreshed = await repo.get_booking(org, b["id"])
    assert refreshed["stato"] == "confermata"


async def test_memory_repo_settings_default():
    repo = InMemoryBookingRepo()
    org = uuid.uuid4()
    assert await repo.get_booking_settings(org) is None
    settings = await repo.upsert_booking_settings(org, capienze_orarie={"20:00": 10})
    assert settings["capienze_orarie"]["20:00"] == 10
    assert await repo.get_booking_settings(org) is not None


async def test_memory_repo_settings_config():
    repo = InMemoryBookingRepo()
    org = uuid.uuid4()
    saved = await repo.upsert_booking_settings_config(org, {"deposito": {"enabled": True}})
    assert saved["config"]["deposito"]["enabled"] is True


async def test_booking_service_demo_verifica_disponibilita():
    svc = make_service()
    org = uuid.uuid4()
    disp = await svc.verifica_disponibilita(org, "2026-08-01", "20:00")
    assert disp.coperti_liberi == 40
    assert disp.stato == "verde"


async def test_booking_service_demo_semaforo():
    svc = make_service()
    org = uuid.uuid4()
    slots = await svc.semaforo_giorno(org, "2026-08-01")
    assert len(slots) == 24


async def test_booking_service_demo_create():
    svc = make_service()
    org = uuid.uuid4()
    b = await svc.create_booking(org, nome_cliente="Mario", data="2026-08-01", ora="20:00", coperti=4)
    assert b["stato"] == "in_attesa"
    assert len(await svc.repo.list_bookings(org)) == 1


async def test_booking_service_demo_slot_full():
    svc = make_service()
    org = uuid.uuid4()
    for i in range(4):
        await svc.repo.create_booking(organization_id=org, nome_cliente=f"G{i}",
            data=date(2026, 8, 1), ora=time(20, 0), coperti=10, stato="confermata")
    with pytest.raises(ValueError, match="slot pieno"):
        await svc.create_booking(org, nome_cliente="X", data="2026-08-01", ora="20:00", coperti=2)


async def test_booking_service_demo_aggiorna_impostazioni():
    svc = make_service()
    org = uuid.uuid4()
    settings = await svc.aggiorna_impostazioni(org, capienze_orarie={"20:00": 8})
    assert settings["capienze_orarie"]["20:00"] == 8
    disp = await svc.verifica_disponibilita(org, "2026-08-01", "20:00")
    assert disp.coperti_massimi == 8
