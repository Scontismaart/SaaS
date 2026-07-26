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
        sample_org["id"], "+393331234567", "Forse"
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
