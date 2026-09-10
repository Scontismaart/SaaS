"""CalComAdapter — Integrazione con Cal.com via REST API v2.

Protocollo: Cal.com API v2 su HTTPS.
Base URL: https://api.cal.com/v2
Autenticazione: Header `Authorization: Bearer <cal_api_key>`
API Version: Header `cal-api-version: 2024-08-13`

Mappatura Risorse:
- ServiceItem          <-> Cal.com Event Type (/v2/event-types)
- AvailabilityQuery    <-> Cal.com Available Slots (/v2/slots/available)
- CreateBookingRequest <-> Cal.com Booking (/v2/bookings)
- UpdateBookingRequest <-> Cal.com Booking Reschedule (/v2/bookings/{uid}/reschedule)
- CancelBookingRequest <-> Cal.com Booking Cancel (/v2/bookings/{uid}/cancel)
- CustomerResult       <-> Cal.com Booking Attendee

Idempotenza e Sicurezza:
- Idempotenza garantita a livello applicativo tramite tabella external_booking_sync (Send-Then-Mark).
- L'adapter non logga MAI API key, header Authorization o PII non necessaria.
- Circuit breaker con fast-fail (<1ms) e gestione nativa rate-limit (HTTP 429 con Retry-After).
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from src.core.bookings.adapters.simplybook_adapter import CircuitOpenError
from src.core.bookings.identity import generate_synthetic_email, is_synthetic_email
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

CALCOM_DEFAULT_BASE_URL = "https://api.cal.com/v2"
CALCOM_API_VERSION = "2024-08-13"
_SERVER_ERROR_CODES = {500, 502, 503, 504}


# ── Eccezioni specifiche Cal.com ─────────────────────────────

class CalComError(Exception):
    """Eccezione base per errori del client Cal.com."""


class CalComAuthError(CalComError):
    """Autenticazione fallita (HTTP 401 o 403)."""


class CalComNotFoundError(CalComError):
    """Risorsa non trovata (HTTP 404)."""


class CalComConflictError(CalComError):
    """Conflitto o slot già prenotato (HTTP 409)."""


class CalComValidationError(CalComError):
    """Payload non valido o rifiutato (HTTP 422)."""


class CalComRateLimitError(CalComError):
    """Rate limit superato (HTTP 429)."""

    def __init__(self, message: str = "Rate limit superato per Cal.com", retry_after: int = 60):
        super().__init__(message)
        self.retry_after = retry_after


class CalComServerError(CalComError):
    """Errore 5xx lato server Cal.com."""


class CalComTimeoutError(CalComError):
    """Timeout di rete verso le API Cal.com."""


class CalComNetworkError(CalComError):
    """Errore di connessione o socket verso Cal.com."""


# ── Adapter Principale ───────────────────────────────────────

class CalComAdapter(BookingSystemPort):
    """Adapter conforme a BookingSystemPort per Cal.com REST API v2."""

    def __init__(
        self,
        api_key: str,
        base_url: str = CALCOM_DEFAULT_BASE_URL,
        event_type_id: int | str | None = None,
        default_timezone: str = "Europe/Rome",
        placeholder_email_domain: str = "noemail.invalid",
        timeout_seconds: float = 5.0,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_reset_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not isinstance(api_key, str) or not api_key.strip():
            raise CalComAuthError("API key mancante o non valida per Cal.com")

        self._api_key = api_key.strip()
        self.provider_name = "calcom"
        self._base_url = base_url.rstrip("/")
        self._default_event_type_id = int(event_type_id) if event_type_id and str(event_type_id).isdigit() else None
        self._timezone = default_timezone
        self._placeholder_domain = placeholder_email_domain.strip().lower().lstrip("@")
        self._timeout = timeout_seconds

        # Circuit breaker state
        self._circuit_breaker_threshold = circuit_breaker_threshold
        self._circuit_breaker_reset_seconds = circuit_breaker_reset_seconds
        self._circuit_failure_count = 0
        self._circuit_is_open = False
        self._circuit_opened_at: float | None = None

        self._client = client or httpx.AsyncClient(timeout=self._timeout)

    def is_synthetic_email(self, email: str | None) -> bool:
        """Determina se un indirizzo email è un placeholder sintetico e non un dato reale."""
        return is_synthetic_email(email, custom_domain=self._placeholder_domain)

    def _generate_synthetic_email(self, customer: CustomerResult) -> str:
        """Genera un placeholder deterministico e conforme a RFC 2606 (.invalid)."""
        return generate_synthetic_email(customer, domain=self._placeholder_domain)

    def _auth_headers(self) -> dict[str, str]:
        """Headers obbligatori per Cal.com API v2 senza esporre credenziali nei log."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "cal-api-version": CALCOM_API_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _record_failure(self) -> None:
        """Incrementa il contatore di fallimento e apre il circuit breaker se raggiunta la soglia."""
        self._circuit_failure_count += 1
        if self._circuit_failure_count >= self._circuit_breaker_threshold:
            self._circuit_is_open = True
            self._circuit_opened_at = time.time()
            logger.warning(
                "Circuit breaker APERTO per Cal.com dopo %d fallimenti consecutivi. "
                "Fast-fail attivo per %ds.",
                self._circuit_failure_count,
                self._circuit_breaker_reset_seconds,
            )

    def _check_circuit_breaker(self) -> None:
        """Verifica se il circuito è aperto e gestisce l'eventuale scadenza della finestra di reset."""
        if not self._circuit_is_open:
            return

        now = time.time()
        if self._circuit_opened_at and (now - self._circuit_opened_at) >= self._circuit_breaker_reset_seconds:
            # Finestra di reset trascorsa: prova di half-open
            self._circuit_is_open = False
            self._circuit_failure_count = 0
            self._circuit_opened_at = None
            logger.info("Circuit breaker per Cal.com reimpostato in stato semi-aperto/chiuso.")
            return

        raise CircuitOpenError(
            "Cal.com temporaneamente irraggiungibile: circuit breaker aperto. Richiede intervento umano."
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        operation: str = "request",
        org_id: uuid.UUID | str | None = None,
    ) -> dict[str, Any]:
        """Esegue una chiamata HTTP a Cal.com con gestione unificata di errori e circuit breaker."""
        self._check_circuit_breaker()

        clean_path = path.lstrip("/")
        base = self._base_url.rstrip("/")
        if clean_path.startswith("v2/") and base.endswith("/v2"):
            clean_path = clean_path[3:]
        url = f"{base}/{clean_path}"
        headers = self._auth_headers()
        start_time = time.time()

        try:
            resp = await self._client.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=json_data,
            )
            duration = round(time.time() - start_time, 3)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException) as exc:
            self._record_failure()
            logger.error(
                "CalCom timeout: op=%s org_id=%s duration=%.3fs error=%s",
                operation, org_id, round(time.time() - start_time, 3), exc,
            )
            raise CalComTimeoutError(f"Timeout di rete verso Cal.com durante {operation}: {exc}") from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            self._record_failure()
            logger.error(
                "CalCom network error: op=%s org_id=%s duration=%.3fs error=%s",
                operation, org_id, round(time.time() - start_time, 3), exc,
            )
            raise CalComNetworkError(f"Errore di rete verso Cal.com durante {operation}: {exc}") from exc

        status = resp.status_code

        # HTTP error handling
        if status in (401, 403):
            logger.warning("CalCom auth failure: op=%s org_id=%s status=%d", operation, org_id, status)
            raise CalComAuthError(f"Cal.com autenticazione rifiutata (HTTP {status})")

        if status == 404:
            raise CalComNotFoundError(f"Cal.com risorsa non trovata (HTTP 404) per {operation}")

        if status == 409:
            logger.info("CalCom conflict/slot busy: op=%s org_id=%s", operation, org_id)
            raise CalComConflictError("Cal.com slot non disponibile o in conflitto (HTTP 409)")

        if status == 422:
            detail = resp.text[:200]
            raise CalComValidationError(f"Cal.com validazione fallita (HTTP 422): {detail}")

        if status == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("CalCom rate limit: op=%s org_id=%s retry_after=%d", operation, org_id, retry_after)
            raise CalComRateLimitError(retry_after=retry_after)

        if status in _SERVER_ERROR_CODES:
            self._record_failure()
            logger.error("CalCom 5xx: op=%s org_id=%s status=%d duration=%.3fs", operation, org_id, status, duration)
            raise CalComServerError(f"Cal.com errore server (HTTP {status})")

        if status >= 400:
            raise CalComError(f"Cal.com errore HTTP {status}: {resp.text[:200]}")

        # Successo: reset circuito
        self._circuit_failure_count = 0
        self._circuit_is_open = False

        try:
            parsed = resp.json()
        except Exception as exc:
            raise CalComError(f"Risposta non valida (non-JSON) da Cal.com: {exc}") from exc

        return parsed

    async def close(self) -> None:
        """Chiude il client HTTP sottostante."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── BookingSystemPort Implementation ─────────────────────────

    async def get_opening_hours(self, org_id: uuid.UUID | str) -> OpeningHoursResult:
        """Recupera gli orari di lavoro (Schedule) da Cal.com v2.
        
        Cal.com v2 gestisce gli orari tramite `/v2/schedules` o `/v2/schedules/default`.
        In caso di orari personalizzati restituisce i DaySchedule settimanali.
        """
        try:
            res = await self._request(
                "GET",
                "/v2/schedules",
                operation="get_opening_hours",
                org_id=org_id,
            )
            schedules = res.get("data") or []
            if isinstance(schedules, dict):
                schedules = [schedules]

            day_map: dict[str, int] = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6,
            }

            schedules_by_day: dict[int, list[TimeRange]] = {d: [] for d in range(7)}
            found_schedule = False

            if schedules:
                first_sched = schedules[0]
                avail_list = first_sched.get("availability") or []
                for item in avail_list:
                    days = item.get("days") or []
                    start_str = item.get("startTime", "09:00")
                    end_str = item.get("endTime", "18:00")
                    try:
                        sh, sm = map(int, start_str.split(":")[:2])
                        eh, em = map(int, end_str.split(":")[:2])
                        tr = TimeRange(inizio=datetime(2000, 1, 1, sh, sm).time(), fine=datetime(2000, 1, 1, eh, em).time())
                    except Exception:
                        continue

                    for day_item in days:
                        day_num = None
                        if isinstance(day_item, int) and 0 <= day_item <= 6:
                            day_num = day_item
                        elif isinstance(day_item, str) and day_item.lower() in day_map:
                            day_num = day_map[day_item.lower()]
                        if day_num is not None:
                            schedules_by_day[day_num].append(tr)
                            found_schedule = True

            if found_schedule:
                day_schedules = [
                    DaySchedule(
                        giorno_settimana=d,
                        aperto=bool(schedules_by_day[d]),
                        fasce=schedules_by_day[d],
                    )
                    for d in range(7)
                ]
                return OpeningHoursResult(orari=day_schedules, festivi_chiusi=[], timezone=self._timezone)

        except Exception as exc:
            logger.info("Lettura schedule Cal.com non disponibile o vuota (%s); fallback orari standard.", exc)

        # Fallback standard da lunedì a venerdì 09:00-18:00
        standard_schedule = [
            DaySchedule(
                giorno_settimana=d,
                aperto=(d < 5),
                fasce=[TimeRange(inizio=datetime(2000, 1, 1, 9, 0).time(), fine=datetime(2000, 1, 1, 18, 0).time())] if d < 5 else [],
            )
            for d in range(7)
        ]
        return OpeningHoursResult(orari=standard_schedule, festivi_chiusi=[], timezone=self._timezone)

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        """Elenca gli Event Types configurati su Cal.com mappandoli in ServiceItem."""
        res = await self._request("GET", "/v2/event-types", operation="get_services", org_id=org_id)
        raw_items = res.get("data") or []
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("eventTypes") or [raw_items]

        services: list[ServiceItem] = []
        for item in raw_items:
            et_id = str(item.get("id") or item.get("slug") or "")
            if not et_id:
                continue

            title = item.get("title") or item.get("slug") or "Consulenza"
            desc = item.get("description") or ""
            length = int(item.get("lengthInMinutes") or item.get("length") or 60)
            price_raw = item.get("price")
            price_cent = None
            if price_raw is not None:
                try:
                    price_cent = int(round(float(price_raw) * 100))
                except (ValueError, TypeError):
                    price_cent = None

            currency = str(item.get("currency") or "EUR").upper()
            category = "visita" if "med" in title.lower() or "visita" in title.lower() else "generale"

            services.append(
                ServiceItem(
                    service_id=et_id,
                    nome=title,
                    descrizione=desc,
                    durata_minuti=length,
                    prezzo_cent=price_cent,
                    valuta=currency,
                    categoria=category,
                )
            )
        return services

    async def get_customer(self, org_id: uuid.UUID | str, query: CustomerQuery) -> CustomerResult | None:
        """Cerca i dati di un cliente tramite le prenotazioni storiche di Cal.com v2.
        
        Cal.com non possiede un'anagrafica CRM isolata in API v2: i clienti sono desunti
        dagli attendee delle prenotazioni.
        """
        params: dict[str, Any] = {}
        if query.email and not self.is_synthetic_email(query.email):
            params["attendeeEmail"] = query.email

        try:
            res = await self._request(
                "GET",
                "/v2/bookings",
                params=params,
                operation="get_customer",
                org_id=org_id,
            )
            bookings = res.get("data") or []
            if isinstance(bookings, dict):
                bookings = bookings.get("bookings") or [bookings]

            clean_q_phone = "".join(ch for ch in (query.telefono or "") if ch.isdigit())

            for b in bookings:
                attendees = b.get("attendees") or []
                for att in attendees:
                    att_email = att.get("email")
                    att_phone = att.get("phoneNumber") or ""
                    att_name = att.get("name") or "Cliente"

                    match_email = (
                        query.email
                        and att_email
                        and not self.is_synthetic_email(query.email)
                        and query.email.lower() == att_email.lower()
                    )
                    clean_att_phone = "".join(ch for ch in att_phone if ch.isdigit())
                    match_phone = (
                        clean_q_phone
                        and clean_att_phone
                        and (clean_q_phone in clean_att_phone or clean_att_phone in clean_q_phone)
                    )

                    if match_email or match_phone:
                        parts = att_name.split(" ", 1)
                        nome = parts[0]
                        cognome = parts[1] if len(parts) > 1 else ""

                        is_synthetic = self.is_synthetic_email(att_email)
                        # REGOLA DI DATA QUALITY & SICUREZZA: se l'email su Cal.com è un placeholder
                        # sintetico, NON deve MAI essere restituita come informazione reale ai sistemi downstream!
                        real_email = None if is_synthetic else att_email

                        return CustomerResult(
                            customer_id=str(att.get("id") or att_phone or (query.customer_id or "calcom-guest")),
                            nome=nome,
                            cognome=cognome,
                            telefono=att_phone or (query.telefono or ""),
                            email=real_email,
                            metadata={
                                "timezone": att.get("timeZone"),
                                "is_synthetic_email": is_synthetic,
                            },
                        )
        except Exception as exc:
            logger.warning("Ricerca cliente Cal.com fallita per org %s: %s", org_id, exc)

        return None

    async def get_availability(self, org_id: uuid.UUID | str, query: AvailabilityQuery) -> AvailabilityResult:
        """Verifica gli slot orari disponibili per un intervallo temporale tramite GET /v2/slots/available.
        
        Note di mapping e limiti del dominio:
        - Cal.com richiede timestamp completi in formato ISO 8601 UTC.
        - Non supporta occupancy alberghiera (adulti, bambini, board_type): se forniti,
          vengono ignorati segnalando il disallineamento senza falsare i dati.
        """
        if query.board_type or query.adulti > 1 or query.bambini > 0:
            logger.info(
                "CalCom availability: parametri hospitality (adulti=%d, bambini=%d, board=%s) "
                "ignorati (dominio appuntamenti orari).",
                query.adulti, query.bambini, query.board_type,
            )

        # Risoluzione eventTypeId
        event_type_id = None
        if query.service_id and str(query.service_id).isdigit():
            event_type_id = int(query.service_id)
        else:
            event_type_id = self._default_event_type_id

        if not event_type_id:
            # Recupera il primo servizio disponibile se non specificato
            services = await self.get_services(org_id)
            if services and services[0].service_id.isdigit():
                event_type_id = int(services[0].service_id)

        if not event_type_id:
            return AvailabilityResult(
                success=False,
                slots=[],
                error_message="Cal.com richiede un eventTypeId valido per verificare la disponibilità.",
            )

        start_utc = f"{query.data_inizio.isoformat()}T00:00:00Z"
        end_utc = f"{query.data_fine.isoformat()}T23:59:59Z"

        params = {
            "startTime": start_utc,
            "endTime": end_utc,
            "eventTypeId": event_type_id,
        }

        try:
            res = await self._request(
                "GET",
                "/v2/slots/available",
                params=params,
                operation="get_availability",
                org_id=org_id,
            )
        except Exception as exc:
            return AvailabilityResult(
                success=False,
                slots=[],
                error_message=str(exc),
            )

        data = res.get("data") or {}
        slots_data = data.get("slots") or data

        parsed_slots: list[SlotAvailability] = []
        duration_minutes = 60

        # Cal.com slots response può essere un dict { "YYYY-MM-DD": [ {"time": "..."} ] } o lista di slot
        if isinstance(slots_data, dict):
            for date_key, slot_items in slots_data.items():
                try:
                    slot_d = date.fromisoformat(date_key)
                except ValueError:
                    continue

                for s in (slot_items or []):
                    slot_iso = s.get("time") or s.get("start")
                    if not slot_iso:
                        continue
                    try:
                        # Parsing ISO UTC string
                        clean_iso = slot_iso.replace("Z", "+00:00")
                        dt_val = datetime.fromisoformat(clean_iso)
                        start_t = dt_val.time()
                        end_dt = dt_val + timedelta(minutes=duration_minutes)
                        end_t = end_dt.time()
                        parsed_slots.append(
                            SlotAvailability(
                                data=dt_val.date(),
                                ora_inizio=start_t,
                                ora_fine=end_t,
                                disponibile=True,
                                capacita_residua=1,
                                service_id=str(event_type_id),
                            )
                        )
                    except Exception:
                        continue

        elif isinstance(slots_data, list):
            for s in slots_data:
                slot_iso = s.get("time") or s.get("start")
                if not slot_iso:
                    continue
                try:
                    clean_iso = slot_iso.replace("Z", "+00:00")
                    dt_val = datetime.fromisoformat(clean_iso)
                    start_t = dt_val.time()
                    end_t = (dt_val + timedelta(minutes=duration_minutes)).time()
                    parsed_slots.append(
                        SlotAvailability(
                            data=dt_val.date(),
                            ora_inizio=start_t,
                            ora_fine=end_t,
                            disponibile=True,
                            capacita_residua=1,
                            service_id=str(event_type_id),
                        )
                    )
                except Exception:
                    continue

        return AvailabilityResult(success=True, slots=parsed_slots)

    async def create_booking(self, org_id: uuid.UUID | str, req: CreateBookingRequest) -> BookingResult:
        """Crea una prenotazione su Cal.com via POST /v2/bookings.
        
        Rispetta il pattern Send-Then-Mark.
        """
        event_type_id = None
        if req.service_id and str(req.service_id).isdigit():
            event_type_id = int(req.service_id)
        else:
            event_type_id = self._default_event_type_id

        if not event_type_id:
            # Fallback al primo event type disponibile se non presente
            services = await self.get_services(org_id)
            if services and services[0].service_id.isdigit():
                event_type_id = int(services[0].service_id)

        if not event_type_id:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="missing_event_type",
                error_message="Cal.com richiede un eventTypeId valido per la creazione della prenotazione.",
                sync_status="failed",
            )

        # Cal.com richiede timestamp start ISO 8601 UTC
        start_iso = f"{req.data.isoformat()}T{req.ora_inizio.strftime('%H:%M:%S')}Z"

        full_name = f"{req.customer.nome} {req.customer.cognome}".strip() or req.customer.nome or "Cliente"
        # Cal.com richiede obbligatoriamente un indirizzo email per l'attendee
        customer_email = req.customer.email
        is_synthetic = False
        if not customer_email:
            customer_email = self._generate_synthetic_email(req.customer)
            is_synthetic = True

        attendee_payload: dict[str, Any] = {
            "name": full_name,
            "email": customer_email,
            "timeZone": self._timezone,
        }
        if req.customer.telefono:
            attendee_payload["phoneNumber"] = req.customer.telefono

        body: dict[str, Any] = {
            "start": start_iso,
            "eventTypeId": event_type_id,
            "attendee": attendee_payload,
            "metadata": {
                "idempotency_key": req.idempotency_key,
                "source_message_id": req.source_message_id or "",
                "internal_booking_id": str(req.internal_booking_id) if req.internal_booking_id else "",
                "is_synthetic_email": is_synthetic,
                "original_phone": req.customer.telefono or "",
            },
        }

        # Note e minimizzazione
        if req.note:
            body["notes"] = req.note

        if req.coperti > 1:
            logger.info(
                "Cal.com create_booking: richiesta per %d persone. Cal.com mappa come appuntamento standard.",
                req.coperti,
            )

        try:
            res = await self._request(
                "POST",
                "/v2/bookings",
                json_data=body,
                operation="create_booking",
                org_id=org_id,
            )
        except CalComConflictError as ce:
            logger.warning("Cal.com create_booking conflitto per org %s: %s", org_id, ce)
            return BookingResult(
                success=False,
                stato="rifiutata",
                error_code="slot_full",
                error_message="Lo slot selezionato non è più disponibile su Cal.com.",
                sync_status="failed",
            )
        except Exception as exc:
            logger.error("Cal.com create_booking fallita per org %s: %s", org_id, exc)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="external_error",
                error_message=str(exc),
                sync_status="failed",
            )

        data = res.get("data") or res
        external_id = str(data.get("uid") or data.get("id") or "")
        cal_status = str(data.get("status") or "ACCEPTED").upper()

        mapped_status = "confermata"
        if cal_status in ("ACCEPTED", "CONFIRMED"):
            mapped_status = "confermata"
        elif cal_status in ("PENDING", "AWAITING_HOST"):
            mapped_status = "in_attesa"
        elif cal_status in ("CANCELLED", "REJECTED"):
            mapped_status = "cancellata"

        return BookingResult(
            success=True,
            external_booking_id=external_id,
            stato=mapped_status,
            data=req.data,
            ora_inizio=req.ora_inizio,
            dettagli={"calcom_status": cal_status, "raw": data},
            sync_status="synced",
        )

    async def update_booking(self, org_id: uuid.UUID | str, req: UpdateBookingRequest) -> BookingResult:
        """Ripianifica o aggiorna una prenotazione esistente via POST /v2/bookings/{uid}/reschedule."""
        if not req.external_booking_id:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="missing_booking_id",
                error_message="external_booking_id obbligatorio per ripianificare su Cal.com.",
                sync_status="failed",
            )

        if not req.nuova_data or not req.nuova_ora_inizio:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="missing_new_datetime",
                error_message="Nuova data e ora inizio obbligatorie per ripianificare su Cal.com.",
                sync_status="failed",
            )

        start_iso = f"{req.nuova_data.isoformat()}T{req.nuova_ora_inizio.strftime('%H:%M:%S')}Z"
        body = {
            "start": start_iso,
            "reschedulingReason": req.nuove_note or "Modifica richiesta dal cliente",
        }

        path = f"/v2/bookings/{req.external_booking_id}/reschedule"
        try:
            res = await self._request(
                "POST",
                path,
                json_data=body,
                operation="update_booking",
                org_id=org_id,
            )
            data = res.get("data") or res
            new_uid = str(data.get("uid") or req.external_booking_id)
            return BookingResult(
                success=True,
                external_booking_id=new_uid,
                stato="confermata",
                data=req.nuova_data,
                ora_inizio=req.nuova_ora_inizio,
                dettagli={"raw": data},
                sync_status="synced",
            )
        except Exception as exc:
            logger.error("Cal.com reschedule fallita per org %s uid %s: %s", org_id, req.external_booking_id, exc)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="update_failed",
                error_message=str(exc),
                sync_status="failed",
            )

    async def cancel_booking(self, org_id: uuid.UUID | str, req: CancelBookingRequest) -> BookingResult:
        """Annulla una prenotazione esistente su Cal.com via POST /v2/bookings/{uid}/cancel."""
        if not req.external_booking_id:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="missing_booking_id",
                error_message="external_booking_id obbligatorio per cancellazione su Cal.com.",
                sync_status="failed",
            )

        body = {
            "cancellationReason": req.motivo or "Richiesta del cliente",
        }
        path = f"/v2/bookings/{req.external_booking_id}/cancel"

        try:
            res = await self._request(
                "POST",
                path,
                json_data=body,
                operation="cancel_booking",
                org_id=org_id,
            )
            return BookingResult(
                success=True,
                external_booking_id=req.external_booking_id,
                stato="cancellata",
                dettagli={"raw": res.get("data") or res},
                sync_status="synced",
            )
        except CalComError as ce:
            # Idempotenza: se la prenotazione è già stata cancellata, trattiamo come successo
            if "already cancelled" in str(ce).lower():
                logger.info("Cal.com booking %s già cancellata in precedenza (idempotente).", req.external_booking_id)
                return BookingResult(
                    success=True,
                    external_booking_id=req.external_booking_id,
                    stato="cancellata",
                    sync_status="synced",
                )
            logger.error("Cal.com cancel failed per org %s uid %s: %s", org_id, req.external_booking_id, ce)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="cancel_failed",
                error_message=str(ce),
                sync_status="failed",
            )
        except Exception as exc:
            logger.error("Cal.com cancel failed per org %s uid %s: %s", org_id, req.external_booking_id, exc)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="cancel_failed",
                error_message=str(exc),
                sync_status="failed",
            )
