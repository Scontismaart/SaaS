"""Test Live Sandbox Apaleo PMS (Hospitality).

SICUREZZA & ISOLAMENTO DI PRODUZIONE:
1. Questo file NON legge mai credenziali dal database di produzione (external_booking_credentials)
   né accede a ID o dati di clienti reali.
2. Le credenziali vengono lette ESCLUSIVAMENTE dalle variabili d'ambiente dedicate:
   - APALEO_SANDBOX_CLIENT_ID (oppure APALEO_CLIENT_ID)
   - APALEO_SANDBOX_CLIENT_SECRET (oppure APALEO_CLIENT_SECRET)
   - APALEO_SANDBOX_PROPERTY_ID (opzionale, auto-rilevato se assente)
3. In assenza di queste variabili, l'intera suite viene saltata (skip) senza errori né chiamate di rete.
4. Ogni prenotazione creata in ambiente sandbox utilizza prefissi sintetici sentinella:
   - Nome: "[TEST-MELPIS] Live Sandbox Guest"
   - Telefono: "+393990000002"
   - Note: "[TEST RUN AUTOMATED - APALEO LIVE SANDBOX]"
5. Il test include una clausola di teardown per cancellare immediatamente la prenotazione creata
   e verificare il comportamento dell'header Idempotency-Key e della cancellazione idempotente.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time as dtime, timedelta

import pytest

from src.core.bookings.adapters.apaleo_adapter import ApaleoAdapter
from src.core.bookings.ports.base import (
    AvailabilityQuery,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerQuery,
    CustomerResult,
)

SANDBOX_CLIENT_ID = os.getenv("APALEO_SANDBOX_CLIENT_ID") or os.getenv("APALEO_CLIENT_ID")
SANDBOX_CLIENT_SECRET = os.getenv("APALEO_SANDBOX_CLIENT_SECRET") or os.getenv("APALEO_CLIENT_SECRET")
SANDBOX_PROPERTY_ID = os.getenv("APALEO_SANDBOX_PROPERTY_ID") or os.getenv("APALEO_PROPERTY_ID")

pytestmark = pytest.mark.skipif(
    not (SANDBOX_CLIENT_ID and SANDBOX_CLIENT_SECRET),
    reason="Test LIVE Sandbox Apaleo: richiede APALEO_SANDBOX_CLIENT_ID e APALEO_SANDBOX_CLIENT_SECRET nell'ambiente",
)

SANDBOX_TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000098")


@pytest.fixture
async def live_apaleo_adapter():
    """Istanzia l'adapter puntando esclusivamente alle credenziali sandbox live."""
    adapter = ApaleoAdapter(
        organization_id=SANDBOX_TEST_ORG_ID,
        client_id=SANDBOX_CLIENT_ID or "",
        client_secret=SANDBOX_CLIENT_SECRET or "",
        property_id=SANDBOX_PROPERTY_ID,
        timeout_seconds=10.0,
    )
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_live_apaleo_authentication_and_services(live_apaleo_adapter):
    """Verifica autenticazione live contro Apaleo Identity e recupero Unit Groups dell'hotel demo."""
    services = await live_apaleo_adapter.get_services(SANDBOX_TEST_ORG_ID)
    assert isinstance(services, list)
    assert len(services) > 0, "L'hotel sandbox di Apaleo deve contenere almeno una tipologia di alloggio (Unit Group)"

    hours = await live_apaleo_adapter.get_opening_hours(SANDBOX_TEST_ORG_ID)
    assert hours.timezone is not None
    assert len(hours.orari) == 7


@pytest.mark.asyncio
async def test_live_apaleo_availability(live_apaleo_adapter):
    """Verifica disponibilità per un soggiorno di 2 notti la settimana prossima."""
    target_arrival = date.today() + timedelta(days=7)
    target_departure = target_arrival + timedelta(days=2)

    query = AvailabilityQuery(
        data_inizio=target_arrival,
        data_fine=target_departure,
        adulti=1,
    )
    avail = await live_apaleo_adapter.get_availability(SANDBOX_TEST_ORG_ID, query)
    assert avail.success is True
    # Nota: se il calendario demo ha disponibilità, verifica la presenza di slot validi
    assert isinstance(avail.slots, list)


@pytest.mark.asyncio
async def test_live_apaleo_booking_lifecycle_with_idempotency(live_apaleo_adapter):
    """Esegue ciclo completo: creazione con Idempotency-Key, get_customer, cancellazione e retry idempotente."""
    target_arrival = date.today() + timedelta(days=14)
    target_departure = target_arrival + timedelta(days=1)
    unique_key = f"live_sandbox_{uuid.uuid4().hex[:12]}"

    customer = CustomerResult(
        customer_id=f"cust_{unique_key}",
        nome="[TEST-MELPIS]",
        cognome="LiveSandboxGuest",
        telefono="+393990000002",
        email="sandbox.test@noemail.invalid",
    )

    req = CreateBookingRequest(
        idempotency_key=unique_key,
        customer=customer,
        data=target_arrival,
        data_fine=target_departure,
        ora_inizio=dtime(15, 0),
        adulti=1,
        note="[TEST RUN AUTOMATED - CANCELLAZIONE IMMEDIATA]",
    )

    # 1. Creazione su hotel demo
    created = await live_apaleo_adapter.create_booking(SANDBOX_TEST_ORG_ID, req)
    assert created.success is True
    assert created.external_booking_id is not None
    assert created.stato == "confermata"

    res_id = created.external_booking_id

    try:
        # 2. Verifica rilettura cliente
        cust_found = await live_apaleo_adapter.get_customer(
            SANDBOX_TEST_ORG_ID,
            CustomerQuery(telefono="+393990000002"),
        )
        if cust_found:
            # Apaleo restituisce i dati in chiaro se 'Retrieve' è consentito,
            # oppure stringa vuota se il client ha PII masking attivo ('Omit linked' -> '***' sanificato).
            assert cust_found.cognome in ("LiveSandboxGuest", "")

        # 3. Cancellazione prenotazione
        cancel_res = await live_apaleo_adapter.cancel_booking(
            SANDBOX_TEST_ORG_ID,
            CancelBookingRequest(idempotency_key=f"can_{unique_key}", external_booking_id=res_id),
        )
        assert cancel_res.success is True
        assert cancel_res.stato == "cancellata"

        # 4. Verifica Idempotenza su seconda cancellazione
        cancel_res_2 = await live_apaleo_adapter.cancel_booking(
            SANDBOX_TEST_ORG_ID,
            CancelBookingRequest(idempotency_key=f"can2_{unique_key}", external_booking_id=res_id),
        )
        assert cancel_res_2.success is True
        assert cancel_res_2.stato == "cancellata"

    except Exception:
        # Pulizia di emergenza in caso di assertion fallita
        await live_apaleo_adapter.cancel_booking(
            SANDBOX_TEST_ORG_ID,
            CancelBookingRequest(idempotency_key=f"cleanup_{unique_key}", external_booking_id=res_id),
        )
        raise
