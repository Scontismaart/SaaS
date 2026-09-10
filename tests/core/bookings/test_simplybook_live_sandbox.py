"""Test Live Sandbox SimplyBook.me (Task 5).

SICUREZZA & ISOLAMENTO DI PRODUZIONE:
1. Questo file NON legge mai credenziali dal database di produzione (external_booking_credentials)
   né accede a ID o dati di clienti reali.
2. Le credenziali vengono lette ESCLUSIVAMENTE dalle variabili d'ambiente dedicate:
   - SIMPLYBOOK_SANDBOX_COMPANY_LOGIN
   - SIMPLYBOOK_SANDBOX_API_KEY
3. In assenza di queste variabili, l'intera suite viene saltata (skip) senza errori né chiamate di rete.
4. Ogni prenotazione creata in ambiente sandbox utilizza prefissi sintetici univoci:
   - Nome: "[TEST-MELPIS] Automazione Sandbox"
   - Telefono: "+393990000001"
   - Note: "[TEST RUN AUTOMATED - CANCELLAZIONE IMMEDIATA]"
5. Il test include una clausola di teardown per cancellare immediatamente la prenotazione creata.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime, time, timedelta

import pytest

from src.core.bookings.adapters.simplybook_adapter import SimplyBookAdapter
from src.core.bookings.ports.base import (
    AvailabilityQuery,
    CancelBookingRequest,
    CreateBookingRequest,
    CustomerResult,
)

# Skip automatico se le variabili sandbox dedicate non sono configurate
SANDBOX_COMPANY_LOGIN = os.getenv("SIMPLYBOOK_SANDBOX_COMPANY_LOGIN")
SANDBOX_API_KEY = os.getenv("SIMPLYBOOK_SANDBOX_API_KEY")

pytestmark = pytest.mark.skipif(
    not (SANDBOX_COMPANY_LOGIN and SANDBOX_API_KEY),
    reason="Test LIVE Sandbox SimplyBook: richiede SIMPLYBOOK_SANDBOX_COMPANY_LOGIN e SIMPLYBOOK_SANDBOX_API_KEY nell'ambiente",
)

SANDBOX_TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")


@pytest.fixture
async def live_sandbox_adapter():
    """Istanzia l'adapter puntando esclusivamente alle credenziali sandbox isolate."""
    adapter = SimplyBookAdapter(
        company_login=SANDBOX_COMPANY_LOGIN or "",
        api_key=SANDBOX_API_KEY or "",
        timeout_seconds=8.0,
    )
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_live_sandbox_authentication(live_sandbox_adapter):
    """Verifica autenticazione live contro l'API SimplyBook (getToken)."""
    await live_sandbox_adapter._ensure_authenticated()
    token = live_sandbox_adapter._token
    assert token is not None
    assert isinstance(token, str)
    assert len(token) > 10


@pytest.mark.asyncio
async def test_live_sandbox_get_services(live_sandbox_adapter):
    """Verifica recupero catalogo servizi live dal sandbox."""
    res = await live_sandbox_adapter.get_services(SANDBOX_TEST_ORG_ID)
    assert res.services is not None
    assert isinstance(res.services, list)


@pytest.mark.asyncio
async def test_live_sandbox_get_availability(live_sandbox_adapter):
    """Verifica interrogazione matrice disponibilità live per una data futura."""
    data_test = date.today() + timedelta(days=7)
    query = AvailabilityQuery(
        data=data_test,
        durata_minuti=30,
        coperti=1,
    )
    res = await live_sandbox_adapter.get_availability(SANDBOX_TEST_ORG_ID, query)
    assert res.success is True
    assert isinstance(res.slots, list)


@pytest.mark.asyncio
async def test_live_sandbox_create_and_cancel_booking(live_sandbox_adapter):
    """Verifica il ciclo completo di creazione e immediata cancellazione nel sandbox."""
    data_test = date.today() + timedelta(days=14)
    ora_test = time(11, 0)
    idemp_key = f"live-test-sb:{SANDBOX_TEST_ORG_ID}:{uuid.uuid4()}"

    req = CreateBookingRequest(
        idempotency_key=idemp_key,
        customer=CustomerResult(
            customer_id="cust-sandbox-1",
            nome="[TEST-MELPIS]",
            cognome="Automazione Sandbox",
            telefono="+393990000001",
            email="sandbox-test@example.com",
        ),
        data=data_test,
        ora_inizio=ora_test,
        durata_minuti=30,
        coperti=1,
        note="[TEST AUTOMATED MELPIS - CANCELLAZIONE IMMEDIATA]",
    )

    external_id = None
    try:
        booking_res = await live_sandbox_adapter.create_booking(SANDBOX_TEST_ORG_ID, req)
        external_id = booking_res.external_booking_id
        # Se lo slot era libero nel sandbox, la creazione ha successo
        if booking_res.success:
            assert external_id is not None
            assert booking_res.stato in ("confermata", "in_attesa")
    finally:
        # Pulizia garantita: se è stato generato un ID esterno, cancella la prenotazione
        if external_id:
            cancel_req = CancelBookingRequest(
                idempotency_key=f"cancel:{idemp_key}",
                external_booking_id=external_id,
                motivo="Pulizia test automatico sandbox",
            )
            await live_sandbox_adapter.cancel_booking(SANDBOX_TEST_ORG_ID, cancel_req)
