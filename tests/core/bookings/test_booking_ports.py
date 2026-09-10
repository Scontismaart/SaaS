"""Test per il Modello Canonico delle Prenotazioni (Task 1).

Verifica la conformità formale dei contratti Pydantic, l'interfaccia BookingSystemPort
e il corretto funzionamento di FakeBookingAdapter e InternalBookingAdapter.
"""
import uuid
from datetime import date, time
import pytest

from src.core.bookings.ports.base import (
    AvailabilityQuery,
    AvailabilityResult,
    BookingCustomer,
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
from src.core.bookings.adapters.fake_adapter import FakeBookingAdapter
from src.core.bookings.adapters.internal_adapter import InternalBookingAdapter


def test_booking_system_port_runtime_checkable():
    """Verifica che BookingSystemPort sia un Protocol runtime checkable."""
    assert issubclass(FakeBookingAdapter, BookingSystemPort)
    assert issubclass(InternalBookingAdapter, BookingSystemPort)


def test_pydantic_contracts_validation():
    """Verifica la corretta serializzazione e validazione dei DTO Pydantic."""
    # ServiceItem
    service = ServiceItem(
        service_id="srv-1",
        nome="Taglio Capelli",
        durata_minuti=45,
        prezzo_cent=2500,
        valuta="EUR",
    )
    assert service.service_id == "srv-1"
    assert service.durata_minuti == 45

    # OpeningHours
    hours = OpeningHoursResult(
        orari=[
            DaySchedule(
                giorno_settimana=1,
                aperto=True,
                fasce=[TimeRange(inizio=time(9, 0), fine=time(19, 0))],
            )
        ],
        festivi_chiusi=[date(2026, 12, 25)],
    )
    assert hours.orari[0].aperto is True
    assert hours.festivi_chiusi[0] == date(2026, 12, 25)

    # AvailabilityQuery & Result
    query = AvailabilityQuery(
        data_inizio=date(2026, 9, 10),
        data_fine=date(2026, 9, 10),
        service_id="srv-1",
        coperti_o_quantita=1,
    )
    res = AvailabilityResult(
        success=True,
        slots=[
            SlotAvailability(
                data=date(2026, 9, 10),
                ora_inizio=time(10, 0),
                ora_fine=time(10, 45),
                disponibile=True,
                capacita_residua=1,
            )
        ],
        alternative_consigliate=["11:00"],
    )
    assert res.success is True
    assert len(res.slots) == 1
    assert res.slots[0].disponibile is True


@pytest.mark.asyncio
async def test_fake_booking_adapter_flow():
    """Verifica il ciclo completo di prenotazione con FakeBookingAdapter."""
    adapter = FakeBookingAdapter()
    org_id = uuid.uuid4()

    # 1. Opening hours & services
    hours = await adapter.get_opening_hours(org_id)
    assert len(hours.orari) == 7

    services = await adapter.get_services(org_id)
    assert len(services) > 0
    assert services[0].service_id == "servizio-default"

    # 2. Availability
    avail = await adapter.get_availability(
        org_id,
        AvailabilityQuery(
            data_inizio=date(2026, 9, 10),
            data_fine=date(2026, 9, 10),
            service_id="servizio-default",
        ),
    )
    assert avail.success is True
    assert len(avail.slots) > 0

    # 3. Create booking
    customer = CustomerResult(
        customer_id="cust-1",
        nome="Mario Rossi",
        telefono="+393331234567",
    )
    create_req = CreateBookingRequest(
        idempotency_key=f"ext-test:{org_id}:msg-01",
        customer=customer,
        data=date(2026, 9, 10),
        ora_inizio=time(15, 0),
        durata_minuti=60,
        coperti=1,
        source_message_id="msg-01",
    )
    created = await adapter.create_booking(org_id, create_req)
    assert created.success is True
    assert created.stato == "confermata"
    assert created.sync_status == "synced"
    assert created.external_booking_id is not None

    # Idempotenza: seconda chiamata con stessa chiave restituisce la stessa prenotazione
    created_dup = await adapter.create_booking(org_id, create_req)
    assert created_dup.success is True
    assert created_dup.external_booking_id == created.external_booking_id

    # 4. Update booking
    update_req = UpdateBookingRequest(
        idempotency_key=f"ext-update:{org_id}:msg-02",
        external_booking_id=created.external_booking_id,
        nuova_ora_inizio=time(16, 0),
    )
    updated = await adapter.update_booking(org_id, update_req)
    assert updated.success is True
    assert updated.ora_inizio == time(16, 0)

    # 5. Cancel booking
    cancel_req = CancelBookingRequest(
        idempotency_key=f"ext-cancel:{org_id}:msg-03",
        external_booking_id=created.external_booking_id,
        motivo="Impegno improvviso",
    )
    cancelled = await adapter.cancel_booking(org_id, cancel_req)
    assert cancelled.success is True
    assert cancelled.stato == "cancellata"


@pytest.mark.asyncio
async def test_internal_booking_adapter_delegation():
    """Verifica che InternalBookingAdapter deleghi correttamente al BookingService/Repository interno."""
    from unittest.mock import AsyncMock, MagicMock
    from src.models.schemas import DisponibilitaSlot

    mock_service = MagicMock()
    mock_service.verifica_disponibilita = AsyncMock(
        return_value=DisponibilitaSlot(
            data="2026-09-10",
            ora="15:00",
            coperti_massimi=4,
            coperti_prenotati=1,
            coperti_liberi=3,
            stato="verde",
            alternative=["16:00"],
        )
    )
    mock_service.create_booking = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "data": "2026-09-10",
            "ora": "15:00",
            "stato": "confermata",
        }
    )
    mock_service.cancel = AsyncMock(
        return_value={"id": uuid.uuid4(), "stato": "cancellata"}
    )
    mock_service.update_booking = AsyncMock(
        return_value={
            "id": uuid.uuid4(),
            "data": "2026-09-10",
            "ora": "16:00",
            "stato": "confermata",
        }
    )

    adapter = InternalBookingAdapter(booking_service=mock_service)
    org_id = uuid.uuid4()

    # Availability
    query = AvailabilityQuery(
        data_inizio=date(2026, 9, 10),
        data_fine=date(2026, 9, 10),
        coperti_o_quantita=1,
    )
    avail = await adapter.get_availability(org_id, query)
    assert avail.success is True
    assert len(avail.slots) == 1
    assert avail.slots[0].capacita_residua == 3
    assert avail.alternative_consigliate == ["16:00"]

    # Create
    cust = CustomerResult(customer_id="local", nome="Luca", telefono="+393400000000")
    req = CreateBookingRequest(
        idempotency_key="key-1",
        customer=cust,
        data=date(2026, 9, 10),
        ora_inizio=time(15, 0),
        coperti=2,
    )
    res = await adapter.create_booking(org_id, req)
    assert res.success is True
    assert res.sync_status == "local_only"
    mock_service.create_booking.assert_called_once()
