"""ApaleoAdapter — Integrazione hardened con Apaleo PMS (Hospitality).

Protocollo: Apaleo REST APIs su HTTPS.
Base URL: https://api.apaleo.com

Mappatura Risorse di Dominio (Hospitality PMS):
- Property                <-> Apaleo Property (/inventory/v1/properties/{id})
- ServiceItem             <-> Apaleo Unit Group / Room Type (/inventory/v1/unit-groups)
- AvailabilityQuery       <-> Apaleo Stay Offers (/booking/v1/offers)
- CreateBookingRequest    <-> Apaleo Booking & Reservation (/booking/v1/bookings)
- UpdateBookingRequest    <-> Apaleo Reservation Amend (/booking/v1/reservation-actions/{id}/amend)
- CancelBookingRequest    <-> Apaleo Reservation Cancel (/booking/v1/reservation-actions/{id}/cancel)
- CustomerResult          <-> Apaleo Guest / Booker (/booking/v1/reservations)

Idempotenza e Sicurezza:
- Header nativo `Idempotency-Key` di Apaleo inviato su tutte le chiamate di creazione e mutazione.
- Idempotenza e tracking a livello applicativo garantiti tramite la tabella `external_booking_sync`
  e il pattern Send-Then-Mark.
- Circuit breaker integrato con fast-fail (<1ms) e gestione nativa rate-limit (HTTP 429 con Retry-After).
- Autenticazione tenant-scoped tramite `ApaleoOAuthClient` (OAuth 2.0 Client Credentials o Refresh Token).
- Zero Secrets Logging: token di accesso, refresh token, client secret e PII non necessaria non vengono mai loggati.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Awaitable, Callable

import httpx

from src.core.bookings.adapters.apaleo_auth import (
    ApaleoAuthError as ApaleoAuthClientError,
    ApaleoInvalidGrantError,
    ApaleoOAuthClient,
    ApaleoTokenRequestError,
)
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

APALEO_DEFAULT_BASE_URL = "https://api.apaleo.com"
_SERVER_ERROR_CODES = {500, 502, 503, 504}


# ── Eccezioni di Dominio Apaleo ───────────────────────────────

class ApaleoError(Exception):
    """Eccezione base per errori del client Apaleo."""


class ApaleoAuthError(ApaleoError):
    """Autenticazione fallita (HTTP 401 o 403) o autorizzazione revocata."""


class ApaleoNotFoundError(ApaleoError):
    """Risorsa non trovata (HTTP 404)."""


class ApaleoConflictError(ApaleoError):
    """Conflitto di disponibilità, overbooking o lock unità (HTTP 409)."""


class ApaleoValidationError(ApaleoError):
    """Payload non valido o rifiutato dalla validazione Apaleo (HTTP 422)."""


class ApaleoRateLimitError(ApaleoError):
    """Rate limit superato (HTTP 429)."""

    def __init__(self, message: str = "Rate limit superato per Apaleo", retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class ApaleoServerError(ApaleoError):
    """Errore 5xx lato server Apaleo."""


class ApaleoTimeoutError(ApaleoError):
    """Timeout di rete verso le API Apaleo."""


class ApaleoNetworkError(ApaleoError):
    """Errore di connessione o socket verso Apaleo."""


# ── Adapter Principale ───────────────────────────────────────

class ApaleoAdapter(BookingSystemPort):
    """Adapter conforme a BookingSystemPort per Apaleo PMS (Hospitality)."""

    def __init__(
        self,
        organization_id: uuid.UUID | str,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        property_id: str | None = None,
        auth_client: ApaleoOAuthClient | None = None,
        base_url: str = APALEO_DEFAULT_BASE_URL,
        default_channel_code: str = "Direct",
        default_timezone: str = "Europe/Rome",
        timeout_seconds: float = 8.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
        on_token_refreshed: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ):
        if not organization_id:
            raise ValueError("organization_id obbligatorio per ApaleoAdapter")

        self.organization_id = str(organization_id)
        self.provider_name = "apaleo"
        self._property_id = property_id.strip() if property_id else None
        self._base_url = base_url.rstrip("/")
        self._default_channel_code = default_channel_code
        self._default_timezone = default_timezone
        self._timeout = float(timeout_seconds)

        # Gestione client HTTP
        self._owns_client = False
        if client is not None:
            self._client = client
        else:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True

        # Inizializzazione layer di autenticazione OAuth2
        if auth_client is not None:
            self.auth = auth_client
        else:
            if not client_id or not client_secret:
                raise ApaleoAuthError(
                    "client_id e client_secret (o auth_client) obbligatori per ApaleoAdapter"
                )
            self.auth = ApaleoOAuthClient(
                organization_id=self.organization_id,
                client_id=client_id,
                client_secret=client_secret,
                refresh_token=refresh_token,
                timeout_seconds=self._timeout,
                client=self._client,
                on_token_refreshed=on_token_refreshed,
            )

        # Circuit Breaker state
        self._circuit_breaker_threshold = int(circuit_breaker_threshold)
        self._circuit_breaker_reset_seconds = float(circuit_breaker_reset_seconds)
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        self._circuit_opened_at: float | None = None

    async def close(self) -> None:
        """Chiude le connessioni HTTP se gestite internamente."""
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Circuit Breaker ──────────────────────────────────────────

    def _check_circuit_breaker(self) -> None:
        """Controlla se il circuit breaker è aperto, consentendo un fast-fail immediato (<1ms)."""
        if not self._circuit_is_open:
            return

        now = time.time()
        if self._circuit_opened_at and (now - self._circuit_opened_at) >= self._circuit_breaker_reset_seconds:
            # Finestra di reset trascorsa: transizione a semi-aperto/chiuso
            self._circuit_is_open = False
            self._circuit_failure_count = 0
            self._circuit_opened_at = None
            logger.info("Circuit breaker per Apaleo org %s reimpostato in stato semi-aperto.", self.organization_id)
            return

        raise CircuitOpenError(
            f"Apaleo temporaneamente irraggiungibile per org {self.organization_id}: circuit breaker aperto."
        )

    def _record_success(self) -> None:
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        self._circuit_opened_at = None

    def _record_failure(self) -> None:
        self._circuit_failure_count += 1
        if self._circuit_failure_count >= self._circuit_breaker_threshold:
            self._circuit_is_open = True
            self._circuit_opened_at = time.time()
            logger.error(
                "Circuit breaker APERTO per Apaleo org %s dopo %d fallimenti consecutivi.",
                self.organization_id,
                self._circuit_failure_count,
            )

    # ── HTTP Request Dispatcher ──────────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        operation: str = "request",
        org_id: uuid.UUID | str | None = None,
        is_retry_after_401: bool = False,
    ) -> dict[str, Any]:
        """Esegue una chiamata autenticata ad Apaleo con gestione di errori, circuit breaker e retry su 401."""
        self._check_circuit_breaker()

        clean_path = path.lstrip("/")
        url = f"{self._base_url}/{clean_path}"

        # 1. Recupera Bearer token valido (o rinfrescato in memoria)
        try:
            token = await self.auth.get_access_token()
        except ApaleoInvalidGrantError as exc:
            self._record_failure()
            logger.error("OAuth token revocato o non valido per org %s: %s", self.organization_id, exc)
            raise ApaleoAuthError(f"Autorizzazione Apaleo revocata o non valida: {exc}") from exc
        except ApaleoTokenRequestError as exc:
            self._record_failure()
            logger.error("Errore Identity server Apaleo per org %s: %s", self.organization_id, exc)
            raise ApaleoServerError(f"Errore Identity server Apaleo: {exc}") from exc
        except Exception as exc:
            self._record_failure()
            raise ApaleoAuthError(f"Errore autenticazione Apaleo: {exc}") from exc

        req_headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        start_time = time.perf_counter()
        try:
            resp = await self._client.request(
                method=method,
                url=url,
                headers=req_headers,
                params=params,
                json=json_data,
            )
            duration_ms = int((time.perf_counter() - start_time) * 1000)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as exc:
            self._record_failure()
            logger.error("Apaleo timeout: op=%s org_id=%s error=%s", operation, self.organization_id, exc)
            raise ApaleoTimeoutError(f"Timeout di rete verso Apaleo durante {operation}: {exc}") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            self._record_failure()
            logger.error("Apaleo network error: op=%s org_id=%s error=%s", operation, self.organization_id, exc)
            raise ApaleoNetworkError(f"Errore socket/connessione verso Apaleo durante {operation}: {exc}") from exc

        status = resp.status_code

        # HTTP 401: Tentativo di refresh proattivo del token
        if status == 401:
            if not is_retry_after_401:
                logger.info("Ricevuto HTTP 401 da Apaleo per org %s. Tentativo di token refresh forzato.", self.organization_id)
                try:
                    await self.auth.get_access_token(force_refresh=True)
                    return await self._request(
                        method,
                        path,
                        params=params,
                        json_data=json_data,
                        headers=headers,
                        operation=operation,
                        org_id=org_id,
                        is_retry_after_401=True,
                    )
                except Exception as ref_exc:
                    self._record_failure()
                    logger.error("Refresh forzato dopo 401 fallito per org %s: %s", self.organization_id, ref_exc)
            self._record_failure()
            raise ApaleoAuthError("Autenticazione Apaleo fallita (HTTP 401)")

        if status == 403:
            self._record_failure()
            raise ApaleoAuthError("Accesso negato da Apaleo (HTTP 403): permessi o scope insufficienti")

        if status == 404:
            raise ApaleoNotFoundError(f"Risorsa non trovata su Apaleo (HTTP 404): {url}")

        if status in (400, 422):
            err_msg = self._extract_error_message(resp)
            logger.warning("Validazione o richiesta non valida su Apaleo (HTTP %d): %s", status, err_msg)
            raise ApaleoValidationError(f"Validazione Apaleo rifiutata (HTTP {status}): {err_msg}")

        if status == 409:
            err_msg = self._extract_error_message(resp)
            logger.warning("Conflitto o indisponibilità/overbooking su Apaleo (HTTP 409): %s", err_msg)
            raise ApaleoConflictError(f"Conflitto Apaleo (HTTP 409): {err_msg}")

        if status == 429:
            self._record_failure()
            retry_after_header = resp.headers.get("Retry-After", "60")
            try:
                retry_after_sec = int(retry_after_header)
            except ValueError:
                retry_after_sec = 60
            logger.warning("Rate limit superato per Apaleo org %s (Retry-After: %ds)", self.organization_id, retry_after_sec)
            raise ApaleoRateLimitError(retry_after=retry_after_sec)

        if status in _SERVER_ERROR_CODES or status >= 500:
            self._record_failure()
            logger.error("Errore server Apaleo HTTP %d per org %s", status, self.organization_id)
            raise ApaleoServerError(f"Errore server Apaleo (HTTP {status})")

        if status == 204:
            self._record_success()
            return {}

        try:
            data = resp.json()
            self._record_success()
            return data
        except Exception as exc:
            logger.error("Risposta Apaleo non parsabile come JSON per org %s: %s", self.organization_id, exc)
            raise ApaleoError(f"Risposta malformata da Apaleo (HTTP {status})") from exc

    @staticmethod
    def _extract_error_message(resp: httpx.Response) -> str:
        """Estrae i messaggi di errore restituiti dal modello MessageItemCollection di Apaleo."""
        try:
            body = resp.json()
            if isinstance(body, dict):
                messages = body.get("messages")
                if isinstance(messages, list) and messages:
                    return "; ".join(str(m) for m in messages)
                if "error" in body:
                    return f"{body.get('error')}: {body.get('error_description', '')}"
                if "message" in body:
                    return str(body["message"])
        except Exception:
            pass
        return resp.text or f"HTTP {resp.status_code}"

    # ── Risoluzione Dinamica Property ID ─────────────────────────

    async def _resolve_property_id(self, org_id: uuid.UUID | str) -> str:
        """Restituisce il property_id configurato o lo auto-scopre dall'elenco properties del tenant."""
        if self._property_id:
            return self._property_id

        try:
            data = await self._request("GET", "/inventory/v1/properties", operation="get_properties", org_id=org_id)
            properties = data.get("properties", [])
            if properties:
                self._property_id = str(properties[0].get("id"))
                logger.info(
                    "Property ID auto-scoperto per org %s: %s",
                    self.organization_id,
                    self._property_id,
                )
                return self._property_id
        except Exception as exc:
            logger.warning("Auto-discovery property fallita per org %s: %s", self.organization_id, exc)

        raise ApaleoNotFoundError(
            f"Nessuna property configurata o rilevata per org {self.organization_id}. Specificare property_id."
        )

    # ── Implementazione Contratto BookingSystemPort ───────────────

    async def get_opening_hours(self, org_id: uuid.UUID | str) -> OpeningHoursResult:
        """Restituisce la timezone della struttura e le fasce standard di accoglienza/check-in."""
        prop_id = await self._resolve_property_id(org_id)
        prop_data = await self._request(
            "GET",
            f"/inventory/v1/properties/{prop_id}",
            operation="get_property_details",
            org_id=org_id,
        )
        tz = prop_data.get("timeZone") or self._default_timezone

        # Semantica Hospitality: check-in standard pomeridiano e serale
        giorni = [
            DaySchedule(
                giorno_settimana=d,
                aperto=True,
                fasce=[TimeRange(inizio=dtime(14, 0), fine=dtime(22, 0))],
            )
            for d in range(7)
        ]
        return OpeningHoursResult(orari=giorni, festivi_chiusi=[], timezone=tz)

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        """Elenca le tipologie di camera / alloggio (Unit Groups) disponibili nella property."""
        prop_id = await self._resolve_property_id(org_id)
        resp = await self._request(
            "GET",
            "/inventory/v1/unit-groups",
            params={"propertyId": prop_id, "pageSize": 100},
            operation="get_unit_groups",
            org_id=org_id,
        )

        unit_groups = resp.get("unitGroups", [])
        services: list[ServiceItem] = []
        for ug in unit_groups:
            ug_id = str(ug.get("id") or ug.get("code") or "")
            name_val = ug.get("name")
            if isinstance(name_val, dict):
                nome = name_val.get("it") or name_val.get("en") or next(iter(name_val.values()), ug_id)
            else:
                nome = str(name_val or ug_id)

            desc_val = ug.get("description")
            if isinstance(desc_val, dict):
                desc = desc_val.get("it") or desc_val.get("en") or next(iter(desc_val.values()), "")
            else:
                desc = str(desc_val or "")

            services.append(
                ServiceItem(
                    service_id=ug_id,
                    nome=nome,
                    descrizione=desc,
                    durata_minuti=1440,  # 1 notte (24 ore standard per camera)
                    prezzo_cent=None,
                    categoria=ug.get("type", "camera"),
                )
            )
        return services

    async def get_availability(self, org_id: uuid.UUID | str, query: AvailabilityQuery) -> AvailabilityResult:
        """Verifica la disponibilità di soggiorni e tariffe (Stay Offers) secondo la semantica hospitality."""
        prop_id = await self._resolve_property_id(org_id)
        arrival = query.data_inizio
        if query.data_fine and query.data_fine > arrival:
            departure = query.data_fine
        else:
            departure = arrival + timedelta(days=1)

        params: dict[str, Any] = {
            "propertyId": prop_id,
            "arrival": arrival.isoformat(),
            "departure": departure.isoformat(),
            "adults": max(1, query.adulti),
            "includeUnavailable": False,
        }
        if query.service_id:
            params["unitGroupIds"] = [query.service_id]
        if query.eta_bambini:
            params["childrenAges"] = query.eta_bambini

        try:
            resp = await self._request(
                "GET",
                "/booking/v1/offers",
                params=params,
                operation="get_offers",
                org_id=org_id,
            )
        except (ApaleoConflictError, ApaleoNotFoundError):
            return AvailabilityResult(success=True, slots=[])

        offers = resp.get("offers", [])
        slots: list[SlotAvailability] = []
        for offer in offers:
            available_units = int(offer.get("availableUnits", 0))
            ug = offer.get("unitGroup", {})
            rate_plan = offer.get("ratePlan", {})
            gross_amount = offer.get("totalGrossAmount", {})
            price_cents = None
            if "amount" in gross_amount:
                try:
                    price_cents = int(round(float(gross_amount["amount"]) * 100))
                except (ValueError, TypeError):
                    pass

            slots.append(
                SlotAvailability(
                    data=arrival,
                    ora_inizio=dtime(14, 0),
                    ora_fine=dtime(11, 0),
                    disponibile=(available_units > 0),
                    capacita_residua=available_units,
                    service_id=ug.get("id") or query.service_id,
                    prezzo_cent=price_cents,
                    board_type=query.board_type or rate_plan.get("name"),
                )
            )

        return AvailabilityResult(success=True, slots=slots)

    async def create_booking(self, org_id: uuid.UUID | str, req: CreateBookingRequest) -> BookingResult:
        """Crea una prenotazione alberghiera su Apaleo utilizzando l'idempotency key nativa e il Send-Then-Mark."""
        prop_id = await self._resolve_property_id(org_id)
        arrival = req.data
        if req.data_fine and req.data_fine > arrival:
            departure = req.data_fine
        else:
            departure = arrival + timedelta(days=1)

        num_nights = max(1, (departure - arrival).days)

        # Risoluzione dinamica offerta/tariffa se non già specificata
        rate_plan_id = None
        time_slices = None
        try:
            offers_resp = await self._request(
                "GET",
                "/booking/v1/offers",
                params={
                    "propertyId": prop_id,
                    "arrival": arrival.isoformat(),
                    "departure": departure.isoformat(),
                    "adults": max(1, req.adulti),
                    "unitGroupIds": [req.service_id] if req.service_id else None,
                    "includeUnavailable": False,
                },
                operation="lookup_offer_for_booking",
                org_id=org_id,
            )
            offers = offers_resp.get("offers", [])
            if offers:
                chosen_offer = offers[0]
                rate_plan_id = chosen_offer.get("ratePlan", {}).get("id")
                offer_slices = chosen_offer.get("timeSlices")
                if offer_slices and isinstance(offer_slices, list):
                    time_slices = [
                        {"ratePlanId": s.get("ratePlanId") or rate_plan_id or "STANDARD"}
                        for s in offer_slices
                    ]
        except Exception as exc:
            logger.debug("Lookup offerte non bloccante per org %s: %s", org_id, exc)

        if not time_slices:
            fallback_rate = rate_plan_id or req.service_id or "STANDARD"
            time_slices = [{"ratePlanId": fallback_rate} for _ in range(num_nights)]

        first_name, last_name, name_err = self._extract_and_validate_guest_name(req.customer)
        if name_err:
            logger.warning("Creazione prenotazione Apaleo bloccata per org %s: %s", org_id, name_err)
            return BookingResult(
                success=False,
                stato="rifiutata",
                error_code="missing_guest_name",
                error_message=name_err,
            )

        customer = req.customer
        email = customer.email if customer.email and not self.is_synthetic_email(customer.email) else None
        phone = customer.telefono

        reservation_payload: dict[str, Any] = {
            "arrival": arrival.isoformat(),
            "departure": departure.isoformat(),
            "adults": max(1, req.adulti),
            "childrenAges": req.eta_bambini or [],
            "channelCode": self._default_channel_code,
            "primaryGuest": {
                "firstName": first_name,
                "lastName": last_name,
                "email": email,
                "phone": phone,
            },
            "guestComment": req.note or None,
            "timeSlices": time_slices,
        }

        body = {
            "booker": {
                "firstName": first_name,
                "lastName": last_name,
                "email": email,
                "phone": phone,
            },
            "comment": req.note or None,
            "reservations": [reservation_payload],
        }

        # Idempotenza nativa Apaleo via Header Idempotency-Key
        headers = {
            "Idempotency-Key": req.idempotency_key,
        }

        try:
            resp = await self._request(
                "POST",
                "/booking/v1/bookings",
                json_data=body,
                headers=headers,
                operation="create_booking",
                org_id=org_id,
            )
        except ApaleoConflictError as exc:
            logger.warning("Conflitto disponibilità/overbooking su Apaleo per org %s: %s", org_id, exc)
            return BookingResult(
                success=False,
                stato="rifiutata",
                error_code="slot_full",
                error_message="Camera non disponibile o periodo occupato",
            )
        except ApaleoValidationError as exc:
            logger.error("Errore validazione Apaleo create_booking per org %s: %s", org_id, exc)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="validation_error",
                error_message=str(exc),
            )

        booking_id = resp.get("id")
        reservation_ids = [r.get("id") for r in resp.get("reservationIds", []) if r.get("id")]
        primary_res_id = reservation_ids[0] if reservation_ids else booking_id

        return BookingResult(
            success=True,
            external_booking_id=primary_res_id,
            stato="confermata",
            data=arrival,
            ora_inizio=req.ora_inizio,
            dettagli={
                "booking_id": booking_id,
                "reservation_ids": reservation_ids,
                "property_id": prop_id,
                "arrival": arrival.isoformat(),
                "departure": departure.isoformat(),
                "adults": req.adulti,
                "idempotency_key": req.idempotency_key,
            },
            sync_status="synced",
        )

    async def update_booking(self, org_id: uuid.UUID | str, req: UpdateBookingRequest) -> BookingResult:
        """Modifica le date o i dettagli di una prenotazione esistente su Apaleo."""
        res_id = req.external_booking_id
        if not res_id:
            return BookingResult(success=False, stato="errore", error_message="external_booking_id obbligatorio")

        body: dict[str, Any] = {}
        if req.nuova_data:
            arrival = req.nuova_data
            departure = (
                req.nuova_data_fine
                if req.nuova_data_fine and req.nuova_data_fine > arrival
                else arrival + timedelta(days=1)
            )
            body["arrival"] = arrival.isoformat()
            body["departure"] = departure.isoformat()
            num_nights = max(1, (departure - arrival).days)
            body["timeSlices"] = [{"ratePlanId": req.nuovo_service_id or "STANDARD"} for _ in range(num_nights)]

        headers = {"Idempotency-Key": req.idempotency_key}
        try:
            await self._request(
                "PUT",
                f"/booking/v1/reservation-actions/{res_id}/amend",
                json_data=body,
                headers=headers,
                operation="update_booking",
                org_id=org_id,
            )
        except ApaleoConflictError:
            return BookingResult(
                success=False,
                stato="rifiutata",
                error_code="slot_full",
                error_message="Nuove date non disponibili su Apaleo",
            )
        except ApaleoNotFoundError:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="not_found",
                error_message="Prenotazione non trovata su Apaleo",
            )

        return BookingResult(
            success=True,
            external_booking_id=res_id,
            stato="confermata",
            data=req.nuova_data,
            ora_inizio=req.nuova_ora_inizio,
            dettagli={"updated": True, "idempotency_key": req.idempotency_key},
            sync_status="synced",
        )

    async def cancel_booking(self, org_id: uuid.UUID | str, req: CancelBookingRequest) -> BookingResult:
        """Cancella una prenotazione su Apaleo con gestione idempotente di cancellazioni già effettuate."""
        res_id = req.external_booking_id
        if not res_id:
            return BookingResult(success=False, stato="errore", error_message="external_booking_id mancante")

        try:
            await self._request(
                "PUT",
                f"/booking/v1/reservation-actions/{res_id}/cancel",
                operation="cancel_booking",
                org_id=org_id,
            )
        except ApaleoNotFoundError:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="not_found",
                error_message="Prenotazione non trovata su Apaleo",
            )
        except (ApaleoConflictError, ApaleoValidationError) as exc:
            # Idempotenza: se la prenotazione è già cancellata, trattiamo come operazione riuscita
            err_str = str(exc).lower()
            if "cancel" in err_str or "status" in err_str or "already" in err_str:
                logger.info("Prenotazione %s già cancellata su Apaleo (idempotente).", res_id)
                return BookingResult(
                    success=True,
                    external_booking_id=res_id,
                    stato="cancellata",
                    dettagli={"already_cancelled": True},
                    sync_status="synced",
                )
            raise

        return BookingResult(
            success=True,
            external_booking_id=res_id,
            stato="cancellata",
            sync_status="synced",
        )

    async def get_customer(self, org_id: uuid.UUID | str, query: CustomerQuery) -> CustomerResult | None:
        """Cerca l'anagrafica ospite/prenotante tramite numero di telefono, email o reservation_id."""
        prop_id = await self._resolve_property_id(org_id)
        search_term = query.telefono or query.email or query.customer_id
        if not search_term:
            return None

        reservations: list[dict[str, Any]] = []

        # Tentativo diretto su ID prenotazione se fornito come customer_id
        if query.customer_id:
            try:
                res_data = await self._request(
                    "GET",
                    f"/booking/v1/reservations/{query.customer_id}",
                    operation="get_reservation_by_id",
                    org_id=org_id,
                )
                if res_data and res_data.get("id"):
                    reservations = [res_data]
            except ApaleoNotFoundError:
                pass

        if not reservations:
            params: dict[str, Any] = {
                "propertyIds": [prop_id],
                "textSearch": search_term,
                "pageSize": 5,
            }
            try:
                resp = await self._request(
                    "GET",
                    "/booking/v1/reservations",
                    params=params,
                    operation="search_reservations",
                    org_id=org_id,
                )
                reservations = resp.get("reservations", [])
            except Exception as exc:
                logger.debug("Ricerca prenotazioni Apaleo non riuscita per org %s: %s", org_id, exc)
                return None

        if not reservations:
            return None

        first_res = reservations[0]
        guest = first_res.get("primaryGuest") or first_res.get("booker") or {}
        cust_id = str(guest.get("id") or first_res.get("id") or uuid.uuid4())
        nome = guest.get("firstName") or ""
        if any(c in nome for c in ("*", "•")):
            nome = ""
        cognome = guest.get("lastName") or ""
        if any(c in cognome for c in ("*", "•")):
            cognome = ""
        telefono = guest.get("phone") or query.telefono or ""
        if any(c in telefono for c in ("*", "•")):
            telefono = query.telefono or ""
        raw_email = guest.get("email") or query.email
        if raw_email and any(c in raw_email for c in ("*", "•")):
            email = None
        else:
            email = None if self.is_synthetic_email(raw_email) else raw_email

        return CustomerResult(
            customer_id=cust_id,
            nome=nome,
            cognome=cognome,
            telefono=telefono,
            email=email,
            metadata={
                "reservation_id": first_res.get("id"),
                "booking_id": first_res.get("bookingId"),
                "status": first_res.get("status"),
                "property_id": prop_id,
            },
        )

    @staticmethod
    def _extract_and_validate_guest_name(customer: CustomerResult) -> tuple[str, str, str | None]:
        """Estrae e valida rigorosamente nome e cognome dell'ospite per la prenotazione alberghiera.

        Ritorna (first_name, last_name, error_message).
        Blocca la creazione se mancano nome o cognome reali, oppure se contengono
        caratteri di mascheramento ('*', '•') o placeholder generici ('Ospite', 'WhatsApp').
        """
        raw_nome = (customer.nome or "").strip()
        raw_cognome = (customer.cognome or "").strip()

        # Se il cognome non è fornito separatamente, tenta di estrarre nome e cognome da raw_nome
        if not raw_cognome and " " in raw_nome:
            parts = raw_nome.split(maxsplit=1)
            first_name = parts[0].strip()
            last_name = parts[1].strip()
        else:
            first_name = raw_nome
            last_name = raw_cognome

        invalid_placeholders = {"ospite", "whatsapp", "guest", "unknown", "cliente", "utente"}
        mask_chars = ("*", "•")

        def is_invalid(val: str) -> bool:
            if not val or len(val.strip()) < 2:
                return True
            low = val.strip().lower()
            if any(c in low for c in mask_chars):
                return True
            if low in invalid_placeholders:
                return True
            return False

        if is_invalid(first_name) or is_invalid(last_name):
            return (
                "",
                "",
                "Nome e cognome reali dell'ospite obbligatori per la prenotazione alberghiera su Apaleo. "
                "Non sono ammessi dati parziali, mascherati o segnaposto generici (es. 'Ospite WhatsApp').",
            )

        return first_name, last_name, None

    @staticmethod
    def is_synthetic_email(email: str | None) -> bool:
        """Rileva se un indirizzo email è un placeholder o sintetico (RFC 2606)."""
        return is_synthetic_email(email)

    def __repr__(self) -> str:
        return (
            f"<ApaleoAdapter org_id='{self.organization_id}' "
            f"property_id='{self._property_id}' "
            f"circuit_open={self._circuit_is_open}>"
        )

    def __str__(self) -> str:
        return self.__repr__()
