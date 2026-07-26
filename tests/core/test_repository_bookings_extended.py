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
        data=tomorrow, ora=time(20, 0), coperti=2, stato="in_attesa")
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
