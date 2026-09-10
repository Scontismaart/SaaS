"""Unit test esaustivi per l'infrastruttura Webhook di Airtable.

Conforme al meccanismo ufficiale Airtable Webhooks API (thin ping):
- La notifica contiene SOLO base.id, webhook.id e timestamp.
- Autenticazione via header X-Airtable-Content-MAC (hmac-sha256= + HMAC-SHA256 hex del
  body grezzo, chiave = macSecretBase64 decodificata da Base64).
- Risposta HTTP ufficiale: 200 con body vuoto.
- I cambiamenti si recuperano da GET /v0/bases/{baseId}/webhooks/{webhookId}/payloads
  con cursore (fetch asincrono, MAI nella request HTTP).

Casi coperti:
1. Valid event: ping valido con firma ufficiale, identificazione integrazione,
   deduplicazione, recupero payload via cursore, filtro tabelle mappate e avanzamento cursore
2. Duplicate event: scarto atomico delle notifiche duplicate (idempotency Invariante 4)
3. Unknown event: payload con sole tabelle non mappate -> evento 'ignored' (fail-safe)
4. Malformed payload: body vuoto, JSON corrotto o privo di base.id/webhook.id -> 400
5. Unknown integration: webhook_id non registrato nel SaaS -> 404
6. Authentication failure: header X-Airtable-Content-MAC mancante o firma non valida -> 401
7. Processing failure: fallimento dell'elaborazione asincrona con stato 'failed' persistito
8. Tenant isolation: segregazione rigorosa a livello di tenant (Invariante 1)
9. Crittografia segreto MAC at-rest (Invariante 10)
10. Endpoint HTTP FastAPI (POST /webhook con body vuoto ufficiale, subscribe, events)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.core.db.scoping import TENANT_SCOPED_TABLES
from src.integrations.airtable import (
    AirtableMalformedWebhookError,
    AirtableNotFoundError,
    AirtableUnknownIntegrationError,
    AirtableWebhookAuthError,
    AirtableWebhookError,
    AirtableWebhookOwnershipError,
    AirtableWebhookEvent,
    AirtableWebhookNotification,
    AirtableWebhookProcessingError,
    AirtableWebhookRepository,
    AirtableWebhookService,
    AirtableWebhookSubscription,
    TableFieldMapping,
)


@pytest.fixture(autouse=True)
def setup_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("ENCRYPTION_KEY", key)
    return key


@pytest.fixture
def org_a_id() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def org_b_id() -> uuid.UUID:
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def raw_mac_secret() -> str:
    # Segreto casuale codificato in Base64 (formato ufficiale macSecretBase64 di Airtable)
    return base64.b64encode(b"super_secret_airtable_mac_key_32b!").decode("utf-8")


def generate_airtable_mac(raw_body: bytes, mac_secret: str, prefix: bool = True) -> str:
    """Calcola la firma HMAC-SHA256 secondo lo schema ufficiale Airtable:
    chiave = macSecretBase64 DECODIFICATA da Base64, digest esadecimale del body grezzo."""
    secret_bytes = base64.b64decode(mac_secret, validate=True)
    digest = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()
    return f"hmac-sha256={digest}" if prefix else digest


def official_ping(base_id: str, webhook_id: str, timestamp: str = "2026-09-07T10:00:00.000Z") -> dict[str, Any]:
    """Payload ufficiale della notifica Airtable (thin ping): solo base.id, webhook.id, timestamp."""
    return {
        "base": {"id": base_id},
        "webhook": {"id": webhook_id},
        "timestamp": timestamp,
    }


def official_payload_page(
    payloads: list[dict[str, Any]],
    might_have_more: bool = False,
) -> dict[str, Any]:
    """Risposta ufficiale dell'endpoint GET /webhooks/{webhookId}/payloads."""
    return {
        "number_of_pages": 1,
        "cursor": max([p.get("cursor", 1) for p in payloads] or [1]),
        "mightHaveMore": might_have_more,
        "payloads": payloads,
    }


# ── IN-MEMORY TEST DOUBLES ───────────────────────────────────────────────────


