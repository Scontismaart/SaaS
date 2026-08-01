# Task 6 — Review: Reply Guard & Heartbeat

## Problema

Due bug critici nel worker WhatsApp (`InboundProcessor`):

1. **Nessuna guardia su `replied_at`**: due worker possono processare lo stesso messaggio in parallelo e inviare la stessa risposta AI allo stesso utente (race condition). Il `claim_inbound_messages` usa `FOR UPDATE SKIP LOCKED`, ma dopo il claim il worker aspetta la risposta LLM (secondi/minuti) senza alcuna protezione contro un secondo claim.

2. **`reap_stale_claims` timeout fisso troppo basso**: usava `claimed_at` per decidere se un claim è stale. Se la latenza LLM supera il timeout (5-15 min), il reaper considera il claim morto e lo rimette in coda. Un secondo worker lo riprende, generando doppia risposta.

## Soluzione

### 1. Migrazione `012_reply_guard.sql`

Aggiunge due colonne alla tabella `messages`:

- `replied_at TIMESTAMPTZ` — flag atomico che dice "questo messaggio ha già ricevuto risposta". Usato come guardia nelle race condition.
- `heartbeat_at TIMESTAMPTZ` — timestamp periodicamente aggiornato dal worker mentre sta processando. Il reaper usa questo invece di `claimed_at` per decidere se un claim è stale.

### 2. `src/whatsapp/repository.py` — 3 cambiamenti

**`claim_inbound_messages()`**:
- Aggiunto `AND replied_at IS NULL` nella WHERE per non reclamare messaggi già risposti
- Aggiunto `heartbeat_at = NOW()` nel SET per inizializzare l'heartbeat all'atto del claim

**Nuovo `try_mark_replied(message_id)`**:
- UPDATE atomico: `SET replied_at = NOW(), status = 'handled', updated_at = NOW()`
- WHERE `id = $1 AND replied_at IS NULL`
- RETURNING * — restituisce il record solo se vince la race
- Restituisce `None` se un altro worker ha già marcato il messaggio come risposto

**Nuovo `update_heartbeat(message_id)`**:
- UPDATE: `SET heartbeat_at = NOW() WHERE id = $1`
- Chiamato periodicamente dal worker per segnalare "sono ancora vivo"

**`reap_stale_claims()`**:
- Per i messaggi, usa `heartbeat_at` al posto di `claimed_at`:
  - Se `heartbeat_at IS NOT NULL`: considera stale solo se `heartbeat_at < NOW() - timeout`
  - Se `heartbeat_at IS NULL` (backward compat, record pre-migrazione): cade su `claimed_at`
- Per `message_delivery_attempts`: invariato (usa `claimed_at`, non hanno heartbeat)
- Resetta anche `heartbeat_at = NULL` quando un messaggio viene rimesso in coda

### 3. `src/whatsapp/inbound_processor.py` — heartbeat + guardia atomica

**`_heartbeat_loop(msg_id)`**:
- Task in background (`asyncio.ensure_future`) lanciato prima della chiamata LLM
- Ogni 30 secondi chiama `repo.update_heartbeat(msg_id)`
- Cancellato via `CancelledError` quando la risposta LLM arriva (try/finally)

**Tutti i path di uscita ora usano `try_mark_replied()`**:
- Opt-out: `try_mark_replied()` invece di `update_message_status("handled")`
- Booking reply: `try_mark_replied()` invece di `update_message_status("handled")`
- Fast-path: `if try_mark_replied(): send_reply()` — se un altro worker ha già risposto, salta
- AI escalation: `try_mark_replied()` invece di `update_message_status("escalated")`
- AI reply: `if try_mark_replied(): send_reply()` — guardia atomica prima dell'invio WhatsApp

### 4. Test di race condition

Nuovo `test_race_condition_only_one_reply_sent` in `tests/whatsapp/test_inbound_processor.py`:

```python
# Due worker simulati che processano lo stesso messaggio in parallelo.
# try_mark_replied restituisce il record solo al primo worker che lo chiama;
# il secondo riceve None e salta l'invio.
# Risultato: una sola chiamata a send_whatsapp_message.
```

- `try_mark_replied` mockato con side_effect: prima chiamata → successo, seconda → None
- `asyncio.gather(proc1.process_next_batch(), proc2.process_next_batch())`
- Assert: `send_whatsapp_message.await_count == 1`

## Files modificati

| File | Cambiamento |
|---|---|
| `src/core/db/migrations/012_reply_guard.sql` | **Nuovo** — colonne replied_at e heartbeat_at |
| `src/whatsapp/repository.py` | claim_inbound_messages + try_mark_replied + update_heartbeat + reap_stale_claims |
| `src/whatsapp/inbound_processor.py` | Heartbeat loop + try_mark_replied guardia su tutti i path |
| `tests/whatsapp/test_inbound_processor.py` | Mock aggiornati + nuovo test race condition |
| `tests/core/conftest.py` | Carica 012_reply_guard.sql |
| `tests/whatsapp/conftest.py` | Carica 012_reply_guard.sql |

## Test result

```bash
python -m pytest -v
# 281 passed, 4 warnings
```
