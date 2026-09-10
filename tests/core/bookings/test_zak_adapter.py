"""Test ZakAdapter — Allineamento con API reale WuBook ZaK (KAPI) per Hospitality.

Verifica che ZakAdapter rispetti rigorosamente le specifiche reali di WuBook ZaK (kapi.wubook.net):
1. Protocol Conformance (BookingSystemPort runtime check)
2. Autenticazione reale: header x-api-key (non X-Zak-Key / X-Property-Id) e base URL https://kapi.wubook.net/kapi
3. Protocollo POST-only RPC per tutti gli endpoint:
   - POST /property/fetch_rooms (get_services)
   - POST /inventory/fetch_availability (get_availability)
   - POST /reservations/create (create_booking)
   - POST /reservations/cancel (cancel_booking)
   - POST /customers/fetch_one (get_customer)
4. Copertura delle 6 aree hospitality:
   - Regimi di trattamento (Meals & Board: RO, BB, HB, FB, AI)
   - Piani tariffari dinamici (prezzo dinamico in get_availability)
   - Occupazione per fascia d'età (adulti, bambini, età bambini)
   - Gestione realistica degli errori KAPI (auth failure, overbooking, bad payload)
   - Overbooking OTA / Channel collision -> stato="rifiutata", error_code="slot_full"
   - Autenticazione reale e assenza di idempotency header nativi
5. DST Multi-night stay safety
6. Timeout e fast-fail
7. Risoluzione tramite BookingAdapterRouter
"""
from __future__ import annotations

import json
import uuid
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from httpx import Response

from src.core.bookings.adapters.zak_adapter import ZAK_DEFAULT_BASE_URL, ZakAdapter
from src.core.bookings.ports.base import (
    AvailabilityQuery,
    BookingResult,
    BookingSystemPort,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerQuery,
    CustomerResult,
)
from src.core.bookings.router import BookingAdapterRouter, BookingMode

ORG_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
TEST_BASE_URL = "https://kapi.wubook.net/kapi"


@pytest.fixture
def zak_adapter():
    return ZakAdapter(
        property_id="hotel_bellavista",
        api_key="zak_live_api_key_xyz987",
        base_url=TEST_BASE_URL,
        timeout_seconds=4.0,
    )


# ── 1. Protocol Conformance ───────────────────────────────────

def test_zak_adapter_conforms_to_booking_system_port(zak_adapter):
    """Verifica conformità formale al protocollo BookingSystemPort."""
    assert isinstance(zak_adapter, BookingSystemPort)


def test_zak_adapter_default_base_url():
    """Verifica che il base URL di default punti all'endpoint KAPI reale."""
    adapter = ZakAdapter(property_id="prop_1", api_key="key_1")
    assert adapter.base_url == "https://kapi.wubook.net/kapi"


# ── 2. Check-in / Check-out Windows ───────────────────────────

@pytest.mark.asyncio
async def test_zak_adapter_get_opening_hours(zak_adapter):
    """Verifica finestre standard di check-in (14:00 - 20:00)."""
    res = await zak_adapter.get_opening_hours(ORG_ID)
    assert res.orari is not None
    assert len(res.orari) == 7
    lunedi = res.orari[0]
    assert lunedi.aperto is True
    assert any(slot.inizio == time(14, 0) for slot in lunedi.fasce)


# ── 3. Recupero Tipologie Camere (get_services via POST) ───────

@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_get_services_kapi_post(zak_adapter):
    """Verifica che get_services usi POST /property/fetch_rooms con header x-api-key."""
    captured_requests = []

    def handle_fetch_rooms(request):
        captured_requests.append(request)
        return Response(
            200,
            json={
                "data": [
                    {
                        "room_id": "rm-std",
                        "name": "Camera Matrimoniale Standard",
                        "capacity": 2,
                        "default_price": 95.0,
                    },
                    {
                        "room_id": "rm-dlx",
                        "name": "Junior Suite Vista Mare",
                        "capacity": 3,
                        "default_price": 160.0,
                    },
                ]
            },
        )

    respx.post(f"{TEST_BASE_URL}/property/fetch_rooms").mock(side_effect=handle_fetch_rooms)

    services = await zak_adapter.get_services(ORG_ID)
    assert len(services) == 2
    assert services[0].service_id == "rm-std"
    assert services[0].prezzo_cent == 9500
    assert services[1].service_id == "rm-dlx"
    assert services[1].categoria == "camera"

    # Verifica header x-api-key e assenza dei fittizi X-Zak-Key / X-Property-Id
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.headers.get("x-api-key") == "zak_live_api_key_xyz987"
    assert "x-zak-key" not in req.headers
    assert "x-property-id" not in req.headers


# ── 4. Verifica Disponibilità e Tariffe Dinamiche ──────────────

