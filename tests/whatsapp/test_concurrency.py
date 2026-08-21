"""
Test di concorrenza REALI per il design v2 (P0_implementation_plan_v2_concurrency_safe.md).

Questi test NON usano mock. Aprono connessioni asyncpg vere contro un Postgres
reale (vedi docker-compose.test.yml) e lanciano coroutine concorrenti con
asyncio.gather per riprodurre lo scenario "due worker sullo stesso messaggio"
e "N messaggi concorrenti sullo stesso org".

Come eseguirli:
    docker compose -f docker-compose.test.yml up -d --wait
    pip install asyncpg pytest pytest-asyncio --break-system-packages
    pytest test_concurrency.py -v
    docker compose -f docker-compose.test.yml down -v

Nota per chi adatta questo file al codebase reale: le funzioni claim_and_bill(),
mark_sent() e get_or_generate_ai_reply() qui sotto implementano ESATTAMENTE la
sequenza SQL descritta nel piano v2 (§2), fuori da qualunque livello applicativo
specifico. Se il vostro repository.py/inbound_processor.py fa qualcosa di
diverso da questa sequenza, il test non vi protegge — allineate il codice a
questa sequenza, non il contrario.
"""

import asyncio
import os
import uuid

import asyncpg
import pytest



# ---------------------------------------------------------------------------
# Setup schema minimale, isolato dal resto del progetto
# ---------------------------------------------------------------------------

SCHEMA = """
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS organizations;

CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    messages_used_this_period INT NOT NULL DEFAULT 0,
    messages_limit INT NOT NULL
);

CREATE TABLE messages (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL REFERENCES organizations(id),
    billed_at TIMESTAMPTZ,
    ai_reply_cache TEXT,
    ai_reply_generated_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    quota_exceeded_at TIMESTAMPTZ,
    processing_at TIMESTAMPTZ
);
"""


@pytest.fixture
async def pool(postgres_container):
    dsn = postgres_container.get_connection_url().replace("+psycopg2", "")
    pool = await asyncpg.create_pool(dsn, min_size=5, max_size=20)
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)
    yield pool
    await pool.close()


# ---------------------------------------------------------------------------
# Implementazione di riferimento della sequenza del design v2
# ---------------------------------------------------------------------------

# Contatori globali per verificare che le chiamate "costose" (AI, Meta)
# avvengano il numero di volte corretto, indipendentemente da quanti
# worker/retry concorrenti ci provano.
ai_call_counter = {"count": 0}
meta_send_counter = {"count": 0}


async def fake_call_ai(pool, msg_id) -> str:
    """Simula la chiamata costosa all'AI. Conta le invocazioni reali."""
    ai_call_counter["count"] += 1
    await asyncio.sleep(0.01)  # simula latenza di rete
    return f"risposta-generata-per-{msg_id}"


async def fake_send_to_meta(pool, msg_id, text) -> str:
    """Simula l'invio a Meta. Conta le invocazioni reali."""
    meta_send_counter["count"] += 1
    await asyncio.sleep(0.01)
    return f"meta-msg-id-{uuid.uuid4()}"


