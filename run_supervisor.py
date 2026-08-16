#!/usr/bin/env python3
"""
run_supervisor.py
------------------
Rete di sicurezza indipendente per i claim bloccati (audit 4.2). Gira come
servizio Docker separato, decoupled da worker-inbound e worker-retry: se uno
di quei worker crasha, muore anche la SUA chiamata interna a
reap_stale_claims() dentro il proprio loop -- questo processo esiste
apposta per liberare comunque i claim bloccati anche quando il worker che
li ha presi in carico non e' piu' vivo per farlo da solo.

Non sostituisce i reap interni di inbound_processor.py e retry_worker.py
(quelli restano, sono il percorso "veloce" quando il worker e' sano):
questo e' il fallback per quando non lo e'.
"""
import asyncio
import logging
import os
import asyncpg
from src.whatsapp.repository import Repository
from src.core.logging_filter import configure_logging

configure_logging(level=logging.INFO)
logger = logging.getLogger("supervisor")

REAP_TIMEOUT_MINUTES = int(os.getenv("SUPERVISOR_REAP_TIMEOUT_MINUTES", "15"))
DEAD_LETTER_THRESHOLD = int(os.getenv("SUPERVISOR_DEAD_LETTER_THRESHOLD", "3"))
LOOP_INTERVAL_SECONDS = int(os.getenv("SUPERVISOR_LOOP_INTERVAL_SECONDS", "30"))


async def main():
    dsn = os.getenv("DATABASE_URL", "")
    if not dsn:
        logger.error("DATABASE_URL non impostata, il supervisor non puo' partire.")
        return
    pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=2)
    repo = Repository(pool)
    logger.info(
        "Supervisor avviato: timeout=%s min, dead_letter_threshold=%s, intervallo=%ss",
        REAP_TIMEOUT_MINUTES, DEAD_LETTER_THRESHOLD, LOOP_INTERVAL_SECONDS,
    )
    while True:
        try:
            reaped = await repo.reap_stale_claims(
                timeout_minutes=REAP_TIMEOUT_MINUTES,
                dead_letter_threshold=DEAD_LETTER_THRESHOLD,
            )
            dead = [r for r in reaped if r.get("status") == "dead"]
            if dead:
                logger.warning(
                    "%s messaggi marcati 'dead' dopo %s re-claim consecutivi: ids=%s",
                    len(dead), DEAD_LETTER_THRESHOLD, [str(r["id"]) for r in dead],
                )
            recovered = [r for r in reaped if r.get("status") != "dead"]
            if recovered:
                logger.info("%s claim stale liberati e rimessi in coda", len(recovered))
        except Exception as e:
            # Il supervisor non deve mai morire per un errore transitorio
            # sul DB (es. connessione persa momentaneamente): logga e ritenta
            # al giro successivo, e' l'unica rete di sicurezza rimasta.
            logger.error("Errore nel ciclo di reap: %s", e)
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
