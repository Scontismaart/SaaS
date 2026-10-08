from datetime import date, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from googleapiclient.errors import HttpError
import httplib2

from src.core.calendar.service import GoogleCalendarService


ORG_ID = "00000000-0000-0000-0000-000000000001"
BOOKING_ID = "00000000-0000-0000-0000-000000000002"


def _http_error(status):
    return HttpError(httplib2.Response({"status": str(status)}), b"private response body")


def _booking(**overrides):
    return {
        "id": BOOKING_ID,
        "organization_id": ORG_ID,
        "nome_cliente": "Sandbox",
        "telefono": "0000000000",
        "coperti": 2,
        "data": date(2026, 10, 7),
        "ora": time(12, 30),
        "stato": "confermata",
        "google_event_id": None,
        **overrides,
    }


def _service(monkeypatch, *, booking_exists=True):
    monkeypatch.setattr("src.core.calendar.service.google_calendar_enabled", lambda: True)
    conn = MagicMock()
    conn.fetchval = AsyncMock(return_value=booking_exists)
    conn.execute = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    repo = SimpleNamespace(pool=pool)
    service = GoogleCalendarService(repo, Fernet.generate_key())
    service._build_service = AsyncMock()
    service._get_calendar_id = AsyncMock(return_value="primary")
    service._get_org_timezone = AsyncMock(return_value="Europe/Rome")
    return service, conn


@pytest.mark.asyncio
async def test_create_reconciles_only_matching_private_event_after_conflict(monkeypatch):
    service, conn = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.insert.return_value.execute.side_effect = [
        TimeoutError("accepted request response lost"),
        _http_error(409),
    ]
    expected_id = __import__("hashlib").sha256(
        f"melpis-calendar-v1:{ORG_ID}:{BOOKING_ID}".encode()
    ).hexdigest()
    ownership = {"organization_id": ORG_ID, "booking_id": BOOKING_ID}
    google.events.return_value.get.return_value.execute.return_value = {
        "id": expected_id,
        "extendedProperties": {"private": ownership},
    }
    service._build_service.return_value = google

    with pytest.raises(TimeoutError):
        await service.create_event(_booking(), ORG_ID)
    event_id = await service.create_event(_booking(), ORG_ID)

    assert event_id == expected_id
    body = google.events.return_value.insert.call_args.kwargs["body"]
    assert body["id"] == expected_id
    assert body["extendedProperties"]["private"] == ownership
    google.events.return_value.get.assert_called_once_with(
        calendarId="primary", eventId=expected_id
    )
    assert google.events.return_value.insert.call_count == 2
    assert all(
        call.kwargs["body"]["id"] == expected_id
        for call in google.events.return_value.insert.call_args_list
    )
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_reconciles_after_database_write_failure(monkeypatch):
    service, conn = _service(monkeypatch)
    google = MagicMock()
    expected_id = __import__("hashlib").sha256(
        f"melpis-calendar-v1:{ORG_ID}:{BOOKING_ID}".encode()
    ).hexdigest()
    ownership = {"organization_id": ORG_ID, "booking_id": BOOKING_ID}
    google.events.return_value.insert.return_value.execute.side_effect = [
        {"id": expected_id},
        _http_error(409),
    ]
    google.events.return_value.get.return_value.execute.return_value = {
        "id": expected_id,
        "extendedProperties": {"private": ownership},
    }
    conn.execute.side_effect = [RuntimeError("database unavailable"), "UPDATE 1"]
    service._build_service.return_value = google

    assert await service.create_event(_booking(), ORG_ID) is None
    assert await service.create_event(_booking(), ORG_ID) == expected_id
    assert conn.execute.await_count == 2


@pytest.mark.asyncio
async def test_create_rejects_unowned_conflict_and_cross_tenant_booking(monkeypatch):
    service, conn = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.insert.return_value.execute.side_effect = _http_error(409)
    google.events.return_value.get.return_value.execute.return_value = {
        "id": "some-event",
        "extendedProperties": {"private": {"organization_id": "another-org"}},
    }
    service._build_service.return_value = google

    assert await service.create_event(_booking(), ORG_ID) is None
    assert conn.execute.await_count == 0

    service, _ = _service(monkeypatch)
    assert await service.create_event(_booking(organization_id="another-org"), ORG_ID) is None
    service._build_service.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejects_cancelled_conflict(monkeypatch):
    service, conn = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.insert.return_value.execute.side_effect = _http_error(409)
    expected_id = __import__("hashlib").sha256(
        f"melpis-calendar-v1:{ORG_ID}:{BOOKING_ID}".encode()
    ).hexdigest()
    google.events.return_value.get.return_value.execute.return_value = {
        "id": expected_id,
        "status": "cancelled",
        "extendedProperties": {
            "private": {"organization_id": ORG_ID, "booking_id": BOOKING_ID}
        },
    }
    service._build_service.return_value = google

    assert await service.create_event(_booking(), ORG_ID) is None
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_update_or_delete_keeps_local_event_reference(monkeypatch, caplog):
    caplog.set_level("ERROR")
    service, conn = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.update.return_value.execute.side_effect = RuntimeError(
        "private provider detail"
    )
    google.events.return_value.delete.return_value.execute.side_effect = _http_error(500)
    service._build_service.return_value = google
    booking = _booking(google_event_id="existing-event")

    assert await service.update_event(booking, ORG_ID) is None
    assert await service.delete_event(booking, ORG_ID) is None
    assert booking["google_event_id"] == "existing-event"
    assert conn.execute.await_count == 0
    assert all("private provider detail" not in record.message for record in caplog.records)
    assert all("private response body" not in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_delete_treats_missing_remote_event_as_idempotent_success(monkeypatch):
    service, conn = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.delete.return_value.execute.side_effect = _http_error(404)
    service._build_service.return_value = google
    booking = _booking(google_event_id="already-absent")

    assert await service.delete_event(booking, ORG_ID) == "already-absent"
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_treats_gone_remote_event_as_idempotent_success(monkeypatch):
    service, conn = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.delete.return_value.execute.side_effect = _http_error(410)
    service._build_service.return_value = google

    assert await service.delete_event(_booking(google_event_id="gone"), ORG_ID) == "gone"
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_unpersisted_booking_is_rejected_for_every_event_mutation(monkeypatch):
    service, conn = _service(monkeypatch, booking_exists=False)
    booking = _booking(google_event_id="existing-event")

    assert await service.create_event(booking, ORG_ID) is None
    assert await service.update_event(booking, ORG_ID) is None
    assert await service.delete_event(booking, ORG_ID) is None
    service._build_service.assert_not_awaited()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_preserves_calendar_private_ownership(monkeypatch):
    service, _ = _service(monkeypatch)
    google = MagicMock()
    google.events.return_value.update.return_value.execute.return_value = {"id": "existing"}
    service._build_service.return_value = google

    assert await service.update_event(
        _booking(google_event_id="existing"), ORG_ID
    ) == "existing"
    body = google.events.return_value.update.call_args.kwargs["body"]
    assert body["extendedProperties"]["private"] == {
        "organization_id": ORG_ID,
        "booking_id": BOOKING_ID,
    }
