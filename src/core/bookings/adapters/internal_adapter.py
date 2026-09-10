"""InternalBookingAdapter per l'utilizzo del database locale PostgreSQL via BookingSystemPort (Task 1)."""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class InternalBookingAdapter(BookingSystemPort):
    """Adapter che incapsula la persistenza e le regole di business locali conformandole a BookingSystemPort."""

    def __init__(self, booking_service=None, repo=None):
        self.service = booking_service
        self.repo = repo or getattr(booking_service, "repo", None)

    async def get_opening_hours(self, org_id: uuid.UUID | str) -> OpeningHoursResult:
        # Default orari di apertura per il sistema locale
        return OpeningHoursResult(
            orari=[
                DaySchedule(
                    giorno_settimana=d,
                    aperto=(d != 0),  # Es. Lunedì chiuso
                    fasce=[
                        TimeRange(inizio=time(9, 0), fine=time(13, 0)),
                        TimeRange(inizio=time(15, 0), fine=time(20, 0)),
                    ] if d != 0 else [],
                )
                for d in range(7)
            ],
            festivi_chiusi=[],
        )

    async def get_services(self, org_id: uuid.UUID | str) -> list[ServiceItem]:
        # Nel sistema locale base, restituisce il servizio generale predefinito
        return [
            ServiceItem(
                service_id="local-standard",
                nome="Prenotazione Standard",
                durata_minuti=60,
                prezzo_cent=None,
                valuta="EUR",
                categoria="generale",
            )
        ]

    async def get_customer(self, org_id: uuid.UUID | str, query: CustomerQuery) -> CustomerResult | None:
        # Se c'è un contact_repo accessibile tramite il servizio
        return None

    async def get_availability(self, org_id: uuid.UUID | str, query: AvailabilityQuery) -> AvailabilityResult:
        if not self.service:
            return AvailabilityResult(success=False, error_message="BookingService non configurato")

        data_str = query.data_inizio.isoformat()
        try:
            # Calcola la disponibilità su una fascia campione o interroga semaforo_giorno
            disp = await self.service.verifica_disponibilita(
                org_id=org_id,
                data=data_str,
                ora="12:00",
                coperti=query.coperti_o_quantita,
            )
            coperti_liberi = getattr(disp, "coperti_liberi", 0)
            alternative = getattr(disp, "alternative", [])

            slot = SlotAvailability(
                data=query.data_inizio,
                ora_inizio=time(12, 0),
                ora_fine=time(13, 0),
                disponibile=(coperti_liberi >= query.coperti_o_quantita),
                capacita_residua=coperti_liberi,
            )
            return AvailabilityResult(
                success=True,
                slots=[slot],
                alternative_consigliate=alternative,
            )
        except Exception as e:
            logger.warning("Internal availability check failed for org %s: %s", org_id, e)
            return AvailabilityResult(success=False, error_message=str(e))

    async def create_booking(self, org_id: uuid.UUID | str, req: CreateBookingRequest) -> BookingResult:
        if not self.service:
            return BookingResult(
                success=False,
                stato="errore",
                error_code="service_missing",
                error_message="BookingService non configurato",
            )

        data_str = req.data.isoformat()
        ora_str = req.ora_inizio.strftime("%H:%M")
        try:
            booking = await self.service.create_booking(
                org_id=org_id,
                nome_cliente=req.customer.nome,
                telefono=req.customer.telefono,
                data=data_str,
                ora=ora_str,
                coperti=req.coperti,
                note=req.note,
                origine=req.origine,
                source_message_id=req.source_message_id,
            )
            booking_id = str(booking.get("id")) if isinstance(booking, dict) else str(booking)
            return BookingResult(
                success=True,
                external_booking_id=booking_id,
                stato="confermata",
                data=req.data,
                ora_inizio=req.ora_inizio,
                sync_status="local_only",
                dettagli={"internal_id": booking_id},
            )
        except Exception as e:
            logger.error("Internal create_booking failed: %s", e)
            return BookingResult(
                success=False,
                stato="errore",
                error_code="internal_create_failed",
                error_message=str(e),
                sync_status="failed",
            )

    async def update_booking(self, org_id: uuid.UUID | str, req: UpdateBookingRequest) -> BookingResult:
        if not self.service:
            return BookingResult(success=False, stato="errore", error_message="BookingService non configurato")
        changes: dict[str, Any] = {}
        if req.nuova_data:
            changes["data"] = req.nuova_data.isoformat()
        if req.nuova_ora_inizio:
            changes["ora"] = req.nuova_ora_inizio.strftime("%H:%M")
        if req.nuovi_coperti:
            changes["coperti"] = req.nuovi_coperti
        if req.nuove_note:
            changes["note"] = req.nuove_note

        try:
            updated = await self.service.update_booking(org_id, req.external_booking_id, **changes)
            return BookingResult(
                success=True,
                external_booking_id=req.external_booking_id,
                stato=updated.get("stato", "confermata"),
                data=req.nuova_data,
                ora_inizio=req.nuova_ora_inizio,
                sync_status="local_only",
            )
        except Exception as e:
            return BookingResult(success=False, stato="errore", error_message=str(e))

    async def cancel_booking(self, org_id: uuid.UUID | str, req: CancelBookingRequest) -> BookingResult:
        if not self.service:
            return BookingResult(success=False, stato="errore", error_message="BookingService non configurato")
        try:
            cancelled = await self.service.cancel(org_id, req.external_booking_id)
            return BookingResult(
                success=True,
                external_booking_id=req.external_booking_id,
                stato="cancellata",
                sync_status="local_only",
            )
        except Exception as e:
            return BookingResult(success=False, stato="errore", error_message=str(e))
