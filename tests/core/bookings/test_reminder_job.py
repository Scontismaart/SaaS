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