class InMemoryWebhookRepo:
    """Repository in-memory per test unitari veloci con garanzia di tenant isolation."""

    def __init__(self):
        self.subscriptions_by_webhook: dict[str, AirtableWebhookSubscription] = {}
        # Chiave deduplicazione atomica: (organization_id, webhook_id, external_event_id)
        self.events: dict[tuple[uuid.UUID, str, str], AirtableWebhookEvent] = {}

    async def save_subscription(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        mac_secret: str,
        cursor: int = 1,
        notification_url: str = "",
        specification: dict[str, Any] | None = None,
        is_active: bool = True,
    ) -> AirtableWebhookSubscription:
        org_uuid = uuid.UUID(str(organization_id))
        sub = AirtableWebhookSubscription(
            id=uuid.uuid4(),
            organization_id=org_uuid,
            base_id=base_id.strip(),
            webhook_id=webhook_id.strip(),
            mac_secret=mac_secret.strip(),
            cursor=cursor,
            notification_url=notification_url.strip(),
            specification=specification or {},
            is_active=is_active,
        )
        self.subscriptions_by_webhook[sub.webhook_id] = sub
        return sub

    async def get_subscription_by_webhook_id(self, webhook_id: str) -> AirtableWebhookSubscription | None:
        return self.subscriptions_by_webhook.get(webhook_id.strip())

    async def get_subscription(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
    ) -> AirtableWebhookSubscription | None:
        org_uuid = uuid.UUID(str(organization_id))
        for sub in self.subscriptions_by_webhook.values():
            if sub.organization_id == org_uuid and sub.base_id == base_id.strip():
                return sub
        return None

    async def update_cursor(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        cursor: int,
    ) -> bool:
        org_uuid = uuid.UUID(str(organization_id))
        for sub in self.subscriptions_by_webhook.values():
            if sub.organization_id == org_uuid and sub.base_id == base_id.strip():
                if int(sub.cursor or 0) >= int(cursor):
                    return False  # guardia monotonica: stale writer non regredisce
                sub.cursor = int(cursor)
                return True
        return False

    async def record_event_idempotent(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        webhook_id: str,
        external_event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[AirtableWebhookEvent | None, bool]:
        org_uuid = uuid.UUID(str(organization_id))
        key = (org_uuid, webhook_id.strip(), external_event_id.strip())

        if key in self.events:
            return self.events[key], True

        event = AirtableWebhookEvent(
            id=uuid.uuid4(),
            organization_id=org_uuid,
            base_id=base_id.strip(),
            webhook_id=webhook_id.strip(),
            external_event_id=external_event_id.strip(),
            event_type=event_type.strip(),
            payload=payload,
            status="pending",
        )
        self.events[key] = event
        return event, False

    async def update_event_status(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
        status: str,
        error_message: str | None = None,
    ) -> bool:
        org_uuid = uuid.UUID(str(organization_id))
        target_id = uuid.UUID(str(event_id))
        for event in self.events.values():
            if event.organization_id == org_uuid and event.id == target_id:
                event.status = status
                event.error_message = error_message
                return True
        return False

    async def claim_event_processing(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
    ) -> bool:
        org_uuid = uuid.UUID(str(organization_id))
        target_id = uuid.UUID(str(event_id))
        for event in self.events.values():
            if event.organization_id == org_uuid and event.id == target_id:
                if event.status != "pending":
                    return False
                event.status = "processing"
                return True
        return False

    async def reap_stale_processing(
        self, older_than_seconds: int = 1800, limit: int = 50
    ) -> list[dict]:
        import datetime

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=older_than_seconds
        )
        reaped = []
        for event in sorted(self.events.values(), key=lambda e: str(e.id)):
            if len(reaped) >= limit:
                break
            created = event.created_at if hasattr(event, "created_at") else None
            if event.status != "processing" or created is None:
                continue
            created_dt = created
            if isinstance(created_dt, str):
                try:
                    created_dt = datetime.datetime.fromisoformat(created_dt)
                except ValueError:
                    continue
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=datetime.timezone.utc)
            if created_dt < cutoff:
                event.status = "pending"
                reaped.append({"id": event.id, "organization_id": event.organization_id})
        return reaped

    async def get_event(
        self,
        organization_id: uuid.UUID | str,
        event_id: uuid.UUID | str,
    ) -> AirtableWebhookEvent | None:
        org_uuid = uuid.UUID(str(organization_id))
        target_id = uuid.UUID(str(event_id))
        for event in self.events.values():
            if event.organization_id == org_uuid and event.id == target_id:
                return event
        return None

    async def list_events(
        self,
        organization_id: uuid.UUID | str,
        base_id: str | None = None,
        limit: int = 50,
    ) -> list[AirtableWebhookEvent]:
        org_uuid = uuid.UUID(str(organization_id))
        results = [
            ev for ev in self.events.values()
            if ev.organization_id == org_uuid and (not base_id or ev.base_id == base_id.strip())
        ]
        return results[:limit]


class InMemoryMappingRepo:
    """Repository in-memory per la risoluzione dei mapping durante l'elaborazione dei webhook."""

    def __init__(self):
        self.mappings: dict[tuple[uuid.UUID, str, str], TableFieldMapping] = {}

    async def get_mapping_by_table(
        self,
        organization_id: uuid.UUID | str,
        base_id: str,
        table_id_or_name: str,
    ) -> TableFieldMapping | None:
        org_uuid = uuid.UUID(str(organization_id))
        return self.mappings.get((org_uuid, base_id.strip(), table_id_or_name.strip()))


class FakePayloadFetcher:
    """Fetcher in-memory che simula l'endpoint ufficiale GET /webhooks/{id}/payloads."""

    def __init__(self, pages: list[dict[str, Any]] | None = None, error: Exception | None = None):
        self.pages = pages or []
        self.error = error
        self.calls: list[int] = []

    async def fetch(self, organization_id, base_id, webhook_id, cursor) -> dict[str, Any]:
        self.calls.append(int(cursor))
        if self.error is not None:
            raise self.error
        if self.calls and len(self.calls) > len(self.pages):
            return official_payload_page([], might_have_more=False)
        return self.pages[len(self.calls) - 1]


# ── 1. TENANT SCOPED TABLES INVARIANT CHECK ──────────────────────────────────