@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_get_availability_with_rates_and_occupancy(zak_adapter):
    """Verifica disponibilità con tariffa dinamica, ripartizione adulti/bambini e trattamento."""
    captured_payloads = []

    def handle_availability(request):
        captured_payloads.append(json.loads(request.content.decode()))
        return Response(
            200,
            json={
                "data": {
                    "available_rooms": [
                        {
                            "room_id": "rm-dlx",
                            "available_count": 2,
                            "price_cents": 18500,
                            "board": "HB",
                        }
                    ]
                }
            },
        )

    respx.post(f"{TEST_BASE_URL}/inventory/fetch_availability").mock(side_effect=handle_availability)

    query = AvailabilityQuery(
        data_inizio=date(2026, 9, 20),
        data_fine=date(2026, 9, 23),
        service_id="rm-dlx",
        coperti_o_quantita=3,
        adulti=2,
        bambini=1,
        eta_bambini=[7],
        board_type="HB",
    )
    res = await zak_adapter.get_availability(ORG_ID, query)

    assert res.success is True
    assert len(res.slots) == 1
    slot = res.slots[0]
    assert slot.disponibile is True
    assert slot.capacita_residua == 2
    assert slot.prezzo_cent == 18500
    assert slot.board_type == "HB"

    # Verifica payload KAPI inviato
    assert len(captured_payloads) == 1
    sent = captured_payloads[0]
    assert sent["date_from"] == "2026-09-20"
    assert sent["date_to"] == "2026-09-23"
    assert sent["adults"] == 2
    assert sent["children"] == 1
    assert sent["children_ages"] == [7]
    assert sent["board"] == "HB"


# ── 5. Creazione Prenotazione (create_booking via POST) ────────

@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_create_booking_success(zak_adapter):
    """Verifica creazione prenotazione con payload KAPI, trattamento e anagrafica ospite."""
    captured_payloads = []

    def handle_create(request):
        captured_payloads.append(json.loads(request.content.decode()))
        return Response(
            200,
            json={
                "data": {
                    "reservation_code": "ZAK-RES-778899",
                    "status": "confirmed",
                }
            },
        )

    respx.post(f"{TEST_BASE_URL}/reservations/create").mock(side_effect=handle_create)

    req = CreateBookingRequest(
        idempotency_key="ext-book:zak:test-1",
        customer=CustomerResult(
            customer_id="cust-1",
            nome="Giulia",
            cognome="Bianchi",
            telefono="+393401122334",
            email="giulia@example.com",
        ),
        data=date(2026, 9, 20),
        data_fine=date(2026, 9, 22),
        ora_inizio=time(14, 0),
        durata_minuti=2880,
        service_id="rm-std",
        coperti=2,
        adulti=2,
        bambini=0,
        board_type="BB",
        note="Arrivo previsto verso le 15:30",
    )

    res = await zak_adapter.create_booking(ORG_ID, req)
    assert res.success is True
    assert res.external_booking_id == "ZAK-RES-778899"
    assert res.stato == "confermata"
    assert res.sync_status == "synced"

    assert len(captured_payloads) == 1
    p = captured_payloads[0]
    assert p["date_from"] == "2026-09-20"
    assert p["date_to"] == "2026-09-22"
    assert p["nights"] == 2
    assert p["adults"] == 2
    assert p["board"] == "BB"
    assert p["customer"]["first_name"] == "Giulia"
    assert p["customer"]["last_name"] == "Bianchi"
    assert p["customer"]["phone"] == "+393401122334"


@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_create_booking_multinight_dst_safety(zak_adapter):
    """Verifica che un soggiorno multi-notte a cavallo del cambio ora legale mantenga date certe."""
    captured_payloads = []

    def handle_create(request):
        captured_payloads.append(json.loads(request.content.decode()))
        return Response(
            200,
            json={"data": {"reservation_code": "ZAK-MULTI-999", "status": "confirmed"}},
        )

    respx.post(f"{TEST_BASE_URL}/reservations/create").mock(side_effect=handle_create)

    req = CreateBookingRequest(
        idempotency_key="ext-book:zak:dst-test",
        customer=CustomerResult(
            customer_id="cust-2",
            nome="Marco",
            cognome="Rossi",
            telefono="+393409988776",
        ),
        data=date(2026, 10, 24),
        data_fine=date(2026, 10, 27),
        ora_inizio=time(15, 0),
        durata_minuti=4320,
        service_id="suite-deluxe",
        coperti=2,
    )

    res = await zak_adapter.create_booking(ORG_ID, req)
    assert res.success is True
    assert res.external_booking_id == "ZAK-MULTI-999"

    sent = captured_payloads[0]
    assert sent["date_from"] == "2026-10-24"
    assert sent["date_to"] == "2026-10-27"
    assert sent["nights"] == 3


