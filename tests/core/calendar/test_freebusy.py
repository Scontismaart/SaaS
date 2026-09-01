"""Test unitari freebusy GoogleCalendarService (nessuna rete)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.calendar.service import GoogleCalendarService

FERNET_KEY = "GT4pFJ9wm5vlxRS2MSmSF3tjbThnKnon-sgG5TVYILE="


def _svc():
    return GoogleCalendarService(repo=MagicMock(), encryption_key=FERNET_KEY)


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
    assert start.tzinfo is None, "gli intervalli devono essere naive nel fuso org"
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
