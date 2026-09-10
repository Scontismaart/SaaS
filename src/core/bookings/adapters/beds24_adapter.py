"""Beds24Adapter — Integrazione hardened con Beds24 API v2 (Hospitality PMS).

Protocollo: Beds24 REST API v2 su HTTPS.
Base URL: https://api.beds24.com/v2
Specifica: apiV2.yaml / OpenAPI 3.0

Mappatura Risorse di Dominio (Hospitality PMS):
- Property                <-> Beds24 Property (GET /properties?id={id})
- ServiceItem             <-> Beds24 Room Type / Room (GET /properties?includeAllRooms=true)
- AvailabilityQuery       <-> Beds24 Room Offers (GET /inventory/rooms/offers)
- CustomerResult          <-> Beds24 Guest Booking (GET /bookings?searchString={q}&includeGuests=true)
- CreateBookingRequest    <-> Beds24 Booking Create (POST /bookings con checkAvailability=true)
- UpdateBookingRequest    <-> Beds24 Booking Amend (POST /bookings con id)
- CancelBookingRequest    <-> Beds24 Booking Cancel (POST /bookings con id e status=cancelled)

Autenticazione & Token Lifecycle:
- Gestione token Beds24 API v2 via `GET /authentication/token` (con refreshToken) o `GET /authentication/setup` (con invite code).
- Caching token in-memory con scadenza e lock asincrono (double-checked locking) anti token-storm.
- Refresh automatico e trasparente su HTTP 401.

Resilienza e Sicurezza:
- Circuit breaker integrato con fast-fail istantaneo (<1ms) e soglia configurabile.
- Rate limiting conforme agli header Beds24 (X-FiveMinCreditLimit-ResetsIn e Retry-After).
- Idempotenza a livello provider tramite popolamento di `apiReference` (idempotency key).
- Invariante #10 (Zero Secrets Logging): token, refresh_token e codici di invito non vengono mai loggati o esposti in repr.
- PII Sanitization: rilevamento mascheramento (* o •) e validazione rigorosa nome ospite (blocco placeholder).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Awaitable, Callable

import httpx

from src.core.bookings.adapters.simplybook_adapter import CircuitOpenError
from src.core.bookings.identity import is_synthetic_email
from src.core.bookings.ports.base import (
    AvailabilityQuery,
    AvailabilityResult,
    BookingResult,
    BookingSystemPort,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerQuery,
    CustomerResult,
    DaySchedule,
    OpeningHoursResult,
    ServiceItem,
    SlotAvailability,
    TimeRange,
    UpdateBookingRequest,
)

logger = logging.getLogger(__name__)

BEDS24_DEFAULT_BASE_URL = "https://api.beds24.com/v2"
_SERVER_ERROR_CODES = {500, 502, 503, 504}
_GENERIC_NAME_PLACEHOLDERS = frozenset(
    {"ospite", "whatsapp", "guest", "unknown", "cliente", "utente", "anonimo"}
)


# ── Eccezioni di Dominio Beds24 ────────────────────────────────

class Beds24Error(Exception):
    """Eccezione base per errori del client Beds24."""


class Beds24AuthError(Beds24Error):
    """Autenticazione fallita (HTTP 401 o 403) o credenziali/token invalidi."""


class Beds24NotFoundError(Beds24Error):
    """Risorsa non trovata (HTTP 404)."""


class Beds24ConflictError(Beds24Error):
    """Conflitto di disponibilità, overbooking o lock unità (HTTP 409)."""


class Beds24ValidationError(Beds24Error):
    """Payload non valido o rifiutato dalla validazione Beds24 (HTTP 422 o errore API)."""


class Beds24RateLimitError(Beds24Error):
    """Rate limit o credito API rolling 5 minuti esaurito (HTTP 429)."""

    def __init__(self, message: str = "Rate limit superato per Beds24", retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class Beds24ServerError(Beds24Error):
    """Errore 5xx lato server Beds24."""


class Beds24TimeoutError(Beds24Error):
    """Timeout di rete verso le API Beds24."""


class Beds24NetworkError(Beds24Error):
    """Errore di connessione o socket verso Beds24."""


# ── Adapter Principale ────────────────────────────────────────

class Beds24Adapter(BookingSystemPort):
    """Adapter conforme a BookingSystemPort per Beds24 PMS (Hospitality)."""

    def __init__(
        self,
        organization_id: uuid.UUID | str,
        token: str | None = None,
        refresh_token: str | None = None,
        invite_code: str | None = None,
        property_id: int | str | None = None,
        base_url: str = BEDS24_DEFAULT_BASE_URL,
        timeout_seconds: float = 8.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: float = 60.0,
        default_timezone: str = "Europe/Rome",
        client: httpx.AsyncClient | None = None,
        on_token_refreshed: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        initial_expires_at: float | None = None,
    ):
        if not organization_id:
            raise ValueError("organization_id obbligatorio per Beds24Adapter")

        self.organization_id = str(organization_id)
        self.provider_name = "beds24"
        self._property_id = str(property_id).strip() if property_id is not None else None
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout_seconds)
        self._default_timezone = default_timezone
        self._on_token_refreshed = on_token_refreshed

        # Credenziali e stato token
        self._token: str | None = token.strip() if token and token.strip() else None
        self._refresh_token: str | None = (
            refresh_token.strip() if refresh_token and refresh_token.strip() else None
        )
        self._invite_code: str | None = (
            invite_code.strip() if invite_code and invite_code.strip() else None
        )
        self._token_expires_at: float | None = (
            float(initial_expires_at) if initial_expires_at is not None else None
        )
        self._auth_lock = asyncio.Lock()

        # Circuit breaker
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_reset_seconds = circuit_breaker_reset_seconds
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        self._circuit_opened_at: float | None = None

        # Client HTTP
        self._client = client or httpx.AsyncClient(timeout=self._timeout)
        self._owns_client = client is None

    # ── Circuit Breaker ──────────────────────────────────────────

    def _check_circuit_breaker(self) -> None:
        """Verifica se il circuit breaker è aperto (fast-fail <1ms)."""
        if self._circuit_is_open:
            if (
                self._circuit_opened_at
                and (time.time() - self._circuit_opened_at) > self._circuit_breaker_reset_seconds
            ):
                # Half-open: permetti una chiamata di prova
                self._circuit_is_open = False
                self._circuit_failure_count = 0
                self._circuit_opened_at = None
                logger.info(
                    "Circuit breaker Beds24 reimpostato a half-open per org %s dopo cooldown",
                    self.organization_id,
                )
            else:
                raise CircuitOpenError(
                    f"Circuit breaker Beds24 aperto per org {self.organization_id} "
                    f"dopo {self._circuit_failure_count} fallimenti consecutivi. Fast-fail immediato."
                )

    def _record_circuit_failure(self) -> None:
        """Registra un fallimento critico e apre il circuito se superata la soglia."""
        self._circuit_failure_count += 1
        if self._circuit_failure_count >= self._circuit_breaker_threshold:
            self._circuit_is_open = True
            self._circuit_opened_at = time.time()
            logger.error(
                "Circuit breaker Beds24 APERTO per org %s: soglia %d fallimenti superata.",
                self.organization_id,
                self._circuit_breaker_threshold,
            )

    def _record_circuit_success(self) -> None:
        """Reimposta il circuit breaker a seguito di una risposta valida."""
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        self._circuit_opened_at = None

    # ── Token Lifecycle & Management ─────────────────────────────

    async def _get_access_token(self, force_refresh: bool = False) -> str:
        """Recupera un access token valido, effettuando il refresh se necessario.
        
        Utilizza Double-Checked Locking su asyncio.Lock per evitare race conditions.
        """
        now = time.time()
        clock_skew = 60.0

        if not force_refresh and self._token:
            if self._token_expires_at is None or (self._token_expires_at - now) > clock_skew:
                return self._token

        async with self._auth_lock:
            # Second check dopo l'acquisizione del lock
            now = time.time()
            if not force_refresh and self._token:
                if self._token_expires_at is None or (self._token_expires_at - now) > clock_skew:
                    return self._token

            # Se abbiamo un refresh token, usiamolo su /authentication/token
            if self._refresh_token:
                url = f"{self._base_url}/authentication/token"
                headers = {
                    "Accept": "application/json",
                    "refreshToken": self._refresh_token,
                }
                try:
                    resp = await self._client.get(url, headers=headers)
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                    raise Beds24TimeoutError(f"Timeout durante token refresh Beds24: {exc}") from exc
                except httpx.RequestError as exc:
                    raise Beds24NetworkError(f"Errore di rete durante token refresh Beds24: {exc}") from exc

                if resp.status_code == 401 or resp.status_code == 403:
                    raise Beds24AuthError("Refresh token Beds24 non valido o scaduto (HTTP 401/403)")
                if resp.status_code in _SERVER_ERROR_CODES:
                    raise Beds24ServerError(f"Errore server durante token refresh Beds24 (HTTP {resp.status_code})")
                if resp.status_code != 200:
                    raise Beds24AuthError(f"Errore inatteso token refresh Beds24: HTTP {resp.status_code}")

                try:
                    data = resp.json()
                except Exception as exc:
                    raise Beds24Error("Risposta malformata da /authentication/token Beds24") from exc

                token_val = data.get("token")
                if not token_val:
                    raise Beds24AuthError("Risposta token refresh Beds24 priva del campo 'token'")

                expires_in = data.get("expiresIn", 86400)
                self._token = token_val
                self._token_expires_at = time.time() + float(expires_in)

                if self._on_token_refreshed:
                    try:
                        await self._on_token_refreshed({
                            "token": self._token,
                            "expires_at": self._token_expires_at,
                            "refresh_token": self._refresh_token,
                        })
                    except Exception as exc:
                        logger.warning("Callback on_token_refreshed Beds24 fallita per org %s: %s", self.organization_id, exc)

                return self._token

            # Se abbiamo solo invite_code, scambiamolo via /authentication/setup
            if self._invite_code:
                url = f"{self._base_url}/authentication/setup"
                headers = {
                    "Accept": "application/json",
                    "code": self._invite_code,
                }
                try:
                    resp = await self._client.get(url, headers=headers)
                except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                    raise Beds24TimeoutError(f"Timeout durante token setup Beds24: {exc}") from exc
                except httpx.RequestError as exc:
                    raise Beds24NetworkError(f"Errore di rete durante token setup Beds24: {exc}") from exc

                if resp.status_code != 200:
                    raise Beds24AuthError(f"Errore durante setup invite code Beds24: HTTP {resp.status_code}")

                try:
                    data = resp.json()
                except Exception as exc:
                    raise Beds24Error("Risposta malformata da /authentication/setup Beds24") from exc

                self._token = data.get("token")
                self._refresh_token = data.get("refreshToken")
                expires_in = data.get("expiresIn", 86400)
                self._token_expires_at = time.time() + float(expires_in)

                if self._on_token_refreshed:
                    try:
                        await self._on_token_refreshed({
                            "token": self._token,
                            "expires_at": self._token_expires_at,
                            "refresh_token": self._refresh_token,
                        })
                    except Exception as exc:
                        logger.warning("Callback on_token_refreshed Beds24 fallita: %s", exc)

                if not self._token:
                    raise Beds24AuthError("Risposta setup Beds24 priva del campo 'token'")

                return self._token

            # Se abbiamo un token statico già configurato
            if self._token:
                return self._token

            raise Beds24AuthError(
                f"Credenziali Beds24 mancanti per org {self.organization_id}: specificare token, refresh_token o invite_code"
            )

    # ── Centralized HTTP Dispatcher ──────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: Any = None,
        is_retry: bool = False,
    ) -> Any:
        """Invia una richiesta HTTP verso Beds24 gestendo auth, circuit breaker, rate limit ed errori."""
        self._check_circuit_breaker()

        token = await self._get_access_token()
        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "token": token,
        }

        try:
            resp = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
            )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            self._record_circuit_failure()
            raise Beds24TimeoutError(f"Timeout HTTP verso Beds24 ({method} {path}): {exc}") from exc
        except httpx.RequestError as exc:
            self._record_circuit_failure()
            raise Beds24NetworkError(f"Errore di rete verso Beds24 ({method} {path}): {exc}") from exc

        # Gestione HTTP 401 con refresh trasparente (1 solo retry)
        if resp.status_code == 401:
            if not is_retry and (self._refresh_token or self._invite_code):
                logger.info(
                    "Token Beds24 scaduto o revocato (HTTP 401) per org %s: tentativo di refresh automatico...",
                    self.organization_id,
                )
                self._token = None
                await self._get_access_token(force_refresh=True)
                return await self._request(
                    method=method,
                    path=path,
                    params=params,
                    json_data=json_data,
                    is_retry=True,
                )
            self._record_circuit_failure()
            raise Beds24AuthError(f"Autenticazione fallita su Beds24 ({method} {path}): HTTP 401")

        # Gestione HTTP 403 Forbidden
        if resp.status_code == 403:
            raise Beds24AuthError(f"Permessi insufficienti o accesso negato su Beds24 ({method} {path}): HTTP 403")

        # Gestione HTTP 404 Not Found
        if resp.status_code == 404:
            raise Beds24NotFoundError(f"Risorsa non trovata su Beds24 ({method} {path}): HTTP 404")

        # Gestione HTTP 409 Conflict
        if resp.status_code == 409:
            raise Beds24ConflictError(f"Conflitto di prenotazione o disponibilità su Beds24: HTTP 409")

        # Gestione HTTP 422 Unprocessable Entity
        if resp.status_code == 422:
            raise Beds24ValidationError(f"Payload rifiutato dalla validazione Beds24 (HTTP 422): {resp.text}")

        # Gestione HTTP 429 Rate Limit
        if resp.status_code == 429:
            retry_after_str = (
                resp.headers.get("X-FiveMinCreditLimit-ResetsIn")
                or resp.headers.get("Retry-After")
                or "60"
            )
            try:
                retry_after = max(1, int(float(retry_after_str)))
            except (ValueError, TypeError):
                retry_after = 60
            raise Beds24RateLimitError(
                f"Rate limit o limite crediti Beds24 raggiunto per org {self.organization_id}. Attesa: {retry_after}s",
                retry_after=retry_after,
            )

        # Gestione errori server 5xx
        if resp.status_code in _SERVER_ERROR_CODES:
            self._record_circuit_failure()
            raise Beds24ServerError(f"Errore interno server Beds24 ({method} {path}): HTTP {resp.status_code}")

        # Parsing JSON di risposta
        try:
            body = resp.json()
        except Exception as exc:
            self._record_circuit_failure()
            raise Beds24Error(f"Risposta malformata da Beds24 ({method} {path}): JSON non valido") from exc

        # Se Beds24 restituisce un payload d'errore applicativo {"success": false, "code": 400, "error": "..."}
        if isinstance(body, dict) and body.get("success") is False:
            err_msg = body.get("error", "Errore API generico")
            code = body.get("code")
            if code == 401 or "unauthorized" in err_msg.lower():
                raise Beds24AuthError(f"Beds24 API Auth Error: {err_msg}")
            if code == 404 or "not found" in err_msg.lower():
                raise Beds24NotFoundError(f"Beds24 API Not Found: {err_msg}")
            if "not available" in err_msg.lower() or "availability" in err_msg.lower():
                raise Beds24ConflictError(f"Beds24 API Conflict: {err_msg}")
            raise Beds24ValidationError(f"Beds24 API Error ({code}): {err_msg}")

        # Risposta valida: reset circuit breaker
        self._record_circuit_success()
        return body

    # ── Validazione Dati Ospite & Sanitizzazione PII ───────────────

    def _extract_and_validate_guest_name(self, customer: CustomerResult) -> tuple[str, str]:
        """Estrae e valida nome e cognome dell'ospite per la prenotazione hospitality.
        
        Regole:
        1. Rifiuta qualsiasi valore con caratteri di mascheramento (* o •).
        2. Esegue l'auto-splitting se il cognome è assente ma il nome è composto (es. 'Mario Rossi').
        3. Rifiuta placeholder generici ('Ospite', 'WhatsApp', 'Guest', 'Unknown', 'Cliente').
        4. Blocca se nome o cognome rimangono vuoti.
        """
        raw_first = (customer.nome or "").strip()
        raw_last = (customer.cognome or "").strip()

        # Rilevamento mascheramento PII pieno o parziale
        if any(c in raw_first for c in ("*", "•")) or any(c in raw_last for c in ("*", "•")):
            raise ValueError(
                "I dati del cliente contengono caratteri di mascheramento PII (*). "
                "È necessario acquisire nome e cognome reali prima di creare la prenotazione."
            )

        # Auto-splitting del nome completo se cognome vuoto
        if not raw_last and " " in raw_first:
            parts = raw_first.split(maxsplit=1)
            raw_first, raw_last = parts[0], parts[1]

        # Rifiuto placeholder generici
        if raw_first.lower() in _GENERIC_NAME_PLACEHOLDERS or raw_last.lower() in _GENERIC_NAME_PLACEHOLDERS:
            raise ValueError(
                f"Nome '{raw_first}' o cognome '{raw_last}' è un placeholder generico non consentito. "
                "È obbligatorio acquisire il nominativo reale dell'ospite."
            )

        if not raw_first or not raw_last:
            raise ValueError(
                "Nome e cognome dell'ospite sono entrambi obbligatori per le prenotazioni Beds24."
            )

        return raw_first, raw_last

    # ── BookingSystemPort: 1. get_opening_hours ──────────────────

    async def get_opening_hours(self, org_id: uuid.UUID | str) -> OpeningHoursResult:
        """Restituisce le finestre orarie di check-in e check-out della struttura."""
        params: dict[str, Any] = {}
        if self._property_id:
            try:
                params["id"] = [int(self._property_id)]
            except ValueError:
                pass

        try:
            res = await self._request("GET", "/properties", params=params)
            props = res.get("data", []) if isinstance(res, dict) else []
            prop = props[0] if props else {}
        except Exception as exc:
            logger.warning("Impossibile recuperare orari property da Beds24 per org %s: %s", org_id, exc)
            prop = {}

        # Estrazione orari check-in / check-out
        raw_checkin_start = prop.get("checkInStart") or "14:00"
        raw_checkin_end = prop.get("checkInEnd") or "20:00"

        try:
            h_in, m_in = map(int, raw_checkin_start.split(":"))
            t_in = dtime(h_in, m_in)
        except Exception:
            t_in = dtime(14, 0)

        try:
            h_out, m_out = map(int, raw_checkin_end.split(":"))
            t_out = dtime(h_out, m_out)
        except Exception:
            t_out = dtime(20, 0)

        daily_fasce = [TimeRange(inizio=t_in, fine=t_out)]
        orari = [DaySchedule(giorno_settimana=day, aperto=True, fasce=daily_fasce) for day in range(7)]

        return OpeningHoursResult(
            orari=orari,
            festivi_chiusi=[],
            timezone=self._default_timezone,
        )

    # ── BookingSystemPort: 2. get_services ────────────────────────

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        """Elenca le tipologie di camera/unità (roomTypes) configurate su Beds24."""
        params: dict[str, Any] = {"includeAllRooms": True}
        if self._property_id:
            try:
                params["id"] = [int(self._property_id)]
            except ValueError:
                pass

        res = await self._request("GET", "/properties", params=params)
        props = res.get("data", []) if isinstance(res, dict) else []

        services: list[ServiceItem] = []
        for prop in props:
            curr = prop.get("currency") or "EUR"
            room_types = prop.get("roomTypes", [])
            for room in room_types:
                room_id = str(room.get("id", ""))
                if not room_id:
                    continue

                nome = room.get("name") or f"Camera {room_id}"
                room_type = room.get("roomType") or "standard"
                max_adult = room.get("maxAdult", 2)
                desc = f"Tipologia: {room_type}, Max Ospiti: {max_adult}"

                prezzo_cent: int | None = None
                raw_price = room.get("minPrice")
                if raw_price is not None:
                    try:
                        prezzo_cent = int(round(float(raw_price) * 100))
                    except (ValueError, TypeError):
                        pass

                services.append(
                    ServiceItem(
                        service_id=room_id,
                        nome=nome,
                        descrizione=desc,
                        durata_minuti=1440,  # 24 ore soggiorno
                        prezzo_cent=prezzo_cent,
                        valuta=curr,
                        categoria="hospitality_room",
                    )
                )

        return services

    # ── BookingSystemPort: 3. get_customer ────────────────────────

    async def get_customer(self, org_id: uuid.UUID | str, query: CustomerQuery) -> CustomerResult | None:
        """Cerca l'anagrafica ospite su Beds24 tramite telefono, email o booking ID."""
        search_term = query.telefono or query.email or query.customer_id
        if not search_term or not search_term.strip():
            return None

        params = {
            "searchString": search_term.strip(),
            "includeGuests": True,
        }
        if self._property_id:
            try:
                params["propertyId"] = [int(self._property_id)]
            except ValueError:
                pass

        res = await self._request("GET", "/bookings", params=params)
        bookings = res.get("data", []) if isinstance(res, dict) else []
        if not bookings:
            return None

        # Prendi la prenotazione più recente
        booking = bookings[0]
        raw_first = (booking.get("firstName") or "").strip()
        raw_last = (booking.get("lastName") or "").strip()
        raw_phone = (booking.get("mobile") or booking.get("phone") or "").strip()
        raw_email = (booking.get("email") or "").strip() or None

        # Sanitizzazione PII mascherata (* o •)
        if any(c in raw_first for c in ("*", "•")):
            raw_first = ""
        if any(c in raw_last for c in ("*", "•")):
            raw_last = ""
        if any(c in raw_phone for c in ("*", "•")):
            raw_phone = ""
        if raw_email and any(c in raw_email for c in ("*", "•")):
            raw_email = None

        if not raw_first and not raw_last and not raw_phone:
            return None

        customer_id = str(booking.get("id", ""))
        return CustomerResult(
            customer_id=customer_id,
            nome=raw_first,
            cognome=raw_last,
            telefono=raw_phone,
            email=raw_email,
            note=booking.get("comments") or booking.get("notes") or "",
            metadata={
                "provider": "beds24",
                "room_id": booking.get("roomId"),
                "status": booking.get("status"),
            },
        )

    # ── BookingSystemPort: 4. get_availability ────────────────────

    async def get_availability(self, org_id: uuid.UUID | str, query: AvailabilityQuery) -> AvailabilityResult:
        """Verifica la disponibilità di camere/offerte hospitality nel periodo indicato."""
        arrival = query.data_inizio.isoformat()
        if query.data_fine and query.data_fine > query.data_inizio:
            departure = query.data_fine.isoformat()
        else:
            departure = (query.data_inizio + timedelta(days=1)).isoformat()

        num_adults = max(1, query.adulti if query.adulti else query.coperti_o_quantita)
        num_children = max(0, query.bambini)

        params: dict[str, Any] = {
            "arrival": arrival,
            "departure": departure,
            "numAdults": num_adults,
            "numChildren": num_children,
        }
        if self._property_id:
            try:
                params["propertyId"] = [int(self._property_id)]
            except ValueError:
                pass
        if query.service_id:
            try:
                params["roomId"] = [int(query.service_id)]
            except ValueError:
                pass

        try:
            res = await self._request("GET", "/inventory/rooms/offers", params=params)
        except Beds24ConflictError:
            return AvailabilityResult(success=True, slots=[])

        data = res.get("data", []) if isinstance(res, dict) else []
        slots: list[SlotAvailability] = []

        for item in data:
            room_id = str(item.get("roomId", ""))
            offers = item.get("offers", [])
            for offer in offers:
                units = int(offer.get("unitsAvailable", 0))
                if units <= 0:
                    continue

                prezzo_cent: int | None = None
                raw_price = offer.get("price")
                if raw_price is not None:
                    try:
                        prezzo_cent = int(round(float(raw_price) * 100))
                    except (ValueError, TypeError):
                        pass

                offer_name = offer.get("offerName")
                slots.append(
                    SlotAvailability(
                        data=query.data_inizio,
                        ora_inizio=dtime(14, 0),
                        ora_fine=dtime(10, 0),
                        disponibile=True,
                        capacita_residua=units,
                        service_id=room_id,
                        prezzo_cent=prezzo_cent,
                        board_type=query.board_type or offer_name,
                    )
                )

        return AvailabilityResult(success=True, slots=slots)

    # ── BookingSystemPort: 5. create_booking ───────────────────────

    async def create_booking(self, org_id: uuid.UUID | str, req: CreateBookingRequest) -> BookingResult:
        """Crea una prenotazione su Beds24 con controllo disponibilità e idempotenza nativa."""
        # 1. Validazione rigorosa del nome ospite
        try:
            first_name, last_name = self._extract_and_validate_guest_name(req.customer)
        except ValueError as exc:
            return BookingResult(
                success=False,
                external_booking_id=None,
                stato="rifiutata",
                error_code="missing_guest_name",
                error_message=str(exc),
                sync_status="synced",
            )

        # 2. Date di soggiorno hospitality
        arrival = req.data.isoformat()
        if req.data_fine and req.data_fine > req.data:
            departure = req.data_fine.isoformat()
        else:
            departure = (req.data + timedelta(days=1)).isoformat()

        # 3. Risoluzione roomId
        room_id: int | None = None
        if req.service_id:
            try:
                room_id = int(req.service_id)
            except ValueError:
                pass

        if room_id is None:
            # Fallback: recupera la prima camera disponibile per la property
            services = await self.get_services(org_id)
            if not services:
                return BookingResult(
                    success=False,
                    external_booking_id=None,
                    stato="errore",
                    error_code="no_room_configured",
                    error_message=f"Nessuna camera configurata su Beds24 per org {org_id}",
                    sync_status="synced",
                )
            room_id = int(services[0].service_id)

        # 4. Email (ignora email sintetiche per non inquinare il PMS)
        email_val: str | None = None
        if req.customer.email and not is_synthetic_email(req.customer.email):
            email_val = req.customer.email.strip()

        # 5. Costruzione payload POST /bookings
        booking_item: dict[str, Any] = {
            "roomId": room_id,
            "status": "confirmed",
            "arrival": arrival,
            "departure": departure,
            "numAdult": max(1, req.adulti if req.adulti else req.coperti),
            "numChild": max(0, req.bambini),
            "firstName": first_name,
            "lastName": last_name,
            "phone": req.customer.telefono,
            "apiReference": req.idempotency_key,
            "actions": {
                "checkAvailability": True,
            },
        }
        if email_val:
            booking_item["email"] = email_val
        if req.note:
            booking_item["comments"] = req.note

        try:
            res = await self._request("POST", "/bookings", json_data=[booking_item])
        except Beds24ConflictError:
            return BookingResult(
                success=False,
                external_booking_id=None,
                stato="rifiutata",
                error_code="slot_full",
                error_message="Camera non disponibile o al completo su Beds24.",
                sync_status="synced",
            )
        except Beds24ValidationError as exc:
            return BookingResult(
                success=False,
                external_booking_id=None,
                stato="rifiutata",
                error_code="validation_error",
                error_message=str(exc),
                sync_status="synced",
            )

        # 6. Analisi esito operazione multipla Beds24
        if isinstance(res, list) and len(res) > 0:
            result_item = res[0]
            if result_item.get("success") is True:
                new_info = result_item.get("new") or {}
                booking_id = str(new_info.get("id") or result_item.get("id") or "")
                return BookingResult(
                    success=True,
                    external_booking_id=booking_id,
                    stato="confermata",
                    data=req.data,
                    ora_inizio=req.ora_inizio,
                    dettagli={
                        "provider": "beds24",
                        "booking_id": booking_id,
                        "room_id": room_id,
                        "arrival": arrival,
                        "departure": departure,
                    },
                    sync_status="synced",
                )
            else:
                errors = result_item.get("errors", [])
                error_msg = "; ".join(e.get("message", "Errore creazione") for e in errors)
                if any(
                    word in error_msg.lower()
                    for word in ("available", "availability", "conflict", "overbooking", "full")
                ):
                    return BookingResult(
                        success=False,
                        external_booking_id=None,
                        stato="rifiutata",
                        error_code="slot_full",
                        error_message="Camera non disponibile o al completo su Beds24.",
                        sync_status="synced",
                    )
                return BookingResult(
                    success=False,
                    external_booking_id=None,
                    stato="errore",
                    error_code="provider_error",
                    error_message=error_msg,
                    sync_status="synced",
                )

        return BookingResult(
            success=False,
            external_booking_id=None,
            stato="errore",
            error_code="unexpected_response",
            error_message="Risposta inattesa da POST /bookings Beds24",
            sync_status="synced",
        )

    # ── BookingSystemPort: 6. update_booking ───────────────────────

    async def update_booking(self, org_id: uuid.UUID | str, req: UpdateBookingRequest) -> BookingResult:
        """Modifica una prenotazione esistente su Beds24."""
        try:
            booking_id = int(req.external_booking_id)
        except ValueError:
            return BookingResult(
                success=False,
                external_booking_id=req.external_booking_id,
                stato="errore",
                error_code="invalid_booking_id",
                error_message=f"ID prenotazione non valido: {req.external_booking_id}",
                sync_status="synced",
            )

        update_item: dict[str, Any] = {"id": booking_id}
        if req.nuova_data:
            update_item["arrival"] = req.nuova_data.isoformat()
        if req.nuova_data_fine:
            update_item["departure"] = req.nuova_data_fine.isoformat()
        if req.nuovo_service_id:
            try:
                update_item["roomId"] = int(req.nuovo_service_id)
            except ValueError:
                pass
        if req.nuovi_coperti is not None:
            update_item["numAdult"] = max(1, req.nuovi_coperti)
        if req.nuove_note is not None:
            update_item["comments"] = req.nuove_note

        try:
            res = await self._request("POST", "/bookings", json_data=[update_item])
        except Beds24ConflictError:
            return BookingResult(
                success=False,
                external_booking_id=req.external_booking_id,
                stato="rifiutata",
                error_code="slot_full",
                error_message="Camera o date non disponibili su Beds24 per la modifica richiesta.",
                sync_status="synced",
            )

        if isinstance(res, list) and len(res) > 0:
            result_item = res[0]
            if result_item.get("success") is True:
                return BookingResult(
                    success=True,
                    external_booking_id=req.external_booking_id,
                    stato="confermata",
                    data=req.nuova_data,
                    ora_inizio=req.nuova_ora_inizio,
                    sync_status="synced",
                )
            else:
                errors = result_item.get("errors", [])
                error_msg = "; ".join(e.get("message", "Errore modifica") for e in errors)
                if any(word in error_msg.lower() for word in ("available", "availability", "conflict")):
                    return BookingResult(
                        success=False,
                        external_booking_id=req.external_booking_id,
                        stato="rifiutata",
                        error_code="slot_full",
                        error_message="Camera non disponibile per le nuove date selezionate.",
                        sync_status="synced",
                    )
                return BookingResult(
                    success=False,
                    external_booking_id=req.external_booking_id,
                    stato="errore",
                    error_code="provider_error",
                    error_message=error_msg,
                    sync_status="synced",
                )

        return BookingResult(
            success=False,
            external_booking_id=req.external_booking_id,
            stato="errore",
            error_code="unexpected_response",
            error_message="Risposta inattesa da POST /bookings Beds24",
            sync_status="synced",
        )

    # ── BookingSystemPort: 7. cancel_booking ───────────────────────

    async def cancel_booking(self, org_id: uuid.UUID | str, req: CancelBookingRequest) -> BookingResult:
        """Cancella una prenotazione su Beds24 garantendo l'idempotenza."""
        try:
            booking_id = int(req.external_booking_id)
        except ValueError:
            return BookingResult(
                success=False,
                external_booking_id=req.external_booking_id,
                stato="errore",
                error_code="invalid_booking_id",
                error_message=f"ID prenotazione non valido: {req.external_booking_id}",
                sync_status="synced",
            )

        cancel_item: dict[str, Any] = {
            "id": booking_id,
            "status": "cancelled",
        }
        if req.motivo:
            cancel_item["notes"] = f"Cancellata: {req.motivo}"

        try:
            res = await self._request("POST", "/bookings", json_data=[cancel_item])
        except Beds24NotFoundError:
            # Idempotenza: se la prenotazione non esiste più o è già cancellata
            return BookingResult(
                success=True,
                external_booking_id=req.external_booking_id,
                stato="cancellata",
                sync_status="synced",
            )

        if isinstance(res, list) and len(res) > 0:
            result_item = res[0]
            if result_item.get("success") is True:
                return BookingResult(
                    success=True,
                    external_booking_id=req.external_booking_id,
                    stato="cancellata",
                    sync_status="synced",
                )
            else:
                errors = result_item.get("errors", [])
                error_msg = "; ".join(e.get("message", "Errore cancellazione") for e in errors)
                # Idempotenza: se l'errore indica che era già cancellata
                if "already cancelled" in error_msg.lower():
                    return BookingResult(
                        success=True,
                        external_booking_id=req.external_booking_id,
                        stato="cancellata",
                        sync_status="synced",
                    )
                return BookingResult(
                    success=False,
                    external_booking_id=req.external_booking_id,
                    stato="errore",
                    error_code="cancellation_failed",
                    error_message=error_msg,
                    sync_status="synced",
                )

        return BookingResult(
            success=False,
            external_booking_id=req.external_booking_id,
            stato="errore",
            error_code="unexpected_response",
            error_message="Risposta inattesa da POST /bookings Beds24",
            sync_status="synced",
        )

    # ── Lifecycle & Safe Representation ───────────────────────────

    async def close(self) -> None:
        """Chiude il client HTTP se gestito internamente dall'adapter."""
        if self._owns_client and self._client:
            await self._client.aclose()

    async def __aenter__(self) -> Beds24Adapter:
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def __repr__(self) -> str:
        """Rappresentazione sicura conforme a Invariante #10 (Zero Secrets Logging)."""
        return f"<Beds24Adapter org={self.organization_id} property_id={self._property_id}>"

    def __str__(self) -> str:
        return self.__repr__()
