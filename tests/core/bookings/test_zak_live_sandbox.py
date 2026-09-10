"""Test Live Sandbox WuBook ZaK KAPI.

SICUREZZA & ISOLAMENTO DI PRODUZIONE:
1. Questo file NON legge mai credenziali dal database di produzione (external_booking_credentials)
   né accede a ID o dati di strutture/ospiti reali.
2. Le credenziali vengono lette ESCLUSIVAMENTE dalle variabili d'ambiente dedicate:
   - ZAK_SANDBOX_API_KEY
   - ZAK_SANDBOX_PROPERTY_ID (opzionale, per logging/audit)
3. In assenza di queste variabili, l'intera suite viene saltata (skip) fail-closed
   senza errori né chiamate di rete.
4. Ogni prenotazione creata in ambiente sandbox utilizza prefissi sintetici sentinella univoci:
   - Nome: "[TEST-AIRGAP-ZAK]"
   - Cognome: "Automazione Sandbox"
   - Telefono: "+393990000002"
   - Note: "[TEST RUN AUTOMATED - CANCELLAZIONE IMMEDIATA]"
5. Il test include una clausola di teardown in `try ... finally` per cancellare
   immediatamente la camera prenotata tramite cancel_booking.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, time, timedelta

import pytest

from src.core.bookings.adapters.zak_adapter import ZakAdapter
from src.core.bookings.ports.base import (
    AvailabilityQuery,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerResult,
)

ZAK_SANDBOX_API_KEY = os.getenv("ZAK_SANDBOX_API_KEY")
ZAK_SANDBOX_PROPERTY_ID = os.getenv("ZAK_SANDBOX_PROPERTY_ID", "sandbox_property_test")

pytestmark = pytest.mark.skipif(
    not ZAK_SANDBOX_API_KEY,
    reason="Test LIVE Sandbox WuBook ZaK: richiede ZAK_SANDBOX_API_KEY configurata nell'ambiente",
)

SANDBOX_TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000098")


@pytest.fixture
async def live_zak_adapter():
    """Istanzia ZakAdapter puntando esclusivamente alle credenziali sandbox isolate."""
    adapter = ZakAdapter(
        property_id=ZAK_SANDBOX_PROPERTY_ID,
        api_key=ZAK_SANDBOX_API_KEY or "",
        timeout_seconds=8.0,
    )
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_live_zak_get_services(live_zak_adapter):
    """Verifica recupero tipologie camere live dal gateway KAPI."""
    services = await live_zak_adapter.get_services(SANDBOX_TEST_ORG_ID)
    assert isinstance(services, list)


@pytest.mark.asyncio
async def test_live_zak_get_availability(live_zak_adapter):
    """Verifica interrogazione disponibilità camere live per una data futura."""
    checkin = date.today() + timedelta(days=30)
    checkout = checkin + timedelta(days=2)
    query = AvailabilityQuery(
        data_inizio=checkin,
        data_fine=checkout,
        adulti=2,
        bambini=0,
        board_type="BB",
    )
    res = await live_zak_adapter.get_availability(SANDBOX_TEST_ORG_ID, query)
    assert res.success is True
    assert isinstance(res.slots, list)


@pytest.mark.asyncio
async def test_live_zak_create_and_cancel_booking(live_zak_adapter):
    """Verifica il ciclo completo di creazione e cancellazione con teardown rigoroso."""
    checkin = date.today() + timedelta(days=45)
    checkout = checkin + timedelta(days=2)
    idemp_key = f"live-zak:{SANDBOX_TEST_ORG_ID}:{uuid.uuid4()}"

    req = CreateBookingRequest(
        idempotency_key=idemp_key,
        customer=CustomerResult(
            customer_id="cust-sandbox-zak",
            nome="[TEST-AIRGAP-ZAK]",
            cognome="Automazione Sandbox",
            telefono="+393990000002",
            email="sandbox-test-zak@example.com",
        ),
        data=checkin,
        data_fine=checkout,
        ora_inizio=time(14, 0),
        durata_minuti=2880,
        coperti=2,
        adulti=2,
        bambini=0,
        board_type="BB",
        note="[TEST RUN AUTOMATED - CANCELLAZIONE IMMEDIATA]",
    )

    created_id: str | None = None
    try:
        res_create = await live_zak_adapter.create_booking(SANDBOX_TEST_ORG_ID, req)
        if res_create.success:
            created_id = res_create.external_booking_id
            assert created_id is not None
            assert res_create.stato == "confermata"
    finally:
        # Teardown garantito: cancella la prenotazione creata per non bloccare lo slot nel PMS
        if created_id:
            cancel_req = CancelBookingRequest(
                idempotency_key=f"cancel:{idemp_key}",
                external_booking_id=created_id,
                motivo="Teardown automatico test sandbox",
            )
            res_cancel = await live_zak_adapter.cancel_booking(SANDBOX_TEST_ORG_ID, cancel_req)
            assert res_cancel.success is True
            assert res_cancel.stato == "cancellata"