# ── 6. Gestione Errori e Overbooking OTA ───────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_error_ota_collision_overbooking(zak_adapter):
    """Verifica che un conflitto di overbooking/canale OTA (es. Booking.com)
    venga mappato a stato='rifiutata' con error_code='slot_full'."""
    respx.post(f"{TEST_BASE_URL}/reservations/create").mock(
        return_value=Response(
            200,
            json={"error": "no_availability", "details": "Room closed due to OTA channel reservation"},
        )
    )

    req = CreateBookingRequest(
        idempotency_key="ext-book:zak:ota-conflict",
        customer=CustomerResult(
            customer_id="cust-3",
            nome="Luca",
            cognome="Verdi",
            telefono="+393405566778",
        ),
        data=date(2026, 8, 15),
        data_fine=date(2026, 8, 17),
        ora_inizio=time(14, 0),
        service_id="rm-std",
    )

    res = await zak_adapter.create_booking(ORG_ID, req)
    assert res.success is False
    assert res.stato == "rifiutata"
    assert res.error_code == "slot_full"
    assert "disponibile" in res.error_message or "OTA" in res.error_message


@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_error_auth_failure_kapi(zak_adapter):
    """Verifica gestione errore di autenticazione restituito da KAPI (es. Apy-key wrong format)."""
    respx.post(f"{TEST_BASE_URL}/reservations/create").mock(
        return_value=Response(200, json={"error": "Apy-key wrong format"})
    )

    req = CreateBookingRequest(
        idempotency_key="ext-book:zak:bad-key",
        customer=CustomerResult(
            customer_id="cust-4",
            nome="Anna",
            cognome="Neri",
            telefono="+393409999999",
        ),
        data=date(2026, 9, 20),
        ora_inizio=time(14, 0),
    )

    res = await zak_adapter.create_booking(ORG_ID, req)
    assert res.success is False
    assert res.stato == "errore"
    assert res.error_code == "authentication_failed"


@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_network_timeout(zak_adapter):
    """Verifica gestione di timeout verso kapi.wubook.net."""
    respx.post(f"{TEST_BASE_URL}/reservations/create").mock(
        side_effect=httpx.TimeoutException("Connection timed out")
    )

    req = CreateBookingRequest(
        idempotency_key="ext-book:zak:timeout",
        customer=CustomerResult(
            customer_id="cust-5",
            nome="Paolo",
            cognome="Gialli",
            telefono="+393408888888",
        ),
        data=date(2026, 9, 20),
        ora_inizio=time(14, 0),
    )

    res = await zak_adapter.create_booking(ORG_ID, req)
    assert res.success is False
    assert res.stato == "errore"
    assert res.error_code == "network_error"


# ── 7. Cancellazione Prenotazione (cancel_booking via POST) ────

@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_cancel_booking(zak_adapter):
    """Verifica cancellazione prenotazione via POST /reservations/cancel."""
    captured_payloads = []

    def handle_cancel(request):
        captured_payloads.append(json.loads(request.content.decode()))
        return Response(200, json={"data": {"reservation_code": "ZAK-RES-778899", "status": "cancelled"}})

    respx.post(f"{TEST_BASE_URL}/reservations/cancel").mock(side_effect=handle_cancel)

    req = CancelBookingRequest(
        idempotency_key="cancel:zak:test-1",
        external_booking_id="ZAK-RES-778899",
        motivo="Disdetta da cliente",
    )

    res = await zak_adapter.cancel_booking(ORG_ID, req)
    assert res.success is True
    assert res.stato == "cancellata"
    assert res.sync_status == "synced"

    assert len(captured_payloads) == 1
    assert captured_payloads[0]["reservation_code"] == "ZAK-RES-778899"


# ── 8. Recupero Anagrafica Ospite (get_customer via POST) ──────

@pytest.mark.asyncio
@respx.mock
async def test_zak_adapter_get_customer_post(zak_adapter):
    """Verifica ricerca ospite tramite POST /customers/fetch_one."""
    respx.post(f"{TEST_BASE_URL}/customers/fetch_one").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "id": "guest-101",
                    "first_name": "Mario",
                    "last_name": "Rossi",
                    "phone": "+393401234567",
                    "email": "mario.rossi@example.com",
                }
            },
        )
    )

    query = CustomerQuery(telefono="+393401234567")
    res = await zak_adapter.get_customer(ORG_ID, query)
    assert res is not None
    assert res.customer_id == "guest-101"
    assert res.nome == "Mario"
    assert res.cognome == "Rossi"


# ── 9. Risoluzione Router per Provider ZaK ────────────────────

@pytest.mark.asyncio
async def test_router_resolves_zak_adapter():
    """Verifica che BookingAdapterRouter risolva ZakAdapter da credenziali provider='zak'."""
    mock_repo = MagicMock()
    mock_repo.get_credentials = AsyncMock(
        return_value={
            "organization_id": ORG_ID,
            "provider": "zak",
            "is_active": True,
            "property_id": "hotel_bellavista",
            "api_key": "zak_token_999",
            "config": {"mode": "authoritative"},
        }
    )

    router = BookingAdapterRouter(repo=mock_repo)
    adapter, mode, config = await router.resolve_adapter(ORG_ID)

    assert isinstance(adapter, ZakAdapter)
    assert mode == BookingMode.AUTHORITATIVE
    assert adapter.property_id == "hotel_bellavista"
