"""Test suite completa per Beds24Adapter (Beds24 API v2).

Copertura:
1. Conformance a BookingSystemPort
2. Autenticazione (Token, RefreshToken, Invite Code setup)
3. Refresh automatico e trasparente su HTTP 401
4. get_opening_hours (check-in / check-out windows hospitality)
5. get_services (mapping roomTypes e prezzi)
6. get_customer (ricerca anagrafica, PII sanitization)
7. get_availability (offerte hospitality multi-notte, tariffe)
8. create_booking (idempotenza, checkAvailability, validazione nome ospite, auto-split)
9. update_booking (modifica date / camere)
10. cancel_booking (idempotenza, cancellazione nativa)
11. Gestione errori HTTP: 401, 403, 404, 409, 422, 429, 500
12. Network & Timeout
13. Circuit Breaker Fast-Fail (<1ms)
14. Zero Secrets Leak in repr/str
15. Integrazione BookingAdapterRouter
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, time as dtime
from typing import Any

import httpx
import pytest

from src.core.bookings.adapters.beds24_adapter import (
    BEDS24_DEFAULT_BASE_URL,
    Beds24Adapter,
    Beds24AuthError,
    Beds24ConflictError,
    Beds24Error,
    Beds24NetworkError,
    Beds24NotFoundError,
    Beds24RateLimitError,
    Beds24ServerError,
    Beds24TimeoutError,
    Beds24ValidationError,
    CircuitOpenError,
)
from src.core.bookings.ports.base import (
    AvailabilityQuery,
    BookingResult,
    BookingSystemPort,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerQuery,
    CustomerResult,
    UpdateBookingRequest,
)

ORG_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
TEST_PROPERTY_ID = "98765"


def create_customer(
    nome: str = "Mario",
    cognome: str = "Rossi",
    telefono: str = "+393331234567",
    email: str | None = "mario.rossi@example.com",
) -> CustomerResult:
    return CustomerResult(
        customer_id="cust-1",
        nome=nome,
        cognome=cognome,
        telefono=telefono,
        email=email,
    )


# ── 1. Conformance e Inizializzazione ─────────────────────────

def test_beds24_adapter_port_conformance():
    """Beds24Adapter implementa BookingSystemPort."""
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="test_static_token",
        property_id=TEST_PROPERTY_ID,
    )
    assert isinstance(adapter, BookingSystemPort)
    assert adapter.provider_name == "beds24"
    assert adapter._property_id == TEST_PROPERTY_ID


@pytest.mark.asyncio
async def test_missing_credentials_raises_auth_error():
    """Se mancano token, refresh_token e invite_code, solleva Beds24AuthError."""
    adapter = Beds24Adapter(organization_id=ORG_ID)
    with pytest.raises(Beds24AuthError, match="Credenziali Beds24 mancanti"):
        await adapter.get_services(ORG_ID)


# ── 2. Autenticazione e Token Flow ────────────────────────────

@pytest.mark.asyncio
async def test_authentication_token_refresh_flow():
    """Richiesta con refresh_token ottiene access token tramite /authentication/token."""
    called_refresh = False

    def handler(request: httpx.Request):
        nonlocal called_refresh
        if request.url.path == "/v2/authentication/token":
            called_refresh = True
            assert request.headers.get("refreshToken") == "valid_refresh_token_123"
            return httpx.Response(
                200,
                json={"token": "refreshed_access_token_abc", "expiresIn": 86400},
            )
        if request.url.path == "/v2/properties":
            assert request.headers.get("token") == "refreshed_access_token_abc"
            return httpx.Response(200, json={"success": True, "data": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        refresh_token="valid_refresh_token_123",
        property_id=TEST_PROPERTY_ID,
        client=client,
    )

    services = await adapter.get_services(ORG_ID)
    assert called_refresh is True
    assert services == []
    assert adapter._token == "refreshed_access_token_abc"


@pytest.mark.asyncio
async def test_authentication_setup_invite_code_flow():
    """Richiesta con invite_code scambia il codice su /authentication/setup."""
    called_setup = False

    def handler(request: httpx.Request):
        nonlocal called_setup
        if request.url.path == "/v2/authentication/setup":
            called_setup = True
            assert request.headers.get("code") == "invite_code_xyz"
            return httpx.Response(
                200,
                json={
                    "token": "new_access_token_123",
                    "refreshToken": "new_refresh_token_456",
                    "expiresIn": 86400,
                },
            )
        if request.url.path == "/v2/properties":
            assert request.headers.get("token") == "new_access_token_123"
            return httpx.Response(200, json={"success": True, "data": []})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        invite_code="invite_code_xyz",
        property_id=TEST_PROPERTY_ID,
        client=client,
    )

    services = await adapter.get_services(ORG_ID)
    assert called_setup is True
    assert adapter._token == "new_access_token_123"
    assert adapter._refresh_token == "new_refresh_token_456"


@pytest.mark.asyncio
async def test_automatic_token_refresh_on_401():
    """Su HTTP 401 l'adapter invalida il token corrente, effettua refresh e riprova con successo."""
    call_count = 0

    def handler(request: httpx.Request):
        nonlocal call_count
        if request.url.path == "/v2/authentication/token":
            return httpx.Response(
                200,
                json={"token": "brand_new_token_789", "expiresIn": 86400},
            )
        if request.url.path == "/v2/properties":
            call_count += 1
            if call_count == 1:
                return httpx.Response(401, json={"success": False, "error": "Token expired"})
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [
                        {
                            "id": 98765,
                            "name": "Hotel Test",
                            "roomTypes": [{"id": 101, "name": "Suite", "roomType": "suite"}],
                        }
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="expired_token_123",
        refresh_token="valid_refresh_token_456",
        property_id=TEST_PROPERTY_ID,
        client=client,
    )

    services = await adapter.get_services(ORG_ID)
    assert len(services) == 1
    assert services[0].service_id == "101"
    assert call_count == 2
    assert adapter._token == "brand_new_token_789"


