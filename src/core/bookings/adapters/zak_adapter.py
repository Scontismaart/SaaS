"""ZakAdapter — Hardened Integration con WuBook ZaK per settore Ospitalità (KAPI).

Protocollo: WuBook ZaK KAPI (JSON RPC-style over HTTPS POST).
Endpoint Gateway ufficiale: https://kapi.wubook.net/kapi

Caratteristiche del dominio alberghiero e conformità:
- Autenticazione: Header `x-api-key: <key>`. L'API key è generata in ZaK PMS
  (Configurazioni > ZaK API) ed è associata server-side alla property.
  Il campo `property_id` è mantenuto nell'adapter per identificazione tenant,
  log e routing interno, ma non è richiesto come header HTTP da KAPI.
- Metodi HTTP: Tutti gli endpoint KAPI operano via HTTP POST (RPC-style).
  - /property/fetch_rooms
  - /inventory/fetch_availability
  - /reservations/create
  - /reservations/cancel
  - /customers/fetch_one
- Regimi di trattamento (Meals & Board): Supporto standard hospitality:
  RO (Solo pernottamento), BB (Bed & Breakfast), HB (Mezza pensione),
  FB (Pensione completa), AI (All Inclusive).
- Tariffe dinamiche: get_availability restituisce prezzo dinamico per slot/camera.
- Occupazione per età: ripartizione esplicita tra adulti, bambini ed età bambini.
- Conflitti / Overbooking OTA: Intercettazione di conflitti da canali OTA (Booking.com,
  Airbnb) e indisponibilità camera -> mappati a stato='rifiutata', error_code='slot_full'.
- Idempotenza (Invariante 4): WuBook KAPI non fornisce header di idempotenza nativi.
  L'idempotenza e la sicurezza da double-booking sono garantite a livello applicativo
  a monte dal database locale tramite pattern Send-Then-Mark (tabella external_booking_sync
  e booking_status='pending_external').
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, time, timedelta
from typing import Any

import httpx

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

ZAK_DEFAULT_BASE_URL = "https://kapi.wubook.net/kapi"

# Stringhe sentinella per riconoscimento indisponibilità / overbooking OTA in KAPI
ZAK_UNAVAILABLE_SENTINELS = (
    "no_availability",
    "room not available",
    "room closed",
    "overbooking",
    "minimum stay",
    "closed to arrival",
    "ota",
    "sold out",
)

# Stringhe sentinella per riconoscimento errori di autenticazione KAPI
ZAK_AUTH_ERROR_SENTINELS = (
    "apy-key",
    "api-key",
    "api key",
    "unauthorized",
    "invalid api key",
    "no apy-key provided",
    "apy-key wrong format",
)


class ZakAdapter(BookingSystemPort):
    """Adapter hardened per il PMS alberghiero WuBook ZaK conforme alle specifiche KAPI."""

    def __init__(
        self,
        property_id: str,
        api_key: str,
        base_url: str = ZAK_DEFAULT_BASE_URL,
        timeout_seconds: float = 5.0,
    ):
        self.property_id = property_id
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_seconds
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "x-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _call_kapi(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Esegue una chiamata POST a un endpoint KAPI con gestione network e unwrapping errori."""
        client = self._get_client()
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_opening_hours(self, org_id: uuid.UUID | str) -> OpeningHoursResult:
        """Restituisce le finestre standard di check-in (14:00-20:00) per i 7 giorni della settimana."""
        giorni = []
        for d in range(7):
            giorni.append(
                DaySchedule(
                    giorno_settimana=d,
                    aperto=True,
                    fasce=[
                        TimeRange(inizio=time(14, 0), fine=time(20, 0)),
                    ],
                )
            )
        return OpeningHoursResult(orari=giorni, festivi_chiusi=[])

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        """Recupera l'elenco delle camere / tipologie di alloggio da ZaK tramite POST /property/fetch_rooms."""
        try:
            data = await self._call_kapi("property/fetch_rooms", {})
            if "error" in data:
                logger.error("ZaK get_services error for org %s: %s", org_id, data["error"])
                return []
            raw_rooms = data.get("data", [])
            services = []
            for r in raw_rooms:
                room_id = str(r.get("room_id") or r.get("id") or "")
                price_val = r.get("default_price")
                price_cents = int(price_val * 100) if price_val is not None else r.get("price_cents")
                services.append(
                    ServiceItem(
                        service_id=room_id,
                        nome=r.get("name", "Camera"),
                        durata_minuti=1440,  # 1 notte (24 ore)
                        prezzo_cent=price_cents,
                        categoria="camera",
                    )
                )
            return services
        except Exception as e:
            logger.error("ZaK get_services failed for org %s: %s", org_id, e)
            return []

    async def get_customer(
        self, org_id: uuid.UUID | str, query: CustomerQuery
    ) -> CustomerResult | None:
        """Recupera anagrafica ospite da ZaK tramite POST /customers/fetch_one."""
        try:
            payload: dict[str, Any] = {}
            if query.telefono:
                payload["phone"] = query.telefono
            if query.email:
                payload["email"] = query.email

            data = await self._call_kapi("customers/fetch_one", payload)
            if "error" in data or not data.get("data"):
                return None
            cust_data = data["data"]
            return CustomerResult(
                customer_id=str(cust_data.get("id") or cust_data.get("guest_id") or ""),
                nome=cust_data.get("first_name", ""),
                cognome=cust_data.get("last_name", ""),
                telefono=cust_data.get("phone", ""),
                email=cust_data.get("email"),
            )
        except Exception as e:
            logger.warning("ZaK get_customer failed: %s", e)
            return None

    async def get_availability(
        self, org_id: uuid.UUID | str, query: AvailabilityQuery
    ) -> AvailabilityResult:
        """Verifica disponibilità camere e tariffe dinamiche via POST /inventory/fetch_availability."""
        try:
            payload: dict[str, Any] = {
                "date_from": query.data_inizio.isoformat(),
                "date_to": query.data_fine.isoformat(),
                "adults": query.adulti,
                "children": query.bambini,
                "children_ages": query.eta_bambini,
            }
            if query.service_id:
                payload["room_id"] = query.service_id
            if query.board_type:
                payload["board"] = query.board_type

            data = await self._call_kapi("inventory/fetch_availability", payload)
            if "error" in data:
                return AvailabilityResult(success=False, error_message=str(data["error"]))

            res_data = data.get("data", {})
            available_rooms = res_data.get("available_rooms", [])
            slots = []
            for rm in available_rooms:
                avail_count = rm.get("available_count", 0)
                price_c = rm.get("price_cents")
                if price_c is None and rm.get("price") is not None:
                    price_c = int(rm["price"] * 100)

                slots.append(
                    SlotAvailability(
                        data=query.data_inizio,
                        ora_inizio=time(14, 0),
                        ora_fine=time(20, 0),
                        disponibile=avail_count > 0,
                        capacita_residua=avail_count,
                        service_id=rm.get("room_id"),
                        prezzo_cent=price_c,
                        board_type=rm.get("board") or query.board_type,
                    )
                )
            return AvailabilityResult(success=True, slots=slots)
        except Exception as e:
            logger.error("ZaK get_availability failed: %s", e)
            return AvailabilityResult(success=False, error_message=str(e))

    async def create_booking(
        self, org_id: uuid.UUID | str, req: CreateBookingRequest
    ) -> BookingResult:
        """Crea una prenotazione camera su WuBook ZaK via POST /reservations/create."""
        # Calcolo data di check-out: privilegia data_fine esplicita (immune a cambi ora legale DST)
        if req.data_fine:
            checkout_date = req.data_fine
        else:
            notti = max(1, req.durata_minuti // 1440)
            checkout_date = req.data + timedelta(days=notti)

        notti_effettive = max(1, (checkout_date - req.data).days)

        payload: dict[str, Any] = {
            "room_id": req.service_id or "default",
            "date_from": req.data.isoformat(),
            "date_to": checkout_date.isoformat(),
            "nights": notti_effettive,
            "adults": req.adulti,
            "children": req.bambini,
            "children_ages": req.eta_bambini,
            "board": req.board_type or "RO",
            "customer": {
                "first_name": req.customer.nome,
                "last_name": req.customer.cognome,
                "phone": req.customer.telefono,
                "email": req.customer.email,
            },
            "notes": req.note,
        }

        try:
            data = await self._call_kapi("reservations/create", payload)
            if "error" in data:
                err_msg = str(data.get("error", "")).lower()
                err_details = str(data.get("details", ""))

                # Errore di autenticazione
                if any(s in err_msg for s in ZAK_AUTH_ERROR_SENTINELS):
                    return BookingResult(
                        success=False,
                        stato="errore",
                        error_code="authentication_failed",
                        error_message=f"Autenticazione ZaK KAPI fallita: {data.get('error')}",
                        sync_status="failed",
                    )

                # Indisponibilità o Overbooking da sincronizzazione OTA
                if any(s in err_msg or s in err_details.lower() for s in ZAK_UNAVAILABLE_SENTINELS):
                    return BookingResult(
                        success=False,
                        stato="rifiutata",
                        error_code="slot_full",
                        error_message="Camera non più disponibile o occupata (conflitto OTA/disponibilità)",
                        sync_status="failed",
                    )

                # Altro errore API
                return BookingResult(
                    success=False,
                    stato="errore",
                    error_code="api_error",
                    error_message=f"ZaK KAPI error: {data.get('error')}",
                    sync_status="failed",
                )

            res_data = data.get("data", {})
            res_code = res_data.get("reservation_code") or res_data.get("id") or ""
            return BookingResult(
                success=True,
                external_booking_id=str(res_code),
                stato="confermata",
                sync_status="synced",
            )
        except httpx.TimeoutException as te:
            logger.error("ZaK KAPI timeout on create_booking for org %s: %s", org_id, te)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="network_error",
                error_message="Timeout verso WuBook ZaK KAPI",
                sync_status="failed",
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                return BookingResult(
                    success=False,
                    stato="errore",
                    error_code="authentication_failed",
                    error_message=f"HTTP {e.response.status_code}: autenticazione ZaK fallita",
                    sync_status="failed",
                )
            return BookingResult(
                success=False,
                stato="errore",
                error_code="api_error",
                error_message=f"HTTP {e.response.status_code}: {e.response.text}",
                sync_status="failed",
            )
        except Exception as exc:
            logger.error("ZaK KAPI create_booking exception: %s", exc)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="network_error",
                error_message=str(exc),
                sync_status="failed",
            )

    async def update_booking(
        self, org_id: uuid.UUID | str, req: UpdateBookingRequest
    ) -> BookingResult:
        """Aggiorna una prenotazione esistente su WuBook ZaK via POST /reservations/update."""
        payload: dict[str, Any] = {"reservation_code": req.external_booking_id}
        if req.nuova_data:
            payload["date_from"] = req.nuova_data.isoformat()
        if req.nuova_data_fine:
            payload["date_to"] = req.nuova_data_fine.isoformat()
        if req.nuovi_coperti:
            payload["guests_count"] = req.nuovi_coperti
        if req.nuove_note is not None:
            payload["notes"] = req.nuove_note

        try:
            data = await self._call_kapi("reservations/update", payload)
            if "error" in data:
                return BookingResult(
                    success=False,
                    stato="errore",
                    error_message=str(data["error"]),
                    sync_status="failed",
                )
            return BookingResult(
                success=True,
                external_booking_id=req.external_booking_id,
                stato="confermata",
                sync_status="synced",
            )
        except Exception as e:
            return BookingResult(
                success=False,
                stato="errore",
                error_message=str(e),
                sync_status="failed",
            )

    async def cancel_booking(
        self, org_id: uuid.UUID | str, req: CancelBookingRequest
    ) -> BookingResult:
        """Cancella una prenotazione su WuBook ZaK via POST /reservations/cancel."""
        payload = {
            "reservation_code": req.external_booking_id,
            "reason": req.motivo or "Cancellazione richiesta dal cliente",
        }
        try:
            data = await self._call_kapi("reservations/cancel", payload)
            if "error" in data:
                return BookingResult(
                    success=False,
                    stato="errore",
                    error_message=str(data["error"]),
                    sync_status="failed",
                )
            return BookingResult(
                success=True,
                external_booking_id=req.external_booking_id,
                stato="cancellata",
                sync_status="synced",
            )
        except Exception as e:
            return BookingResult(
                success=False,
                stato="errore",
                error_message=str(e),
                sync_status="failed",
            )
