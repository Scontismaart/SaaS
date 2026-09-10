"""FakeBookingAdapter per collaudi offline, test unitari e test di concorrenza (Task 1)."""
from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any

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


class FakeBookingAdapter(BookingSystemPort):
    """Implementazione in-memory di BookingSystemPort per test deterministici."""

    def __init__(self):
        self.bookings: dict[str, dict[str, Any]] = {}
        self.idempotency_map: dict[str, str] = {}  # idempotency_key -> booking_id
        self.customers: dict[str, CustomerResult] = {}
        self.services: list[ServiceItem] = [
            ServiceItem(
                service_id="servizio-default",
                nome="Servizio Test",
                durata_minuti=60,
                prezzo_cent=3000,
                valuta="EUR",
            )
        ]

    async def get_opening_hours(self, org_id: uuid.UUID | str) -> OpeningHoursResult:
        return OpeningHoursResult(
            orari=[
                DaySchedule(
                    giorno_settimana=d,
                    aperto=True,
                    fasce=[
                        TimeRange(inizio=time(9, 0), fine=time(13, 0)),
                        TimeRange(inizio=time(14, 0), fine=time(19, 0)),
                    ],
                )
                for d in range(7)
            ],
            festivi_chiusi=[],
        )

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        return self.services

    async def get_customer(self, org_id: uuid.UUID | str, query: CustomerQuery) -> CustomerResult | None:
        if query.customer_id and query.customer_id in self.customers:
            return self.customers[query.customer_id]
        if query.telefono:
            for c in self.customers.values():
                if c.telefono == query.telefono:
                    return c
        return None

    async def get_availability(self, org_id: uuid.UUID | str, query: AvailabilityQuery) -> AvailabilityResult:
        slots = [
            SlotAvailability(
                data=query.data_inizio,
                ora_inizio=time(h, 0),
                ora_fine=time(h + 1, 0),
                disponibile=True,
                capacita_residua=5,
                service_id=query.service_id,
            )
            for h in range(9, 18)
        ]
        return AvailabilityResult(success=True, slots=slots, alternative_consigliate=[])

    async def create_booking(self, org_id: uuid.UUID | str, req: CreateBookingRequest) -> BookingResult:
        # Verifica idempotenza
        if req.idempotency_key in self.idempotency_map:
            existing_id = self.idempotency_map[req.idempotency_key]
            b = self.bookings[existing_id]
            return BookingResult(
                success=True,
                external_booking_id=existing_id,
                stato=b["stato"],
                data=b["data"],
                ora_inizio=b["ora_inizio"],
                sync_status="synced",
            )

        booking_id = f"fake-{uuid.uuid4()}"
        record = {
            "id": booking_id,
            "customer": req.customer,
            "data": req.data,
            "ora_inizio": req.ora_inizio,
            "coperti": req.coperti,
            "stato": "confermata",
            "service_id": req.service_id,
        }
        self.bookings[booking_id] = record
        self.idempotency_map[req.idempotency_key] = booking_id

        return BookingResult(
            success=True,
            external_booking_id=booking_id,
            stato="confermata",
            data=req.data,
            ora_inizio=req.ora_inizio,
            sync_status="synced",
        )

    async def update_booking(self, org_id: uuid.UUID | str, req: UpdateBookingRequest) -> BookingResult:
        if req.external_booking_id not in self.bookings:
            return BookingResult(
                success=False,
                error_code="not_found",
                error_message="Booking not found",
                stato="errore",
            )
        b = self.bookings[req.external_booking_id]
        if req.nuova_data:
            b["data"] = req.nuova_data
        if req.nuova_ora_inizio:
            b["ora_inizio"] = req.nuova_ora_inizio
        return BookingResult(
            success=True,
            external_booking_id=req.external_booking_id,
            stato=b["stato"],
            data=b["data"],
            ora_inizio=b["ora_inizio"],
            sync_status="synced",
        )

    async def cancel_booking(self, org_id: uuid.UUID | str, req: CancelBookingRequest) -> BookingResult:
        if req.external_booking_id not in self.bookings:
            return BookingResult(
                success=False,
                error_code="not_found",
                error_message="Booking not found",
                stato="errore",
            )
        b = self.bookings[req.external_booking_id]
        b["stato"] = "cancellata"
        return BookingResult(
            success=True,
            external_booking_id=req.external_booking_id,
            stato="cancellata",
            data=b["data"],
            ora_inizio=b["ora_inizio"],
            sync_status="synced",
        )
