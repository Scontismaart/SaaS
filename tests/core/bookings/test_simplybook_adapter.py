"""Test SimplyBookAdapter — mock HTTP con respx (Task 3).

SimplyBook.me usa JSON-RPC 2.0 su https://user-api.simplybook.me/.
Autenticazione: getToken(companyLogin, apiKey) → token da cachare (~50 min TTL).
Headers: X-Company-Login + X-Token su ogni richiesta.

Copre gli scenari critici:
1. Autenticazione getToken + caching
2. get_services() via getEventList
3. get_availability() via getStartTimeMatrix
4. create_booking() via book
5. cancel_booking() via cancelBooking (admin)
6. Rate limit (HTTP 429 + JSON-RPC -32600 "Too many requests")
7. Circuit breaker: N fallimenti → fast-fail → escalation umana
8. Token refresh su 401
9. Idempotenza applicativa (chiave locale, no replay cieco)
"""
from __future__ import annotations

import uuid
from datetime import date, time

import httpx
import pytest
import respx

from src.core.bookings.ports.base import (
    AvailabilityQuery,
    AvailabilityResult,
    BookingResult,
    BookingSystemPort,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerResult,
    ServiceItem,
)
from src.core.bookings.adapters.simplybook_adapter import (
    SimplyBookAdapter,
    SimplyBookAuthError,
    SimplyBookRateLimitError,
    SimplyBookTimeoutError,
    CircuitOpenError,
)

ORG_ID = uuid.UUID("00000000-0000-0000-0000-aaaaaaaaaaaa")

# SimplyBook JSON-RPC 2.0 endpoints
LOGIN_URL = "https://user-api.simplybook.me/login"
PUBLIC_URL = "https://user-api.simplybook.me/"
ADMIN_URL = "https://user-api.simplybook.me/admin"


def _jsonrpc_ok(result, rpc_id=1):
    """Helper per risposta JSON-RPC 2.0 con successo."""
    return {"jsonrpc": "2.0", "result": result, "id": rpc_id}