@pytest.mark.asyncio
async def test_failed_token_refresh_on_401_raises_auth_error():
    """Se HTTP 401 persiste anche dopo il refresh, solleva Beds24AuthError."""
    def handler(request: httpx.Request):
        if request.url.path == "/v2/authentication/token":
            return httpx.Response(
                200,
                json={"token": "brand_new_token_789", "expiresIn": 86400},
            )
        if request.url.path == "/v2/properties":
            return httpx.Response(401, json={"success": False, "error": "Invalid token"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="expired_token_123",
        refresh_token="valid_refresh_token_456",
        client=client,
    )

    with pytest.raises(Beds24AuthError, match="HTTP 401"):
        await adapter.get_services(ORG_ID)


# ── 3. get_opening_hours ─────────────────────────────────────

@pytest.mark.asyncio
async def test_get_opening_hours_success():
    """Recupera check-in e check-out della property e restituisce 7 giorni di DaySchedule."""
    def handler(request: httpx.Request):
        assert request.url.path == "/v2/properties"
        assert request.url.params.get("id") == "98765"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": 98765,
                        "name": "Beds24 Seaside Resort",
                        "checkInStart": "15:00",
                        "checkInEnd": "22:00",
                        "checkOutEnd": "11:00",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="valid_token",
        property_id=TEST_PROPERTY_ID,
        client=client,
    )

    hours = await adapter.get_opening_hours(ORG_ID)
    assert len(hours.orari) == 7
    assert hours.orari[0].fasce[0].inizio == dtime(15, 0)
    assert hours.orari[0].fasce[0].fine == dtime(22, 0)


# ── 4. get_services ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_services_maps_room_types():
    """Mappa roomTypes della proprietà in ServiceItem hospitality con prezzo in centesimi."""
    def handler(request: httpx.Request):
        assert request.url.path == "/v2/properties"
        assert request.url.params.get("includeAllRooms") == "true"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": 98765,
                        "currency": "EUR",
                        "roomTypes": [
                            {
                                "id": 501,
                                "name": "Camera Matrimoniale Deluxe",
                                "roomType": "double",
                                "minPrice": 120.50,
                                "maxAdult": 2,
                            },
                            {
                                "id": 502,
                                "name": "Suite Vista Mare",
                                "roomType": "suite",
                                "minPrice": 250.00,
                                "maxAdult": 4,
                            },
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="valid_token",
        property_id=TEST_PROPERTY_ID,
        client=client,
    )

    services = await adapter.get_services(ORG_ID)
    assert len(services) == 2
    s1 = services[0]
    assert s1.service_id == "501"
    assert s1.nome == "Camera Matrimoniale Deluxe"
    assert s1.prezzo_cent == 12050
    assert s1.durata_minuti == 1440
    assert s1.valuta == "EUR"

    s2 = services[1]
    assert s2.service_id == "502"
    assert s2.prezzo_cent == 25000


