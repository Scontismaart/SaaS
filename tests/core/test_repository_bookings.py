from datetime import date, time

import pytest

pytestmark = pytest.mark.usefixtures("reset_db")

@pytest.mark.asyncio
async def test_create_and_get_booking(repo, sample_org):
    created = await repo.create_booking(
        organization_id=sample_org["id"],
        nome_cliente="Mario Rossi",
        telefono="+393912345678",
        data=date(2026, 7, 25),
        ora=time(20, 0),
        coperti=4,
        note="Tavolo vicino alla finestra",
        stato="in_attesa",
        origine="WhatsApp",
    )
    assert created["nome_cliente"] == "Mario Rossi"
    assert created["stato"] == "in_attesa"
    assert created["coperti"] == 4

    fetched = await repo.get_booking(sample_org["id"], created["id"])
    assert fetched is not None
    assert fetched["nome_cliente"] == "Mario Rossi"


@pytest.mark.asyncio
async def test_list_bookings_by_date(repo, sample_org):
    await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="A",
        data=date(2026, 7, 25), ora=time(20, 0), coperti=2,
    )
    await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="B",
        data=date(2026, 7, 25), ora=time(21, 0), coperti=3,
    )
    await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="C",
        data=date(2026, 7, 26), ora=time(20, 0), coperti=2,
    )
    bookings_25 = await repo.list_bookings(sample_org["id"], data=date(2026, 7, 25))
    assert len(bookings_25) == 2
    all_bookings = await repo.list_bookings(sample_org["id"])
    assert len(all_bookings) == 3


@pytest.mark.asyncio
async def test_update_booking_status(repo, sample_org):
    created = await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="Test",
        data=date(2026, 7, 25), ora=time(20, 0), coperti=2,
    )
    updated = await repo.update_booking_status(
        sample_org["id"], created["id"], "confermata"
    )
    assert updated["stato"] == "confermata"
    fetched = await repo.get_booking(sample_org["id"], created["id"])
    assert fetched["stato"] == "confermata"


@pytest.mark.asyncio
async def test_booking_requires_positive_coperti(repo, sample_org):
    with pytest.raises(Exception):
        await repo.create_booking(
            organization_id=sample_org["id"], nome_cliente="Bad",
            data=date(2026, 7, 25), ora=time(20, 0), coperti=0,
        )


@pytest.mark.asyncio
async def test_booking_cross_tenant_isolation(repo, sample_org, other_org):
    await repo.create_booking(
        organization_id=sample_org["id"], nome_cliente="Org1",
        data=date(2026, 7, 25), ora=time(20, 0), coperti=2,
    )
    bookings_org2 = await repo.list_bookings(other_org["id"])
    assert len(bookings_org2) == 0