def _jsonrpc_error(code, message, rpc_id=1):
    """Helper per risposta JSON-RPC 2.0 con errore."""
    return {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": rpc_id}


@pytest.fixture
def credentials():
    return {
        "company_login": "test-company",
        "api_key": "fake-api-key-12345",
    }


@pytest.fixture
def adapter(credentials):
    return SimplyBookAdapter(
        company_login=credentials["company_login"],
        api_key=credentials["api_key"],
        timeout_seconds=4.0,
        circuit_breaker_threshold=3,  # Abbassato a 3 per test veloci
        circuit_breaker_reset_seconds=1.0,
    )


# ── 0. Soddisfa il protocollo BookingSystemPort ─────────────
class TestProtocol:
    def test_is_runtime_checkable(self, adapter):
        assert isinstance(adapter, BookingSystemPort)


# ── 1. Autenticazione: getToken ─────────────────────────────
class TestAuth:
    @respx.mock
    @pytest.mark.asyncio
    async def test_login_success_stores_token(self, adapter):
        respx.post(LOGIN_URL).respond(
            200,
            json=_jsonrpc_ok("d41d8cd98f00b204e9800998ecf8427e"),
        )
        await adapter._authenticate()
        assert adapter._token == "d41d8cd98f00b204e9800998ecf8427e"

    @respx.mock
    @pytest.mark.asyncio
    async def test_login_rpc_error_raises_auth_error(self, adapter):
        """Errore JSON-RPC -32600 su credenziali invalide."""
        respx.post(LOGIN_URL).respond(
            200,
            json=_jsonrpc_error(-32600, "Company does not exist"),
        )
        with pytest.raises(SimplyBookAuthError, match="Company does not exist"):
            await adapter._authenticate()

    @respx.mock
    @pytest.mark.asyncio
    async def test_login_http_401_raises_auth_error(self, adapter):
        """HTTP 401 diretto (es. IP bloccato)."""
        respx.post(LOGIN_URL).respond(
            401,
            json={"message": "Unauthorized"},
        )
        with pytest.raises(SimplyBookAuthError):
            await adapter._authenticate()


# ── 2. get_services() via getEventList ───────────────────────
class TestGetServices:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_services_200(self, adapter):
        # Login
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        # getEventList → JSON-RPC POST su PUBLIC_URL
        respx.post(PUBLIC_URL).respond(
            200,
            json=_jsonrpc_ok([
                {
                    "id": "101",
                    "name": "Taglio Uomo",
                    "description": "Taglio classico maschile",
                    "duration": 30,
                    "price": "15.00",
                    "currency": "EUR",
                    "categories": ["1"],
                },
                {
                    "id": "102",
                    "name": "Barba",
                    "description": "Rifinitura barba con rasoio",
                    "duration": 20,
                    "price": "10.00",
                    "currency": "EUR",
                    "categories": [],
                },
            ]),
        )
        services = await adapter.get_services(ORG_ID)
        assert len(services) == 2
        assert isinstance(services[0], ServiceItem)
        assert services[0].service_id == "101"
        assert services[0].nome == "Taglio Uomo"
        assert services[0].durata_minuti == 30
        assert services[0].prezzo_cent == 1500  # 15.00 EUR → 1500 cent


# ── 3. get_availability() via getStartTimeMatrix ─────────────
class TestGetAvailability:
    @respx.mock
    @pytest.mark.asyncio
    async def test_get_availability_200(self, adapter):
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        # getStartTimeMatrix → POST su PUBLIC_URL
        respx.post(PUBLIC_URL).respond(
            200,
            json=_jsonrpc_ok({
                "2026-09-10": ["09:00:00", "09:30:00", "10:00:00", "14:00:00"],
            }),
        )
        query = AvailabilityQuery(
            data_inizio=date(2026, 9, 10),
            data_fine=date(2026, 9, 10),
            service_id="101",
        )
        result = await adapter.get_availability(ORG_ID, query)
        assert result.success is True
        assert len(result.slots) == 4
        assert result.slots[0].ora_inizio == time(9, 0)
        assert result.slots[0].disponibile is True
        assert result.slots[0].data == date(2026, 9, 10)

    @respx.mock
    @pytest.mark.asyncio
    async def test_get_availability_empty_day(self, adapter):
        """Giorno senza slot → slots vuoti, ma successo."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).respond(
            200,
            json=_jsonrpc_ok({"2026-09-10": []}),
        )
        query = AvailabilityQuery(
            data_inizio=date(2026, 9, 10),
            data_fine=date(2026, 9, 10),
            service_id="101",
        )
        result = await adapter.get_availability(ORG_ID, query)
        assert result.success is True
        assert len(result.slots) == 0


# ── 4. create_booking() via book ─────────────────────────────
class TestCreateBooking:
    @respx.mock
    @pytest.mark.asyncio
    async def test_create_booking_200(self, adapter):
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        # book → POST su PUBLIC_URL
        respx.post(PUBLIC_URL).respond(
            200,
            json=_jsonrpc_ok({
                "id": 42,
                "hash": "abc123def",
                "code": "BK-42",
                "start_date_time": "2026-09-10 09:00:00",
            }),
        )
        req = CreateBookingRequest(
            idempotency_key="ext-book:aaa:msg-001",
            customer=CustomerResult(
                customer_id="c-1",
                nome="Mario",
                cognome="Rossi",
                telefono="393515205809",
            ),
            data=date(2026, 9, 10),
            ora_inizio=time(9, 0),
            durata_minuti=30,
            service_id="101",
        )
        result = await adapter.create_booking(ORG_ID, req)
        assert result.success is True
        assert result.external_booking_id == "42"
        assert result.stato == "confermata"
        assert result.sync_status == "synced"

    @respx.mock
    @pytest.mark.asyncio
    async def test_create_booking_slot_conflict(self, adapter):
        """Se lo slot è già occupato, SimplyBook restituisce errore RPC.
        L'adapter deve segnalare il fallimento senza crash."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).respond(
            200,
            json=_jsonrpc_error(-32600, "Selected time is not available"),
        )
        req = CreateBookingRequest(
            idempotency_key="ext-book:aaa:msg-002",
            customer=CustomerResult(
                customer_id="c-1",
                nome="Mario",
                cognome="Rossi",
                telefono="393515205809",
            ),
            data=date(2026, 9, 10),
            ora_inizio=time(9, 0),
            service_id="101",
        )
        result = await adapter.create_booking(ORG_ID, req)
        assert result.success is False
        assert result.stato == "rifiutata"
        assert "not available" in (result.error_message or "").lower()