async def process_message_once(pool: asyncpg.Pool, msg_id, org_id):
    """
    Implementa ESATTAMENTE la sequenza del piano v2 §2:
    lock riga messaggio -> check/incrementa quota atomicamente ->
    claim billing -> (fuori tx) chiama AI se serve -> invia se serve.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT billed_at, ai_reply_cache, sent_at, quota_exceeded_at, processing_at "
                "FROM messages WHERE id = $1 FOR UPDATE",
                msg_id,
            )

            if row["sent_at"] is not None:
                return "already_sent"

            if row["quota_exceeded_at"] is not None:
                return "quota_exceeded"
                
            if row["processing_at"] is not None and row["ai_reply_cache"] is None:
                # Un altro worker sta generando la risposta AI adesso
                return "currently_processing"

            if row["billed_at"] is None:
                incremented = await conn.fetchrow(
                    "UPDATE organizations "
                    "SET messages_used_this_period = messages_used_this_period + 1 "
                    "WHERE id = $1 AND messages_used_this_period < messages_limit "
                    "RETURNING messages_used_this_period",
                    org_id,
                )
                if incremented is None:
                    await conn.execute(
                        "UPDATE messages SET quota_exceeded_at = now() WHERE id = $1",
                        msg_id,
                    )
                    return "quota_exceeded"

                await conn.execute(
                    "UPDATE messages SET billed_at = now() WHERE id = $1", msg_id
                )
                
            if row["ai_reply_cache"] is None:
                await conn.execute(
                    "UPDATE messages SET processing_at = now() WHERE id = $1", msg_id
                )

            # ai_reply_cache letto/scritto FUORI da questa transazione,
            # ma dentro il blocco "with conn.acquire()" per riusare la stessa
            # connessione in modo semplice nel test; nel codice reale, la tx
            # va chiusa qui e la cache va scritta con una query separata.
            reply_cache = row["ai_reply_cache"]

        # --- fuori dalla transazione: chiamate esterne ---
        if reply_cache is None:
            reply = await fake_call_ai(pool, msg_id)
            await conn.execute(
                "UPDATE messages SET ai_reply_cache = $1, ai_reply_generated_at = now() "
                "WHERE id = $2",
                reply,
                msg_id,
            )
        else:
            reply = reply_cache

        meta_id = await fake_send_to_meta(pool, msg_id, reply)
        await conn.execute(
            "UPDATE messages SET sent_at = now() WHERE id = $1", msg_id
        )
        return "sent"


# ---------------------------------------------------------------------------
# I test veri
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_double_billing_two_workers_same_message(pool):
    """Due worker processano LO STESSO messaggio in parallelo:
    la quota deve incrementare di 1, non di 2."""
    ai_call_counter["count"] = 0
    org_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, messages_limit) VALUES ($1, 100)", org_id
        )
        await conn.execute(
            "INSERT INTO messages (id, org_id) VALUES ($1, $2)", msg_id, org_id
        )

    await asyncio.gather(
        process_message_once(pool, msg_id, org_id),
        process_message_once(pool, msg_id, org_id),
    )

    async with pool.acquire() as conn:
        used = await conn.fetchval(
            "SELECT messages_used_this_period FROM organizations WHERE id = $1", org_id
        )
    assert used == 1, f"Atteso incremento di 1, trovato {used}"


@pytest.mark.asyncio
async def test_no_double_ai_call_or_send_same_message(pool):
    """Due worker sullo stesso messaggio: l'AI e l'invio a Meta devono
    avvenire esattamente una volta ciascuno, non due."""
    ai_call_counter["count"] = 0
    meta_send_counter["count"] = 0
    org_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, messages_limit) VALUES ($1, 100)", org_id
        )
        await conn.execute(
            "INSERT INTO messages (id, org_id) VALUES ($1, $2)", msg_id, org_id
        )

    await asyncio.gather(
        process_message_once(pool, msg_id, org_id),
        process_message_once(pool, msg_id, org_id),
    )

    assert ai_call_counter["count"] == 1, (
        f"L'AI e' stata chiamata {ai_call_counter['count']} volte, attesa 1"
    )
    assert meta_send_counter["count"] == 1, (
        f"Meta e' stato chiamato {meta_send_counter['count']} volte, attesa 1"
    )


@pytest.mark.asyncio
async def test_retry_after_meta_failure_reuses_ai_cache(pool):
    """Simula: prima chiamata genera la risposta AI ma 'crasha' prima
    dell'invio (sent_at rimane NULL). Il retry NON deve richiamare l'AI."""
    ai_call_counter["count"] = 0
    org_id = uuid.uuid4()
    msg_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, messages_limit) VALUES ($1, 100)", org_id
        )
        await conn.execute(
            "INSERT INTO messages (id, org_id, billed_at, ai_reply_cache) "
            "VALUES ($1, $2, now(), 'risposta-gia-generata')",
            msg_id,
            org_id,
        )

    result = await process_message_once(pool, msg_id, org_id)

    assert result == "sent"
    assert ai_call_counter["count"] == 0, "L'AI non doveva essere richiamata: c'era gia' la cache"


@pytest.mark.asyncio
async def test_quota_hard_limit_never_exceeded_under_concurrency(pool):
    """N messaggi diversi, concorrenti, stesso org, quota residua < N:
    non deve MAI passare più della quota residua, indipendentemente
    dall'ordine di esecuzione dei worker."""
    org_id = uuid.uuid4()
    residual_quota = 3
    n_messages = 10

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO organizations (id, messages_limit, messages_used_this_period) "
            "VALUES ($1, $2, 0)",
            org_id,
            residual_quota,
        )
        msg_ids = [uuid.uuid4() for _ in range(n_messages)]
        for mid in msg_ids:
            await conn.execute(
                "INSERT INTO messages (id, org_id) VALUES ($1, $2)", mid, org_id
            )

    results = await asyncio.gather(
        *[process_message_once(pool, mid, org_id) for mid in msg_ids]
    )

    sent_count = results.count("sent")
    quota_exceeded_count = results.count("quota_exceeded")

    assert sent_count == residual_quota, (
        f"Attesi esattamente {residual_quota} messaggi passati, trovati {sent_count}"
    )
    assert quota_exceeded_count == n_messages - residual_quota

    async with pool.acquire() as conn:
        used = await conn.fetchval(
            "SELECT messages_used_this_period FROM organizations WHERE id = $1", org_id
        )
    assert used == residual_quota, "La quota non deve MAI superare il limite impostato"