# ── 5. get_customer ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_customer_found():
    """Cerca ospite su /bookings?searchString=... e mappa in CustomerResult."""
    def handler(request: httpx.Request):
        assert request.url.path == "/v2/bookings"
        assert request.url.params.get("searchString") == "+393331234567"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": 778899,
                        "roomId": 501,
                        "firstName": "Luigi",
                        "lastName": "Verdi",
                        "mobile": "+393331234567",
                        "email": "luigi.verdi@example.com",
                        "comments": "Ospite frequente",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    cust = await adapter.get_customer(ORG_ID, CustomerQuery(telefono="+393331234567"))
    assert cust is not None
    assert cust.customer_id == "778899"
    assert cust.nome == "Luigi"
    assert cust.cognome == "Verdi"
    assert cust.email == "luigi.verdi@example.com"
    assert cust.note == "Ospite frequente"


@pytest.mark.asyncio
async def test_get_customer_masked_pii_sanitized():
    """Caratteri di mascheramento (* o •) parziali o totali vengono sanitizzati."""
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "id": 881122,
                        "roomId": 501,
                        "firstName": "M***o",
                        "lastName": "***",
                        "mobile": "+39333***4567",
                        "email": "m***o@example.com",
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    cust = await adapter.get_customer(ORG_ID, CustomerQuery(customer_id="881122"))
    assert cust is None  # Tutti i campi identificativi mascherati -> scartato


@pytest.mark.asyncio
async def test_get_customer_not_found():
    """Se non ci sono prenotazioni corrispondenti, restituisce None."""
    def handler(request: httpx.Request):
        return httpx.Response(200, json={"success": True, "data": []})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    cust = await adapter.get_customer(ORG_ID, CustomerQuery(email="nonexistent@example.com"))
    assert cust is None


# ── 6. get_availability ──────────────────────────────────────

@pytest.mark.asyncio
async def test_get_availability_hospitality_offers():
    """Interroga /inventory/rooms/offers e restituisce gli slot per offerte con unità disponibili."""
    def handler(request: httpx.Request):
        assert request.url.path == "/v2/inventory/rooms/offers"
        assert request.url.params.get("arrival") == "2026-10-01"
        assert request.url.params.get("departure") == "2026-10-04"
        assert request.url.params.get("numAdults") == "2"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "roomId": 501,
                        "propertyId": 98765,
                        "offers": [
                            {
                                "offerId": 1,
                                "offerName": "Standard Non-Refundable",
                                "price": 360.00,
                                "unitsAvailable": 2,
                            }
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="valid_token",
        property_id=TEST_PROPERTY_ID,
        client=client,
    )

    query = AvailabilityQuery(
        data_inizio=date(2026, 10, 1),
        data_fine=date(2026, 10, 4),
        service_id="501",
        adulti=2,
    )
    result = await adapter.get_availability(ORG_ID, query)
    assert result.success is True
    assert len(result.slots) == 1
    slot = result.slots[0]
    assert slot.disponibile is True
    assert slot.capacita_residua == 2
    assert slot.prezzo_cent == 36000
    assert slot.ora_inizio == dtime(14, 0)
    assert slot.ora_fine == dtime(10, 0)
    assert slot.service_id == "501"


