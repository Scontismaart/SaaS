# Review: Robustezza Payload Meta e Webhook Status (Task 7)

## Problemi riscontrati e correzioni

### 1. `biz_opaque_callback_data` non validato come UUID
**Problema:** `_handle_status_update` chiamava `uuid.UUID(biz_data)` senza try/except. Se Meta inviava una stringa non-UUID, crash 500 ripetuto (poison-message loop).

**Correzione:** try/except ValueError. Se UUID fallisce, log strutturato `webhook_invalid_callback_data` + fallback a `update_message_status_by_wam_id` (wam_id garantito da Meta). Nessuna perdita di aggiornamenti stato.

### 2. `contacts` assente/vuoto in `_handle_inbound_message`
**Problema:** `contacts[0].profile.name` su array vuoto crasha. L'accesso era già protetto da `if contacts` ma mancava logging esplicito.

**Correzione:** aggiunto `logger.warning` se contacts è vuoto/None. Il messaggio procede comunque usando `from_number`.

### 3. Batch isolation — no `except Exception`
**Problema:** Catturare genericamente `Exception` e continuare il batch risponde 200 a Meta anche se il DB è giù → Meta cancella il batch dalla coda → **perdita dati**.

**Correzione:** Nessun `except Exception` nel loop. Solo eccezioni di validazione (ValueError su UUID) sono gestite localmente dentro `_handle_status_update`. Errori infrastrutturali (asyncpg, timeout) si propagano → FastAPI → **500**, Meta ritenta il batch.

### 4. Idempotenza — tabella `webhook_idempotency`
**Problema:** Nessuna protezione contro duplicati. Meta ritenta su timeout/500 e processiamo lo stesso messaggio più volte.

**Correzione:** Nuova tabella `webhook_idempotency` con PK `(wam_id, resource_type, status_value)`. La tripla PK è **essenziale** perché:
- Stesso wam_id può avere `sent` → `delivered` → `read` (transizioni sequenziali)
- Senza `status_value` nella PK, `read` sarebbe scartato come falso duplicato di `sent`
- `resource_type` distingue `'message'` da `'status'`

Inserimento atomico via `INSERT ... ON CONFLICT DO NOTHING RETURNING wam_id`:
- Nessuna race condition (no SELECT + INSERT separati)
- Se `RETURNING` restituisce riga → nuovo evento, procedi
- Se `None` → conflitto, skip

## Files modificati

### Nuovi
- `src/core/db/migrations/013_webhook_idempotency.sql` — tabella + indice su created_at
- `src/whatsapp/idempotency.py` — funzione `dedup_check(pool, wam_id, resource_type, status_value) -> bool`

### Modificati
- `src/whatsapp/router.py`:
  - `_handle_status_update`: UUID try/except + fallback wam_id + idempotenza
  - `_handle_inbound_message`: idempotenza + log contatti vuoti
  - Batch loop: nessun `except Exception` (errori infrastruttura → 500)
  - Import `dedup_check` da `src.whatsapp.idempotency`
- `tests/whatsapp/conftest.py`: carica `013_webhook_idempotency.sql`, TRUNCATE tabella
- `tests/core/conftest.py`: carica `013_webhook_idempotency.sql`, TRUNCATE tabella
- `tests/whatsapp/test_router.py`: mock_repo con `pool.fetchrow`, 7 nuovi test

## Test (7 nuovi)

| Test | Payload | Risultato |
|------|---------|-----------|
| `test_post_status_non_uuid_callback_fallback` | `biz_opaque_callback_data: "not-a-uuid"` + secondo valido | 200, `webhook_invalid_callback_data` log, fallback via wam_id, secondo via UUID |
| `test_post_status_idempotent_skip` | Stesso status inviato 2x | 200, `update_message_status_by_wam_id` chiamato 1 sola volta |
| `test_post_inbound_idempotent_skip` | Stesso wam_id messaggio 2x | 200, `upsert_message` chiamato 1 sola volta |
| `test_post_batch_db_down_500` | `pool.fetchrow` solleva `InsufficientResourcesError` | **500** — Meta ritenta |
| `test_post_contacts_empty_log` | `contacts: []` + messaggio valido | 200, log, messaggio processato |
| `test_post_status_sequence_dedup_correct` | 3 status (`sent`/`delivered`/`read`) stesso wam_id | 200, 3 chiamate distinte |
| `test_post_batch_mixed_valid_invalid` | Status UUID invalido + messaggio valido | 200, status skippato con log, messaggio processato |

## Totale test suite: **298/298 passati** (+7 dalla baseline)

## Raccomandazioni (fuori scope)
- **Coda messaggi asincrona:** Disaccoppiare la validazione HMAC (sincrona) dall'elaborazione business (coda RabbitMQ/Redis Streams). Il router risponderebbe 200 a Meta dopo aver solo messo il payload in coda, eliminando il timeout dei 5-10s.
- **TTL cleanup job:** `DELETE FROM webhook_idempotency WHERE created_at < NOW() - INTERVAL '24 hours'` da schedulare periodicamente.