# ── 5. cancel_booking() via cancelBooking (admin) ────────────
class TestCancelBooking:
    @respx.mock
    @pytest.mark.asyncio
    async def test_cancel_booking_200(self, adapter):
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        # cancelBooking (admin) → POST su ADMIN_URL
        respx.post(ADMIN_URL).respond(
            200,
            json=_jsonrpc_ok(True),
        )
        req = CancelBookingRequest(
            idempotency_key="ext-cancel:aaa:msg-003",
            external_booking_id="42",
            motivo="Cliente ha cambiato idea",
        )
        result = await adapter.cancel_booking(ORG_ID, req)
        assert result.success is True
        assert result.stato == "cancellata"

    @respx.mock
    @pytest.mark.asyncio
    async def test_cancel_booking_not_found(self, adapter):
        """Booking non trovato (-32080) → errore gestito, non crash."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(ADMIN_URL).respond(
            200,
            json=_jsonrpc_error(-32080, "Appointment not found"),
        )
        req = CancelBookingRequest(
            idempotency_key="ext-cancel:aaa:msg-004",
            external_booking_id="99999",
        )
        result = await adapter.cancel_booking(ORG_ID, req)
        assert result.success is False
        assert result.error_code == "not_found"


# ── 6. Rate Limit ───────────────────────────────────────────
class TestRateLimit:
    @respx.mock
    @pytest.mark.asyncio
    async def test_http_429_raises_rate_limit_error(self, adapter):
        """HTTP 429 diretto (rate limit a livello di trasporto)."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).respond(
            429,
            headers={"Retry-After": "30"},
            json={"message": "Rate limit exceeded"},
        )
        with pytest.raises(SimplyBookRateLimitError) as exc_info:
            await adapter.get_services(ORG_ID)
        assert exc_info.value.retry_after == 30

    @respx.mock
    @pytest.mark.asyncio
    async def test_rpc_too_many_requests_raises_rate_limit(self, adapter):
        """JSON-RPC -32600 con messaggio 'Too many requests'
        dev'essere trattato come rate limit, non come errore generico."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).respond(
            200,
            json=_jsonrpc_error(-32600, "Invalid request: Too many requests"),
        )
        with pytest.raises(SimplyBookRateLimitError):
            await adapter.get_services(ORG_ID)


# ── 7. Circuit Breaker: fast-fail → escalation umana ────────
class TestCircuitBreaker:
    @respx.mock
    @pytest.mark.asyncio
    async def test_timeout_increments_failure_counter(self, adapter):
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))
        with pytest.raises(SimplyBookTimeoutError):
            await adapter.get_services(ORG_ID)
        assert adapter._circuit_failure_count == 1

    @respx.mock
    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self, adapter):
        """Dopo N fallimenti consecutivi, il circuito si apre e le chiamate
        successive ricevono CircuitOpenError istantaneamente (fast-fail).
        
        Invariante piano: in modalità 'authoritative' il fast-fail porta
        SEMPRE a escalation umana (richiede_umano=True), MAI a fallback
        silenzioso su dati locali."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))

        # 3 fallimenti consecutivi (threshold=3 nel fixture)
        for _ in range(3):
            with pytest.raises(SimplyBookTimeoutError):
                await adapter.get_services(ORG_ID)

        assert adapter._circuit_is_open is True

        # La 4ª chiamata → CircuitOpenError istantaneo, nessuna HTTP
        with pytest.raises(CircuitOpenError, match="richiede_umano"):
            await adapter.get_services(ORG_ID)

    @respx.mock
    @pytest.mark.asyncio
    async def test_circuit_resets_on_success(self, adapter):
        """Un successo resetta il contatore dei fallimenti consecutivi."""
        login_route = respx.post(LOGIN_URL)
        login_route.respond(200, json=_jsonrpc_ok("tok-1"))
        public_route = respx.post(PUBLIC_URL)

        # 2 fallimenti (sotto threshold=3)
        public_route.mock(side_effect=httpx.ConnectTimeout("timeout"))
        for _ in range(2):
            with pytest.raises(SimplyBookTimeoutError):
                await adapter.get_services(ORG_ID)
        assert adapter._circuit_failure_count == 2

        # Successo → reset
        public_route.mock(side_effect=None)
        public_route.respond(200, json=_jsonrpc_ok([]))
        services = await adapter.get_services(ORG_ID)
        assert adapter._circuit_failure_count == 0
        assert adapter._circuit_is_open is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_500_counts_as_circuit_failure(self, adapter):
        """HTTP 500 incrementa il contatore del circuit breaker."""
        respx.post(LOGIN_URL).respond(200, json=_jsonrpc_ok("tok-1"))
        respx.post(PUBLIC_URL).respond(500, json={"error": "Internal"})
        with pytest.raises(SimplyBookTimeoutError):
            await adapter.get_services(ORG_ID)
        assert adapter._circuit_failure_count == 1