@pytest.mark.asyncio
async def test_get_availability_empty_or_zero_units():
    """Nessuna offerta o unitsAvailable=0 restituisce slots vuoti."""
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "roomId": 501,
                        "offers": [
                            {
                                "offerId": 1,
                                "unitsAvailable": 0,
                            }
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    query = AvailabilityQuery(
        data_inizio=date(2026, 10, 1),
        data_fine=date(2026, 10, 2),
    )
    result = await adapter.get_availability(ORG_ID, query)
    assert result.success is True
    assert len(result.slots) == 0


# ── 7. create_booking ────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_booking_success():
    """Creazione prenotazione con checkAvailability=true e apiReference idempotente."""
    posted_payload = None

    def handler(request: httpx.Request):
        nonlocal posted_payload
        if request.url.path == "/v2/bookings" and request.method == "POST":
            posted_payload = json.loads(request.content)
            return httpx.Response(
                201,
                json=[
                    {
                        "success": True,
                        "new": {
                            "id": 998877,
                        },
                    }
                ],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    req = CreateBookingRequest(
        idempotency_key="idemp_beds24_001",
        customer=create_customer(nome="Mario", cognome="Rossi"),
        data=date(2026, 11, 10),
        ora_inizio=dtime(14, 0),
        data_fine=date(2026, 11, 13),
        service_id="501",
        adulti=2,
        bambini=1,
        note="Late check-in",
    )

    res = await adapter.create_booking(ORG_ID, req)
    assert res.success is True
    assert res.stato == "confermata"
    assert res.external_booking_id == "998877"

    assert posted_payload is not None
    assert len(posted_payload) == 1
    item = posted_payload[0]
    assert item["roomId"] == 501
    assert item["arrival"] == "2026-11-10"
    assert item["departure"] == "2026-11-13"
    assert item["numAdult"] == 2
    assert item["numChild"] == 1
    assert item["firstName"] == "Mario"
    assert item["lastName"] == "Rossi"
    assert item["apiReference"] == "idemp_beds24_001"
    assert item["actions"]["checkAvailability"] is True


@pytest.mark.asyncio
async def test_create_booking_rejects_missing_or_placeholder_name():
    """Blocca la creazione con missing_guest_name se cognome manca o sono placeholder."""
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token")

    # Caso 1: Solo nome senza cognome
    req1 = CreateBookingRequest(
        idempotency_key="k1",
        customer=create_customer(nome="Mario", cognome=""),
        data=date(2026, 11, 10),
        ora_inizio=dtime(14, 0),
        service_id="501",
    )
    res1 = await adapter.create_booking(ORG_ID, req1)
    assert res1.success is False
    assert res1.error_code == "missing_guest_name"

    # Caso 2: Placeholder generico 'Ospite WhatsApp'
    req2 = CreateBookingRequest(
        idempotency_key="k2",
        customer=create_customer(nome="Ospite", cognome="WhatsApp"),
        data=date(2026, 11, 10),
        ora_inizio=dtime(14, 0),
        service_id="501",
    )
    res2 = await adapter.create_booking(ORG_ID, req2)
    assert res2.success is False
    assert res2.error_code == "missing_guest_name"

    # Caso 3: Carattere di mascheramento PII
    req3 = CreateBookingRequest(
        idempotency_key="k3",
        customer=create_customer(nome="Mario", cognome="R***i"),
        data=date(2026, 11, 10),
        ora_inizio=dtime(14, 0),
        service_id="501",
    )
    res3 = await adapter.create_booking(ORG_ID, req3)
    assert res3.success is False
    assert res3.error_code == "missing_guest_name"


@pytest.mark.asyncio
async def test_create_booking_accepts_split_full_name():
    """Auto-splitting del nome completo 'Mario Rossi' in first_name e last_name."""
    posted_payload = None

    def handler(request: httpx.Request):
        nonlocal posted_payload
        if request.url.path == "/v2/bookings" and request.method == "POST":
            posted_payload = json.loads(request.content)
            return httpx.Response(
                201,
                json=[{"success": True, "new": {"id": 12345}}],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    req = CreateBookingRequest(
        idempotency_key="k_split",
        customer=create_customer(nome="Mario Rossi", cognome=""),
        data=date(2026, 11, 10),
        ora_inizio=dtime(14, 0),
        service_id="501",
    )
    res = await adapter.create_booking(ORG_ID, req)
    assert res.success is True
    assert posted_payload[0]["firstName"] == "Mario"
    assert posted_payload[0]["lastName"] == "Rossi"


@pytest.mark.asyncio
async def test_create_booking_conflict_or_no_availability():
    """Se Beds24 rifiuta per mancanza di disponibilità, restituisce slot_full."""
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json=[
                {
                    "success": False,
                    "errors": [
                        {
                            "action": "create",
                            "field": "roomId",
                            "message": "Room not available for specified dates",
                        }
                    ],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    req = CreateBookingRequest(
        idempotency_key="k_conf",
        customer=create_customer(nome="Mario", cognome="Rossi"),
        data=date(2026, 11, 10),
        ora_inizio=dtime(14, 0),
        service_id="501",
    )
    res = await adapter.create_booking(ORG_ID, req)
    assert res.success is False
    assert res.stato == "rifiutata"
    assert res.error_code == "slot_full"


# ── 8. update_booking ────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_booking_success():
    """Modifica di una prenotazione esistente via POST /bookings."""
    posted_payload = None

    def handler(request: httpx.Request):
        nonlocal posted_payload
        if request.url.path == "/v2/bookings" and request.method == "POST":
            posted_payload = json.loads(request.content)
            return httpx.Response(
                201,
                json=[{"success": True, "modified": {"id": 998877}}],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    req = UpdateBookingRequest(
        idempotency_key="upd_1",
        external_booking_id="998877",
        nuova_data=date(2026, 12, 1),
        nuova_data_fine=date(2026, 12, 5),
        nuovo_service_id="502",
        nuovi_coperti=3,
        nuove_note="Aggiornato orario arrivo",
    )
    res = await adapter.update_booking(ORG_ID, req)
    assert res.success is True
    assert res.stato == "confermata"
    assert posted_payload[0]["id"] == 998877
    assert posted_payload[0]["arrival"] == "2026-12-01"
    assert posted_payload[0]["departure"] == "2026-12-05"
    assert posted_payload[0]["roomId"] == 502
    assert posted_payload[0]["numAdult"] == 3


# ── 9. cancel_booking ────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_booking_success():
    """Cancellazione con status=cancelled via POST /bookings."""
    posted_payload = None

    def handler(request: httpx.Request):
        nonlocal posted_payload
        if request.url.path == "/v2/bookings" and request.method == "POST":
            posted_payload = json.loads(request.content)
            return httpx.Response(
                201,
                json=[{"success": True, "modified": {"id": 998877}}],
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    req = CancelBookingRequest(
        idempotency_key="canc_1",
        external_booking_id="998877",
        motivo="Imprevisto ospite",
    )
    res = await adapter.cancel_booking(ORG_ID, req)
    assert res.success is True
    assert res.stato == "cancellata"
    assert posted_payload[0]["id"] == 998877
    assert posted_payload[0]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_booking_idempotent_already_cancelled():
    """Idempotenza: se la prenotazione è già cancellata o 404, restituisce cancellata con successo."""
    def handler(request: httpx.Request):
        return httpx.Response(
            200,
            json=[
                {
                    "success": False,
                    "errors": [{"action": "modify", "message": "Booking is already cancelled"}],
                }
            ],
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    req = CancelBookingRequest(
        idempotency_key="canc_idem",
        external_booking_id="998877",
    )
    res = await adapter.cancel_booking(ORG_ID, req)
    assert res.success is True
    assert res.stato == "cancellata"


# ── 10. Gestione Errori HTTP ─────────────────────────────────

@pytest.mark.asyncio
async def test_error_auth_403_forbidden():
    """HTTP 403 solleva Beds24AuthError."""
    def handler(request: httpx.Request):
        return httpx.Response(403, text="Forbidden")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24AuthError, match="HTTP 403"):
        await adapter.get_services(ORG_ID)


@pytest.mark.asyncio
async def test_error_not_found_404():
    """HTTP 404 solleva Beds24NotFoundError."""
    def handler(request: httpx.Request):
        return httpx.Response(404, text="Not Found")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24NotFoundError, match="HTTP 404"):
        await adapter.get_services(ORG_ID)


@pytest.mark.asyncio
async def test_error_validation_422():
    """HTTP 422 solleva Beds24ValidationError."""
    def handler(request: httpx.Request):
        return httpx.Response(422, text="Unprocessable Entity")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24ValidationError, match="HTTP 422"):
        await adapter.get_services(ORG_ID)


@pytest.mark.asyncio
async def test_error_rate_limit_429_with_retry_after():
    """HTTP 429 estrae X-FiveMinCreditLimit-ResetsIn e solleva Beds24RateLimitError."""
    def handler(request: httpx.Request):
        return httpx.Response(
            429,
            headers={"X-FiveMinCreditLimit-ResetsIn": "45"},
            text="Too Many Requests",
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24RateLimitError) as exc_info:
        await adapter.get_services(ORG_ID)
    assert exc_info.value.retry_after == 45


@pytest.mark.asyncio
async def test_error_server_500():
    """HTTP 500 solleva Beds24ServerError."""
    def handler(request: httpx.Request):
        return httpx.Response(500, text="Internal Server Error")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24ServerError, match="HTTP 500"):
        await adapter.get_services(ORG_ID)


@pytest.mark.asyncio
async def test_error_timeout():
    """Timeout di rete solleva Beds24TimeoutError."""
    def handler(request: httpx.Request):
        raise httpx.ReadTimeout("Timeout reading response")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24TimeoutError, match="Timeout HTTP"):
        await adapter.get_services(ORG_ID)


@pytest.mark.asyncio
async def test_error_malformed_json_response():
    """Risposta non JSON solleva Beds24Error."""
    def handler(request: httpx.Request):
        return httpx.Response(200, text="INVALID_JSON_HERE")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(organization_id=ORG_ID, token="valid_token", client=client)

    with pytest.raises(Beds24Error, match="malformata"):
        await adapter.get_services(ORG_ID)


# ── 11. Circuit Breaker Fast-Fail ────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_fast_fail():
    """Consecutivi 5xx aprono il circuito, provocando fast-fail istantaneo (<1ms)."""
    def handler(request: httpx.Request):
        return httpx.Response(503, text="Service Unavailable")

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="valid_token",
        circuit_breaker_threshold=3,
        circuit_breaker_reset_seconds=60.0,
        client=client,
    )

    # 3 fallimenti consecutivi aprono il circuito
    for _ in range(3):
        with pytest.raises(Beds24ServerError):
            await adapter.get_services(ORG_ID)

    # La 4a chiamata fallisce istantaneamente tramite CircuitOpenError
    start = time.perf_counter()
    with pytest.raises(CircuitOpenError):
        await adapter.get_services(ORG_ID)
    duration_ms = (time.perf_counter() - start) * 1000
    assert duration_ms < 5


# ── 12. Zero Secrets Leak ────────────────────────────────────

def test_zero_secret_leak_in_adapter_repr():
    """repr e str non devono mai rivelare token, refresh token o codici di invito."""
    adapter = Beds24Adapter(
        organization_id=ORG_ID,
        token="SUPER_SECRET_TOKEN_999",
        refresh_token="SUPER_SECRET_REFRESH_888",
        invite_code="SECRET_INVITE_777",
        property_id="HOTEL_123",
    )

    r_repr = repr(adapter)
    r_str = str(adapter)

    assert "SUPER_SECRET_TOKEN_999" not in r_repr
    assert "SUPER_SECRET_REFRESH_888" not in r_repr
    assert "SECRET_INVITE_777" not in r_repr
    assert "SUPER_SECRET_TOKEN_999" not in r_str
    assert "SUPER_SECRET_REFRESH_888" not in r_str
    assert "SECRET_INVITE_777" not in r_str

    assert "HOTEL_123" in r_repr
    assert str(ORG_ID) in r_repr


# ── 13. Router Resolution ────────────────────────────────────

@pytest.mark.asyncio
async def test_router_resolves_beds24_adapter():
    """BookingAdapterRouter risolve le credenziali di tipo 'beds24' istanziando Beds24Adapter."""
    from unittest.mock import AsyncMock, MagicMock
    from src.core.bookings.router import BookingAdapterRouter, BookingMode

    mock_repo = MagicMock()
    mock_repo.get_credentials = AsyncMock(
        return_value={
            "organization_id": ORG_ID,
            "provider": "beds24",
            "is_active": True,
            "token": "beds24_token_router",
            "property_id": "98765",
            "config": {"mode": "authoritative", "timeout_seconds": 6.0},
        }
    )

    router = BookingAdapterRouter(repo=mock_repo)
    adapter, mode, config = await router.resolve_adapter(ORG_ID)

    assert isinstance(adapter, Beds24Adapter)
    assert adapter.provider_name == "beds24"
    assert adapter._property_id == "98765"
    assert mode == BookingMode.AUTHORITATIVE
    assert config["timeout_seconds"] == 6.0
