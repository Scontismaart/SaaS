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