# ── 8. Token refresh su 401 ─────────────────────────────────
class TestTokenRefresh:
    @respx.mock
    @pytest.mark.asyncio
    async def test_401_triggers_reauth_and_retry(self, adapter):
        """Se una chiamata riceve 401, l'adapter rifà getToken e riprova
        la richiesta originale con il nuovo token — una sola volta."""
        login_route = respx.post(LOGIN_URL)
        login_route.side_effect = [
            httpx.Response(200, json=_jsonrpc_ok("tok-old")),
            httpx.Response(200, json=_jsonrpc_ok("tok-new")),
        ]
        public_route = respx.post(PUBLIC_URL)
        public_route.side_effect = [
            httpx.Response(401, json={"message": "Token expired"}),
            httpx.Response(200, json=_jsonrpc_ok([])),
        ]
        services = await adapter.get_services(ORG_ID)
        assert services == []
        assert adapter._token == "tok-new"
        # Login 2 volte (iniziale + refresh), services 2 volte
        assert login_route.call_count == 2
        assert public_route.call_count == 2

    @respx.mock
    @pytest.mark.asyncio
    async def test_401_after_refresh_raises_auth_error(self, adapter):
        """Se anche dopo il refresh il 401 persiste, solleva SimplyBookAuthError
        senza loop infiniti."""
        login_route = respx.post(LOGIN_URL)
        login_route.side_effect = [
            httpx.Response(200, json=_jsonrpc_ok("tok-old")),
            httpx.Response(200, json=_jsonrpc_ok("tok-still-bad")),
        ]
        respx.post(PUBLIC_URL).respond(
            401, json={"message": "Unauthorized"},
        )
        with pytest.raises(SimplyBookAuthError, match="Unauthorized"):
            await adapter.get_services(ORG_ID)


# ── 9. Token caching (non ri-autentica se valido) ───────────
class TestTokenCaching:
    @respx.mock
    @pytest.mark.asyncio
    async def test_cached_token_not_reauthenticated(self, adapter):
        """Dopo il primo login, le chiamate successive non richiedono
        un nuovo getToken (token cachato)."""
        login_route = respx.post(LOGIN_URL)
        login_route.respond(200, json=_jsonrpc_ok("tok-cached"))
        public_route = respx.post(PUBLIC_URL)
        public_route.respond(200, json=_jsonrpc_ok([]))

        # Due chiamate consecutive
        await adapter.get_services(ORG_ID)
        await adapter.get_services(ORG_ID)

        # Login chiamato solo 1 volta
        assert login_route.call_count == 1
        assert public_route.call_count == 2


# ── 10. Cleanup ─────────────────────────────────────────────
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close_releases_client(self, adapter):
        """L'adapter deve poter essere chiuso senza errori."""
        await adapter.close()
        assert adapter._client.is_closed
