"""P1.3 Airtable webhook reliability (DB-free, riusa i fake di test_airtable_webhooks).

Copre: event-ID composito anti-collisione ms, fail-closed (None, True) -> 500,
guardia monotonica cursore, claim atomico concorrente, reaper orfani.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import hashlib
import json
import os
import uuid
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.integrations.airtable.errors import AirtableWebhookProcessingError
from src.integrations.airtable.webhook_service import AirtableWebhookService
from tests.integrations.airtable.test_airtable_webhooks import (
    FakePayloadFetcher,
    InMemoryMappingRepo,
    InMemoryWebhookRepo,
    generate_airtable_mac,
    official_payload_page,
    official_ping,
)

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
RAW_MAC_SECRET = base64.b64encode(os.urandom(32)).decode()


async def _subscribed_repo(base_id="appRelBase", webhook_id="achRelHook", cursor=1):
    repo = InMemoryWebhookRepo()
    await repo.save_subscription(
        organization_id=ORG_A, base_id=base_id, webhook_id=webhook_id,
        mac_secret=RAW_MAC_SECRET, cursor=cursor,
    )
    return repo


def _ping_body(base_id, webhook_id, ts="2026-09-07T10:00:00.000Z", extra=None):
    body = dict(official_ping(base_id, webhook_id, ts))
    if extra:
        body.update(extra)
    raw = json.dumps(body).encode("utf-8")
    return raw, generate_airtable_mac(raw, RAW_MAC_SECRET)


class TestCompositeEventId:
    @pytest.mark.asyncio
    async def test_same_ms_different_body_are_distinct(self):
        repo = await _subscribed_repo()
        service = AirtableWebhookService(repo=repo)
        raw1, mac1 = _ping_body("appRelBase", "achRelHook", extra={"n": 1})
        raw2, mac2 = _ping_body("appRelBase", "achRelHook", extra={"n": 2})

        e1, _, dup1 = await service.handle_incoming_notification(raw1, mac1)
        e2, _, dup2 = await service.handle_incoming_notification(raw2, mac2)

        assert dup1 is False and dup2 is False
        assert e1.id != e2.id
        assert e1.external_event_id != e2.external_event_id
        assert e1.external_event_id.startswith("ts:2026-09-07T10:00:00.000Z:hash:")

    @pytest.mark.asyncio
    async def test_identical_retry_still_deduplicated(self):
        repo = await _subscribed_repo()
        service = AirtableWebhookService(repo=repo)
        raw, mac = _ping_body("appRelBase", "achRelHook")

        e1, _, dup1 = await service.handle_incoming_notification(raw, mac)
        e2, _, dup2 = await service.handle_incoming_notification(raw, mac)

        assert dup1 is False and dup2 is True
        assert e2.id == e1.id


class TestNoneEventFailClosed:
    @pytest.mark.asyncio
    async def test_none_event_raises_processing_error(self):
        repo = await _subscribed_repo()
        repo.record_event_idempotent = AsyncMock(return_value=(None, True))
        service = AirtableWebhookService(repo=repo)
        raw, mac = _ping_body("appRelBase", "achRelHook")

        with pytest.raises(AirtableWebhookProcessingError):
            await service.handle_incoming_notification(raw, mac)

    @pytest.mark.asyncio
    async def test_none_event_route_returns_500_not_200(self):
        from src.api.dependencies import get_airtable_webhook_service
        from src.api.routes.airtable import router

        repo = await _subscribed_repo(base_id="appRoute500", webhook_id="achRoute500")
        repo.record_event_idempotent = AsyncMock(return_value=(None, True))
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_airtable_webhook_service] = (
            lambda: AirtableWebhookService(repo=repo)
        )
        client = TestClient(app, raise_server_exceptions=False)

        raw, mac = _ping_body("appRoute500", "achRoute500")
        resp = client.post(
            "/api/v1/integrations/airtable/webhook",
            content=raw,
            headers={"X-Airtable-Content-MAC": mac, "Content-Type": "application/json"},
        )
        # Fail-closed: 500 (retry Airtable) invece di 200 con evento perso.
        assert resp.status_code == 500


class TestCursorMonotonicGuard:
    @pytest.mark.asyncio
    async def test_stale_writer_does_not_regress(self):
        repo = await _subscribed_repo(cursor=6)
        assert await repo.update_cursor(ORG_A, "appRelBase", 4) is False
        sub = await repo.get_subscription(ORG_A, "appRelBase")
        assert sub.cursor == 6
        assert await repo.update_cursor(ORG_A, "appRelBase", 9) is True
        sub = await repo.get_subscription(ORG_A, "appRelBase")
        assert sub.cursor == 9


class TestConcurrentClaim:
    @pytest.mark.asyncio
    async def test_double_process_single_fetch(self):
        repo = await _subscribed_repo()
        mapping_repo = InMemoryMappingRepo()
        fetcher = FakePayloadFetcher(pages=[official_payload_page([])])
        service = AirtableWebhookService(
            repo=repo, mapping_repo=mapping_repo, payload_fetcher=fetcher)
        raw, mac = _ping_body("appRelBase", "achRelHook")
        event, sub, _ = await service.handle_incoming_notification(raw, mac)

        async def _run():
            return await service.process_event_async(
                event_id=event.id, organization_id=sub.organization_id,
                base_id=sub.base_id, webhook_id=sub.webhook_id,
                payload=event.payload)

        r1, r2 = await asyncio.gather(_run(), _run())

        assert fetcher.calls and len(fetcher.calls) == 1
        completed = [r for r in (r1, r2) if r["status"] == "completed"]
        other = [r for r in (r1, r2) if r["status"] != "completed"]
        assert len(completed) == 1
        # Il perdente non rielabora: deferred (in corso) o skipped (terminale).
        assert other[0]["status"] in ("deferred", "skipped")


class TestReaper:
    def _seed(self, repo, status, created_at):
        import uuid as _uuid

        from src.integrations.airtable.models import AirtableWebhookEvent

        event = AirtableWebhookEvent(
            id=_uuid.uuid4(), organization_id=ORG_A, base_id="appRelBase",
            webhook_id="achRelHook", external_event_id=f"ev-{_uuid.uuid4().hex[:8]}",
            event_type="notification_ping", payload={}, status=status)
        event.created_at = created_at
        repo.events[(ORG_A, "achRelHook", event.external_event_id)] = event
        return event

    @pytest.mark.asyncio
    async def test_stale_processing_requeued_fresh_and_terminal_untouched(self):
        repo = InMemoryWebhookRepo()
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        stale = self._seed(repo, "processing", old)
        fresh = self._seed(repo, "processing",
                           datetime.datetime.now(datetime.timezone.utc))
        done = self._seed(repo, "completed", old)

        service = AirtableWebhookService(repo=repo)
        out = await service.reap_stale_events(older_than_seconds=1800)

        assert out == {"reaped": 1}
        assert repo.events[(ORG_A, "achRelHook", stale.external_event_id)].status == "pending"
        assert repo.events[(ORG_A, "achRelHook", fresh.external_event_id)].status == "processing"
        assert repo.events[(ORG_A, "achRelHook", done.external_event_id)].status == "completed"

    @pytest.mark.asyncio
    async def test_reaped_event_can_be_processed_again(self):
        repo = InMemoryWebhookRepo()
        mapping_repo = InMemoryMappingRepo()
        fetcher = FakePayloadFetcher(pages=[official_payload_page([])])
        service = AirtableWebhookService(
            repo=repo, mapping_repo=mapping_repo, payload_fetcher=fetcher)
        await repo.save_subscription(
            organization_id=ORG_A, base_id="appRelBase", webhook_id="achRelHook",
            mac_secret=RAW_MAC_SECRET)
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        event = self._seed(repo, "processing", old)

        await service.reap_stale_events(older_than_seconds=1800)
        result = await service.process_event_async(
            event_id=event.id, organization_id=ORG_A, base_id="appRelBase",
            webhook_id="achRelHook", payload={})

        assert result["status"] == "completed"
        assert fetcher.calls == [1]


def test_composite_id_unit_shape():
    body = json.dumps(official_ping("b", "w", "2026-01-01T00:00:00.000Z")).encode()
    ext = AirtableWebhookService._extract_external_event_id(
        {"timestamp": "2026-01-01T00:00:00.000Z"}, body)
    expected = f"ts:2026-01-01T00:00:00.000Z:hash:{hashlib.sha256(body).hexdigest()[:16]}"
    assert ext == expected
