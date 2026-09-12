"""Script di bonifica periodica per la sandbox di SimplyBook.me.

Effettua uno sweep programmatico delle prenotazioni generate durante i test E2E o live,
cancellando qualsiasi record che contenga il prefisso sentinella '[TEST-MELPIS]'.
Previene l'accumulo di residui orfani dovuti a network drop prima dell'esecuzione del finally locale.

Utilizzo:
    py -3.12 scripts/sweep_simplybook_sandbox.py

Richiede le variabili d'ambiente:
    SIMPLYBOOK_SANDBOX_COMPANY_LOGIN
    SIMPLYBOOK_SANDBOX_API_KEY
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.bookings.adapters.simplybook_adapter import ADMIN_URL, SimplyBookAdapter
from src.core.bookings.ports.base import CancelBookingRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sandbox-sweep")

SENTINEL = "[TEST-MELPIS]"


async def run_sweep():
    company_login = os.getenv("SIMPLYBOOK_SANDBOX_COMPANY_LOGIN")
    api_key = os.getenv("SIMPLYBOOK_SANDBOX_API_KEY")

    if not company_login or not api_key:
        logger.info(
            "Variabili SIMPLYBOOK_SANDBOX_COMPANY_LOGIN o SIMPLYBOOK_SANDBOX_API_KEY non impostate. "
            "Nessun account sandbox configurato; sweep ignorato in modo sicuro."
        )
        return

    adapter = SimplyBookAdapter(company_login=company_login, api_key=api_key)
    try:
        logger.info("Avvio connessione alla sandbox SimplyBook (%s)...", company_login)
        # Recupera le prenotazioni recenti/future tramite getBookings admin RPC
        bookings_resp = await adapter._rpc_call(ADMIN_URL, "getBookings", [{"is_archive": 0}])
        if not isinstance(bookings_resp, list):
            logger.warning("Risposta inattesa da getBookings: %s", bookings_resp)
            return

        orfani = []
        for b in bookings_resp:
            client_name = b.get("client_name", "")
            comment = b.get("comment", "")
            if SENTINEL in client_name or SENTINEL in comment:
                orfani.append(b)

        logger.info("Trovate %d prenotazioni marcate come test orfani.", len(orfani))
        cancellati = 0
        for b in orfani:
            booking_id = str(b.get("id"))
            cancel_req = CancelBookingRequest(
                idempotency_key=f"sweep:{uuid.uuid4()}",
                external_booking_id=booking_id,
                motivo="Bonifica automatica periodica test orfani",
            )
            res = await adapter.cancel_booking(uuid.uuid4(), cancel_req)
            if res.success:
                cancellati += 1
                logger.info("Cancellata prenotazione test ID=%s", booking_id)
            else:
                logger.warning("Impossibile cancellare ID=%s: %s", booking_id, res.error_message)

        logger.info("Sweep completato con successo: %d/%d ripuliti.", cancellati, len(orfani))
    finally:
        await adapter.close()


if __name__ == "__main__":
    asyncio.run(run_sweep())