def test_airtable_webhook_tables_in_tenant_scoped():
    """Invariante 1 & 2: Le tabelle airtable_webhooks e airtable_webhook_events devono essere tenant-scoped."""
    assert "airtable_webhooks" in TENANT_SCOPED_TABLES
    assert "airtable_webhook_events" in TENANT_SCOPED_TABLES


# ── 2. MAC VERIFICATION (SCHEMA UFFICIALE) ───────────────────────────────────


def test_mac_verification_official_scheme(org_a_id: uuid.UUID, raw_mac_secret: str):
    """La firma segue lo schema ufficiale: hmac-sha256= + hex HMAC-SHA256, chiave = segreto decodificato."""
    raw_body = json.dumps(official_ping("appMacBase", "achMacHook")).encode("utf-8")
    good_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    assert AirtableWebhookService.verify_signature(raw_body, good_mac, raw_mac_secret) is True
    # Tolleranza: header senza prefisso e case-insensitive
    assert AirtableWebhookService.verify_signature(raw_body, good_mac.split("=", 1)[1], raw_mac_secret) is True
    assert AirtableWebhookService.verify_signature(raw_body, good_mac.upper(), raw_mac_secret) is True

    # Firma calcolata con la stringa Base64 NON decodificata (errore comune) deve FALLIRE
    wrong_key_mac = hmac.new(raw_mac_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    assert AirtableWebhookService.verify_signature(raw_body, f"hmac-sha256={wrong_key_mac}", raw_mac_secret) is False
    # Body manomesso deve fallire
    assert AirtableWebhookService.verify_signature(raw_body + b" ", good_mac, raw_mac_secret) is False
    # Secret diverso deve fallire
    other_secret = base64.b64encode(b"another_secret_airtable_mac_key_!").decode("utf-8")
    assert AirtableWebhookService.verify_signature(raw_body, good_mac, other_secret) is False


# ── 3. VALID EVENT TEST (FULL OFFICIAL FLOW) ─────────────────────────────────


@pytest.mark.asyncio
async def test_valid_webhook_notification_and_processing(org_a_id: uuid.UUID, raw_mac_secret: str):
    """1. Valid event: ping ufficiale valido -> persistenza idempotente -> fetch payloads via cursore -> cursore avanzato."""
    webhook_repo = InMemoryWebhookRepo()
    mapping_repo = InMemoryMappingRepo()

    base_id = "appValidBase123"
    webhook_id = "achValidWebhook123"
    table_id = "tblCustomers001"

    await webhook_repo.save_subscription(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        mac_secret=raw_mac_secret,
        cursor=1,
    )

    mapping = TableFieldMapping(
        organization_id=org_a_id,
        base_id=base_id,
        table_id_or_name=table_id,
        entity_type="customer",
        field_mappings={"customer.name": "Nome", "customer.phone": "Telefono"},
        required_fields=["customer.name", "customer.phone"],
    )
    mapping_repo.mappings[(org_a_id, base_id, table_id)] = mapping

    # Pagina ufficiale del recupero payloads: tabella mappata (create+update+delete) e non mappata
    payload_entry = {
        "payloadFormat": "v0",
        "cursor": 5,
        "changedTablesById": {
            table_id: {
                "createdRecordsById": {
                    "rec001": {"createdTime": "2026-09-07T10:00:00.000Z", "fields": {"Nome": "Mario Rossi", "Telefono": "+393331234567"}},
                },
                "updatedRecordsById": {
                    "rec002": {"fields": {"Nome": "Luigi Bianchi", "Telefono": "+393339876543"}},
                },
                "destroyedRecordIds": ["rec003"],
            },
            "tblUnmapped999": {
                "createdRecordsById": {"rec999": {"fields": {"X": "y"}}},
            },
        },
    }
    fetcher = FakePayloadFetcher(pages=[official_payload_page([payload_entry])])

    service = AirtableWebhookService(repo=webhook_repo, mapping_repo=mapping_repo, payload_fetcher=fetcher)

    raw_body = json.dumps(official_ping(base_id, webhook_id)).encode("utf-8")
    header_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    # 1. Ingestion veloce (acknowledgment)
    event, sub, is_duplicate = await service.handle_incoming_notification(raw_body, header_mac)

    assert event is not None
    assert is_duplicate is False
    assert sub.organization_id == org_a_id
    assert event.status == "pending"
    assert event.event_type == "notification_ping"
    # Deduplicazione composita: timestamp + hash body (collisione ms impossibile,
    # retry con body identico comunque deduplicati)
    expected_prefix = "ts:2026-09-07T10:00:00.000Z:hash:"
    assert event.external_event_id.startswith(expected_prefix)
    expected_hash = hashlib.sha256(raw_body).hexdigest()[:16]
    assert event.external_event_id == f"{expected_prefix}{expected_hash}"

    # 2. Async processing: fetch payloads dal cursore salvato
    result = await service.process_event_async(
        event_id=event.id,
        organization_id=sub.organization_id,
        base_id=sub.base_id,
        webhook_id=sub.webhook_id,
        payload=event.payload,
    )

    assert result["status"] == "completed"
    # 3 record della tabella mappata (2 trasformati + 1 distrutto); tabella non mappata ignorata
    assert result["records_processed"] == 3
    assert result["relevant_tables"] == 1
    assert result["ignored_tables"] == 1
    assert result["cursor"] == 5

    # Il cursore parte dalla sottoscrizione (1) e avanza all'ultimo cursore elaborato + 1
    assert fetcher.calls == [1]
    persisted_sub = await webhook_repo.get_subscription(org_a_id, base_id)
    assert persisted_sub.cursor == 6

    # Verifica persistenza stato completato
    persisted_event = await webhook_repo.get_event(org_a_id, event.id)
    assert persisted_event is not None
    assert persisted_event.status == "completed"


@pytest.mark.asyncio
async def test_external_event_id_hash_fallback_without_timestamp(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Notifica senza timestamp (degenerata): fallback deterministico sull'hash del body grezzo."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    base_id, webhook_id = "appHashBase", "achHashHook"
    await webhook_repo.save_subscription(
        organization_id=org_a_id, base_id=base_id, webhook_id=webhook_id, mac_secret=raw_mac_secret,
    )

    raw_body = json.dumps({"base": {"id": base_id}, "webhook": {"id": webhook_id}}).encode("utf-8")
    header_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    event, _, is_dup = await service.handle_incoming_notification(raw_body, header_mac)
    assert is_dup is False
    expected_hash = f"hash:{hashlib.sha256(raw_body).hexdigest()[:24]}"
    assert event.external_event_id == expected_hash

    # Il body identico re-inviato deve comunque essere deduplicato
    _, _, is_dup2 = await service.handle_incoming_notification(raw_body, header_mac)
    assert is_dup2 is True


@pytest.mark.asyncio
async def test_notification_model_parses_official_payload():
    """AirtableWebhookNotification accetta il payload ufficiale thin-ping."""
    notification = AirtableWebhookNotification.from_raw_payload(
        official_ping("appModelBase", "achModelHook", "2026-09-07T11:00:00.000Z")
    )
    assert notification.base_id == "appModelBase"
    assert notification.webhook_id == "achModelHook"
    assert notification.timestamp == "2026-09-07T11:00:00.000Z"


# ── 4. DUPLICATE EVENT TEST ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_webhook_notification_deduplication(org_a_id: uuid.UUID, raw_mac_secret: str):
    """2. Duplicate: il retry ufficiale di Airtable (body identico, stesso timestamp) viene deduplicato."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    base_id = "appDedup123"
    webhook_id = "achDedup123"

    await webhook_repo.save_subscription(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        mac_secret=raw_mac_secret,
    )

    raw_body = json.dumps(official_ping(base_id, webhook_id, "2026-09-07T10:05:00.000Z")).encode("utf-8")
    header_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    # Prima notifica -> accettata
    event1, sub1, is_dup1 = await service.handle_incoming_notification(raw_body, header_mac)
    assert is_dup1 is False
    assert event1 is not None

    # Seconda notifica identica (retry ufficiale) -> deduplicata, stesso evento
    event2, sub2, is_dup2 = await service.handle_incoming_notification(raw_body, header_mac)
    assert is_dup2 is True
    assert event2 is not None
    assert event2.id == event1.id

    # Notifica con timestamp diverso = evento diverso (due cambiamenti distinti)
    raw_body2 = json.dumps(official_ping(base_id, webhook_id, "2026-09-07T10:06:00.000Z")).encode("utf-8")
    event3, _, is_dup3 = await service.handle_incoming_notification(raw_body2, generate_airtable_mac(raw_body2, raw_mac_secret))
    assert is_dup3 is False
    assert event3.id != event1.id


# ── 5. UNKNOWN EVENT TEST (TABELLE NON RILEVANTI) ────────────────────────────


@pytest.mark.asyncio
async def test_unknown_event_payloads_are_ignored(org_a_id: uuid.UUID, raw_mac_secret: str):
    """3. Unknown event: payload con sole tabelle non mappate per il tenant -> 'ignored' fail-safe."""
    webhook_repo = InMemoryWebhookRepo()
    mapping_repo = InMemoryMappingRepo()  # vuoto: nessuna tabella mappata
    fetcher = FakePayloadFetcher(
        pages=[official_payload_page([{
            "payloadFormat": "v0",
            "cursor": 2,
            "changedTablesById": {"tblUnrelated001": {"createdRecordsById": {"recX": {"fields": {}}}}},
        }])]
    )
    service = AirtableWebhookService(repo=webhook_repo, mapping_repo=mapping_repo, payload_fetcher=fetcher)

    base_id = "appIgnore123"
    webhook_id = "achIgnore123"

    await webhook_repo.save_subscription(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        mac_secret=raw_mac_secret,
    )

    raw_body = json.dumps(official_ping(base_id, webhook_id)).encode("utf-8")
    event, sub, _ = await service.handle_incoming_notification(raw_body, generate_airtable_mac(raw_body, raw_mac_secret))

    result = await service.process_event_async(
        event_id=event.id,
        organization_id=sub.organization_id,
        base_id=sub.base_id,
        webhook_id=sub.webhook_id,
        payload=event.payload,
    )

    assert result["status"] == "ignored"
    assert result["reason"] == "no_relevant_tables"
    persisted_event = await webhook_repo.get_event(org_a_id, event.id)
    assert persisted_event.status == "ignored"
    # Il cursore avanza comunque: i payload non rilevanti sono stati consumati
    persisted_sub = await webhook_repo.get_subscription(org_a_id, base_id)
    assert persisted_sub.cursor == 3


# ── 6. MALFORMED PAYLOAD TEST ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_payload_raises_error():
    """4. Malformed payload: Body vuoto, JSON corrotto o campioni obbligatori mancanti -> 400."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    # 1. Body vuoto
    with pytest.raises(AirtableMalformedWebhookError):
        await service.handle_incoming_notification(raw_body=b"", header_mac="some_mac")

    # 2. JSON non valido
    with pytest.raises(AirtableMalformedWebhookError):
        await service.handle_incoming_notification(raw_body=b"NOT_A_JSON_STRING", header_mac="some_mac")

    # 3. JSON valido ma privo di base.id o webhook.id (la notifica ufficiale li richiede entrambi)
    missing_fields_payload = json.dumps({"timestamp": "2026-09-07T10:00:00Z"}).encode("utf-8")
    with pytest.raises(AirtableMalformedWebhookError):
        await service.handle_incoming_notification(raw_body=missing_fields_payload, header_mac="some_mac")

    # 4. Array JSON invece di oggetto
    with pytest.raises(AirtableMalformedWebhookError):
        await service.handle_incoming_notification(raw_body=b"[]", header_mac="some_mac")


# ── 7. UNKNOWN INTEGRATION TEST ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_integration_raises_404_error(raw_mac_secret: str):
    """5. Unknown integration: webhook_id inesistente o non registrato nel DB -> 404."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    raw_body = json.dumps(official_ping("appUnknownBase", "achUnknownWebhook")).encode("utf-8")
    header_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    with pytest.raises(AirtableUnknownIntegrationError) as exc_info:
        await service.handle_incoming_notification(raw_body=raw_body, header_mac=header_mac)

    assert exc_info.value.status_code == 404
    assert "achUnknownWebhook" in exc_info.value.message


@pytest.mark.asyncio
async def test_base_id_mismatch_raises_unknown_integration(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Invariante 1: la notifica deve corrispondere anche al base_id registrato della sottoscrizione."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    await webhook_repo.save_subscription(
        organization_id=org_a_id,
        base_id="appRegisteredBase",
        webhook_id="achMismatchHook",
        mac_secret=raw_mac_secret,
    )

    # webhoook noto ma base_id diverso da quello registrato -> non fidarsi del payload
    raw_body = json.dumps(official_ping("appSpoofedBase", "achMismatchHook")).encode("utf-8")
    header_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    with pytest.raises(AirtableUnknownIntegrationError):
        await service.handle_incoming_notification(raw_body=raw_body, header_mac=header_mac)


# ── 8. AUTHENTICATION FAILURE TEST ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_authentication_failure_invalid_or_missing_mac(org_a_id: uuid.UUID, raw_mac_secret: str):
    """6. Authentication failure: Mancanza o firma errata dell'header X-Airtable-Content-MAC -> 401."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    base_id = "appAuthTest"
    webhook_id = "achAuthTest"

    await webhook_repo.save_subscription(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        mac_secret=raw_mac_secret,
    )

    raw_body = json.dumps(official_ping(base_id, webhook_id)).encode("utf-8")

    # 1. Header mancante
    with pytest.raises(AirtableWebhookAuthError):
        await service.handle_incoming_notification(raw_body=raw_body, header_mac=None)

    # 2. Firma errata / contraffatta
    tampered_mac = "hmac-sha256=0000000000000000000000000000000000000000000000000000000000000000"
    with pytest.raises(AirtableWebhookAuthError) as exc_info:
        await service.handle_incoming_notification(raw_body=raw_body, header_mac=tampered_mac)

    assert exc_info.value.status_code == 401
    assert "non valida" in exc_info.value.message

    # 3. Firma calcolata con un segreto diverso (attacco con webhook registrato altrove)
    other_secret = base64.b64encode(b"attacker_controlled_mac_secret_key").decode("utf-8")
    forged_mac = generate_airtable_mac(raw_body, other_secret)
    with pytest.raises(AirtableWebhookAuthError):
        await service.handle_incoming_notification(raw_body=raw_body, header_mac=forged_mac)


# ── 9. PROCESSING FAILURE TEST ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_processing_failure_updates_status_and_persists_error(org_a_id: uuid.UUID, raw_mac_secret: str):
    """7. Processing failure: Fallimento del fetch dei payload registra stato 'failed' con errore."""
    webhook_repo = InMemoryWebhookRepo()
    mapping_repo = InMemoryMappingRepo()
    fetcher = FakePayloadFetcher(error=RuntimeError("Database connection lost during processing"))
    service = AirtableWebhookService(repo=webhook_repo, mapping_repo=mapping_repo, payload_fetcher=fetcher)

    base_id, webhook_id = "appCrashBase", "achCrashWebhook"
    await webhook_repo.save_subscription(
        organization_id=org_a_id, base_id=base_id, webhook_id=webhook_id, mac_secret=raw_mac_secret,
    )

    raw_body = json.dumps(official_ping(base_id, webhook_id)).encode("utf-8")
    event, sub, _ = await service.handle_incoming_notification(raw_body, generate_airtable_mac(raw_body, raw_mac_secret))

    with pytest.raises(AirtableWebhookProcessingError) as exc_info:
        await service.process_event_async(
            event_id=event.id,
            organization_id=sub.organization_id,
            base_id=sub.base_id,
            webhook_id=sub.webhook_id,
            payload=event.payload,
        )

    assert exc_info.value.status_code == 500
    assert "Database connection lost" in exc_info.value.message
    persisted_event = await webhook_repo.get_event(org_a_id, event.id)
    assert persisted_event.status == "failed"
    assert "Database connection lost" in persisted_event.error_message


@pytest.mark.asyncio
async def test_processing_without_fetcher_defers_event(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Senza payload fetcher configurato l'evento resta 'pending' (deferred), non 'failed'."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    base_id, webhook_id = "appDeferBase", "achDeferHook"
    await webhook_repo.save_subscription(
        organization_id=org_a_id, base_id=base_id, webhook_id=webhook_id, mac_secret=raw_mac_secret,
    )

    raw_body = json.dumps(official_ping(base_id, webhook_id)).encode("utf-8")
    event, sub, _ = await service.handle_incoming_notification(raw_body, generate_airtable_mac(raw_body, raw_mac_secret))

    result = await service.process_event_async(
        event_id=event.id,
        organization_id=sub.organization_id,
        base_id=sub.base_id,
        webhook_id=sub.webhook_id,
        payload=event.payload,
    )

    assert result["status"] == "deferred"
    persisted_event = await webhook_repo.get_event(org_a_id, event.id)
    assert persisted_event.status == "pending"


@pytest.mark.asyncio
async def test_pagination_follows_might_have_more(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Paginazione ufficiale: while mightHaveMore=true si richiede la pagina successiva col cursore."""
    webhook_repo = InMemoryWebhookRepo()
    mapping_repo = InMemoryMappingRepo()

    base_id, webhook_id, table_id = "appPageBase", "achPageHook", "tblPaged001"
    await webhook_repo.save_subscription(
        organization_id=org_a_id, base_id=base_id, webhook_id=webhook_id, mac_secret=raw_mac_secret, cursor=1,
    )
    mapping_repo.mappings[(org_a_id, base_id, table_id)] = TableFieldMapping(
        organization_id=org_a_id,
        base_id=base_id,
        table_id_or_name=table_id,
        entity_type="customer",
        field_mappings={"customer.name": "Nome"},
        required_fields=["customer.name"],
    )

    fetcher = FakePayloadFetcher(pages=[
        official_payload_page(
            [{"payloadFormat": "v0", "cursor": 2, "changedTablesById": {table_id: {"createdRecordsById": {"recA": {"fields": {"Nome": "A"}}}}}}],
            might_have_more=True,
        ),
        official_payload_page(
            [{"payloadFormat": "v0", "cursor": 3, "changedTablesById": {table_id: {"createdRecordsById": {"recB": {"fields": {"Nome": "B"}}}}}}],
            might_have_more=False,
        ),
    ])
    service = AirtableWebhookService(repo=webhook_repo, mapping_repo=mapping_repo, payload_fetcher=fetcher)

    raw_body = json.dumps(official_ping(base_id, webhook_id)).encode("utf-8")
    event, sub, _ = await service.handle_incoming_notification(raw_body, generate_airtable_mac(raw_body, raw_mac_secret))

    result = await service.process_event_async(
        event_id=event.id,
        organization_id=sub.organization_id,
        base_id=sub.base_id,
        webhook_id=sub.webhook_id,
        payload=event.payload,
    )

    assert result["status"] == "completed"
    assert result["records_processed"] == 2
    assert fetcher.calls == [1, 2]
    persisted_sub = await webhook_repo.get_subscription(org_a_id, base_id)
    assert persisted_sub.cursor == 4


# ── 9b. WEBHOOK SUBSCRIPTION OWNERSHIP (ANTI-HIJACK / IDOR) ───────────────────


@pytest.mark.asyncio
async def test_webhook_subscription_hijack_rejected_across_tenants(
    org_a_id: uuid.UUID, org_b_id: uuid.UUID, raw_mac_secret: str
):
    """Tenant isolation: il Tenant B NON puo' sovrascrivere (hijack) il webhook_id del Tenant A."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    other_secret = base64.b64encode(b"attacker_controlled_mac_secret!").decode("utf-8")

    await service.register_webhook(
        organization_id=org_a_id,
        base_id="appOrgA",
        webhook_id="achHijackMe",
        mac_secret=raw_mac_secret,
    )

    # Tenant B prova ad appropriarsi del webhook_id di A con il proprio mac_secret
    with pytest.raises(AirtableWebhookOwnershipError) as exc_info:
        await service.register_webhook(
            organization_id=org_b_id,
            base_id="appOrgA",
            webhook_id="achHijackMe",
            mac_secret=other_secret,
        )
    assert exc_info.value.status_code == 403

    # La sottoscrizione di A deve restare INTATTA (stesso segreto, stessa org, attiva)
    sub = await webhook_repo.get_subscription_by_webhook_id("achHijackMe")
    assert sub.organization_id == org_a_id
    assert sub.mac_secret == raw_mac_secret
    assert sub.is_active is True


@pytest.mark.asyncio
async def test_webhook_subscription_re_registration_same_org_allowed(
    org_a_id: uuid.UUID, raw_mac_secret: str
):
    """Il legittimo proprietario puo' ri-registrare (rotazione secret) il proprio webhook."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    await service.register_webhook(
        organization_id=org_a_id, base_id="appRot", webhook_id="achRot", mac_secret=raw_mac_secret,
    )
    rotated = base64.b64encode(b"rotated_secret_airtable_mac").decode("utf-8")
    sub = await service.register_webhook(
        organization_id=org_a_id, base_id="appRot", webhook_id="achRot", mac_secret=rotated,
    )
    assert sub.mac_secret == rotated
    assert sub.organization_id == org_a_id


@pytest.mark.asyncio
async def test_subscribe_route_rejects_base_not_connected_to_tenant(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Base authorization: la route subscribe richiede la Base connessa al tenant autenticato."""
    from src.api.dependencies import get_airtable_service, get_airtable_webhook_service
    from src.api.routes.airtable import router
    from src.core.auth.dependencies import get_organization_context

    app = FastAPI()
    app.include_router(router)

    webhook_repo = InMemoryWebhookRepo()
    app.dependency_overrides[get_airtable_webhook_service] = lambda: AirtableWebhookService(repo=webhook_repo)

    # Connection service senza connessioni registrate: nessuna Base appartiene al tenant
    class EmptyConnectionRepo:
        async def get_connection(self, organization_id, base_id):
            return None

    class FakeConnectionService:
        def __init__(self):
            self.repo = EmptyConnectionRepo()

        async def get_adapter_for_tenant(self, organization_id, base_id):
            conn = await self.repo.get_connection(organization_id, base_id)
            if not conn or not conn.get("is_active", True):
                raise AirtableNotFoundError(
                    f"Nessuna connessione Airtable attiva trovata per l'organizzazione {organization_id} e Base {base_id}."
                )
            return None

    app.dependency_overrides[get_airtable_service] = lambda: FakeConnectionService()
    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": str(org_a_id),
        "ruolo": "owner",
        "user_id": str(uuid.uuid4()),
        "source": "jwt",
    }

    client = TestClient(app)
    resp = client.post(
        "/api/v1/integrations/airtable/webhooks/subscribe",
        json={
            "base_id": "appBelongsToSomeoneElse",
            "webhook_id": "achSubscribeTest",
            "mac_secret": raw_mac_secret,
        },
    )
    assert resp.status_code == 403
    # Nessuna sottoscrizione deve essere stata creata
    assert webhook_repo.subscriptions_by_webhook == {}


# ── 10. TENANT ISOLATION TEST ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_tenant_isolation(org_a_id: uuid.UUID, org_b_id: uuid.UUID, raw_mac_secret: str):
    """Invariante 1: Segregazione totale tra tenant per sottoscrizioni ed eventi webhook."""
    webhook_repo = InMemoryWebhookRepo()
    service = AirtableWebhookService(repo=webhook_repo)

    # Org A sottoscrive Base A
    await service.register_webhook(
        organization_id=org_a_id,
        base_id="appOrgA",
        webhook_id="achOrgA",
        mac_secret=raw_mac_secret,
    )

    # Org B sottoscrive Base B
    await service.register_webhook(
        organization_id=org_b_id,
        base_id="appOrgB",
        webhook_id="achOrgB",
        mac_secret=raw_mac_secret,
    )

    # Verifica isolamento get_subscription
    assert await service.get_subscription(org_a_id, "appOrgA") is not None
    assert await service.get_subscription(org_b_id, "appOrgA") is None

    # Simula ricezione evento per Org A
    raw_a = json.dumps(official_ping("appOrgA", "achOrgA")).encode("utf-8")
    mac_a = generate_airtable_mac(raw_a, raw_mac_secret)

    event_a, _, _ = await service.handle_incoming_notification(raw_a, mac_a)

    # Org B non deve poter accedere all'evento di Org A
    assert await service.get_event(org_a_id, event_a.id) is not None
    assert await service.get_event(org_b_id, event_a.id) is None


# ── 11. FASTAPI ROUTE INTEGRATION TESTS ──────────────────────────────────────


@pytest.mark.asyncio
async def test_fastapi_webhook_route_full_cycle(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Verifica l'integrazione dell'endpoint FastAPI POST /webhook: risposta ufficiale 200 con body vuoto."""
    from src.api.dependencies import get_airtable_webhook_service
    from src.api.routes.airtable import router

    app = FastAPI()
    app.include_router(router)

    webhook_repo = InMemoryWebhookRepo()
    base_id = "appRouteTest"
    webhook_id = "achRouteTest"

    await webhook_repo.save_subscription(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        mac_secret=raw_mac_secret,
    )

    mock_webhook_service = AirtableWebhookService(repo=webhook_repo)
    app.dependency_overrides[get_airtable_webhook_service] = lambda: mock_webhook_service

    client = TestClient(app)

    raw_body = json.dumps(official_ping(base_id, webhook_id, "2026-09-07T12:00:00.000Z")).encode("utf-8")
    valid_mac = generate_airtable_mac(raw_body, raw_mac_secret)

    # 1. Chiamata valida con HMAC valido -> 200 con BODY VUOTO (schema ufficiale Airtable)
    resp = client.post(
        "/api/v1/integrations/airtable/webhook",
        content=raw_body,
        headers={"X-Airtable-Content-MAC": valid_mac, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    assert resp.content == b""

    # 2. Chiamata duplicata (retry ufficiale) -> 200 body vuoto, nessun retry storm
    resp_dup = client.post(
        "/api/v1/integrations/airtable/webhook",
        content=raw_body,
        headers={"X-Airtable-Content-MAC": valid_mac, "Content-Type": "application/json"},
    )
    assert resp_dup.status_code == 200
    assert resp_dup.content == b""

    # 3. Chiamata con firma non valida -> 401
    resp_bad_auth = client.post(
        "/api/v1/integrations/airtable/webhook",
        content=raw_body,
        headers={"X-Airtable-Content-MAC": "invalid_signature", "Content-Type": "application/json"},
    )
    assert resp_bad_auth.status_code == 401

    # 4. Chiamata con payload malformato -> 400
    resp_bad_payload = client.post(
        "/api/v1/integrations/airtable/webhook",
        content=b"BAD_JSON",
        headers={"X-Airtable-Content-MAC": valid_mac, "Content-Type": "application/json"},
    )
    assert resp_bad_payload.status_code == 400

    # 5. Chiamata verso webhook_id inesistente -> 404
    unknown_body = json.dumps(official_ping("appGhost", "achGhost")).encode("utf-8")
    resp_unknown = client.post(
        "/api/v1/integrations/airtable/webhook",
        content=unknown_body,
        headers={"X-Airtable-Content-MAC": valid_mac, "Content-Type": "application/json"},
    )
    assert resp_unknown.status_code == 404

    # 6. GET /webhooks/events per il tenant autenticato
    from src.core.auth.dependencies import get_organization_context

    app.dependency_overrides[get_organization_context] = lambda: {
        "organization_id": str(org_a_id),
        "ruolo": "owner",
        "user_id": str(uuid.uuid4()),
        "source": "jwt",
    }
    resp_events = client.get("/api/v1/integrations/airtable/webhooks/events")
    assert resp_events.status_code == 200
    assert len(resp_events.json()) >= 1


# ── 12. SQL REPOSITORY AT-REST ENCRYPTION & IDEMPOTENCY ──────────────────────


@pytest.mark.asyncio
async def test_sql_webhook_repo_crypto_and_scoped_conn(org_a_id: uuid.UUID, raw_mac_secret: str):
    """Invariante 1 & 10: Verifica crittografia at-rest del MAC secret ed esecuzione tenant-scoped."""
    mock_conn = MagicMock()
    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    repo = AirtableWebhookRepository(pool=mock_pool)
    base_id = "appSqlBase123"
    webhook_id = "achSqlWebhook123"

    # 1. Test crittografia at-rest
    encrypted_secret = repo.encrypt_secret(raw_mac_secret)
    assert raw_mac_secret not in encrypted_secret
    assert repo.decrypt_secret(encrypted_secret) == raw_mac_secret

    # 2. Test save_subscription
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "organization_id": org_a_id,
            "base_id": base_id,
            "webhook_id": webhook_id,
            "mac_secret_encrypted": encrypted_secret,
            "cursor": 1,
            "notification_url": "https://api.example.com/webhook",
            "specification": "{}",
            "is_active": True,
            "created_at": None,
            "updated_at": None,
        }
    )

    sub = await repo.save_subscription(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        mac_secret=raw_mac_secret,
        notification_url="https://api.example.com/webhook",
    )

    assert sub.mac_secret == raw_mac_secret
    assert sub.webhook_id == webhook_id
    mock_conn.fetchrow.assert_called_once()
    # Verifica che il secret passato alla query SQL sia cifrato e non in chiaro (Invariante 10)
    args = mock_conn.fetchrow.call_args[0]
    sql_query = args[0]
    assert "INSERT INTO airtable_webhooks" in sql_query
    assert raw_mac_secret not in [str(a) for a in args[1:]]

    # 3. Test record_event_idempotent (deduplicazione ufficiale su timestamp)
    event_id = uuid.uuid4()
    mock_conn.fetchrow = AsyncMock(
        return_value={
            "id": event_id,
            "organization_id": org_a_id,
            "base_id": base_id,
            "webhook_id": webhook_id,
            "external_event_id": "ts:2026-09-07T12:00:00.000Z",
            "event_type": "notification_ping",
            "payload": "{}",
            "status": "pending",
            "error_message": None,
            "created_at": None,
            "processed_at": None,
        }
    )

    event, is_duplicate = await repo.record_event_idempotent(
        organization_id=org_a_id,
        base_id=base_id,
        webhook_id=webhook_id,
        external_event_id="ts:2026-09-07T12:00:00.000Z",
        event_type="notification_ping",
        payload={"key": "val"},
    )
    assert is_duplicate is False
    assert event.id == event_id

    # 4. Test update_event_status
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")
    ok = await repo.update_event_status(
        organization_id=org_a_id,
        event_id=event_id,
        status="completed",
    )
    assert ok is True

    # 5. Test update_cursor: il cursore avanza solo per la sottoscrizione del tenant
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")
    ok = await repo.update_cursor(org_a_id, base_id, 6)
    assert ok is True
    args = mock_conn.execute.call_args[0]
    assert "UPDATE airtable_webhooks" in args[0]
    assert "cursor = $1" in args[0]
    assert "organization_id = $2" in args[0]
