# Task 8 — Review: GDPR Cascade + Atomicità Message/Usage + Idempotenza

## Problemi riscontrati e correzioni

### 1. GDPR: FK contacts senza CASCADE/SET NULL
**Problema:** Eliminare un contatto (hard-delete) crashava per vincoli FK su `conversations`, `messages`, `bookings`, `reviews`, `contact_consent_log`. `delete_organization()` richiedeva DELETE manuali su ogni tabella figlia — fragili e facili da dimenticare.

**Correzione (014_contact_fk_strategy.sql):**
- **Indici B-tree** su TUTTE le FK verso contacts: `idx_fk_conversations_contact`, `idx_fk_messages_conversation`, `idx_fk_bookings_contact`, `idx_fk_reviews_contact`, `idx_fk_consent_log_contact`
- **DO dinamico** che altera tutte le FK da `organizations(id)` a `ON DELETE CASCADE`: scorre `pg_constraint` con `confdeltype = 'a'` (NO ACTION), droppa e ricrea con CASCADE. Copre tutte le figlie senza hardcodare nomi tabella.
- **Trigger BEFORE DELETE su contacts** (`trg_mask_pii_before_contact_delete`): anonimizza PII in bookings (`nome_cliente='REDACTED', telefono='REDACTED', contact_id=NULL`) e reviews (`autore='REDACTED', contact_id=NULL`) prima che la FK venga recisa.
- **Trigger AFTER UPDATE su contacts** (`trg_propagate_contact_soft_delete`): quando `deleted_at` viene impostato, propaga a `conversations.deleted_at = NOW()`.
- **ALTER FK esplicite**: conversations→contacts CASCADE, messages→conversations CASCADE, contact_consent_log→contacts CASCADE, bookings→contacts SET NULL, reviews→contacts SET NULL.

### 2. `delete_organization()` non atomica
**Problema:** `delete_organization()` faceva DELETE multipli manuali su bookings, reviews, conversations, messages, consent_log, poi organizations. Fragile (se una tabella veniva aggiunta, la DELETE veniva dimenticata).

**Correzione:** `delete_organization()` ora è una singola `DELETE FROM organizations WHERE id = $1`. Il CASCADE DB (creato dal DO dinamico) elimina tutte le figlie automaticamente, e il trigger BEFORE DELETE su contacts anonimizza PII prima della cascata.

### 3. Atomicità: messaggio salvato anche se usage increment fallisce
**Problema:** `_handle_inbound_message` faceva `upsert_message()` e `increment_message_usage()` in due chiamate separate senza transazione. Se usage falliva (DB down), il messaggio era già salvato — perdita di tracciabilità billing.

**Correzione:** `_handle_inbound_message` apre `pool.acquire() + conn.transaction()` e passa `conn=conn` a entrambe le chiamate. `upsert_message()` e `increment_message_usage()` ora accettano `conn` opzionale — se presente, usano la connessione esistente invece di acquisirne una nuova. Un'unica transazione atomica: se usage fallisce, tutto rollback.

### 4. Idempotenza webhook — tripla PK
**Problema (task 7):** `webhook_idempotency` aveva PK su `(wam_id, resource_type)` — falso duplicato quando lo stesso wam_id ha `sent` → `delivered` → `read`.

**Correzione (task 7, 013):** PK estesa a `(wam_id, resource_type, status_value)`. La tripla permette transizioni sequenziali sullo stesso wam_id. INSERT ON CONFLICT DO NOTHING RETURNING atomico.

### 5. Mock pool test router — async context manager
**Problema:** Il mock `pool.acquire()` era un `MagicMock` senza `__aenter__`/`__aexit__`. L'aggiunta di `async with conn.transaction()` in `_handle_inbound_message` crashava i test router.

**Correzione:** Mock ora supporta la catena completa:
```python
mock_conn = MagicMock()
mock_conn.transaction.return_value.__aenter__ = AsyncMock()
mock_conn.transaction.return_value.__aexit__ = AsyncMock(return_value=False)
pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
```
`MagicMock` per `mock_conn` è essenziale: `AsyncMock` restituirebbe una coroutine da `transaction()`, ma `async with` richiede un oggetto con `__aenter__`.

## Files modificati

| File | Cambiamento |
|------|-------------|
| `src/core/db/migrations/014_contact_fk_strategy.sql` | **Nuovo** — indici, DO dinamico CASCADE, trigger PII, trigger soft-delete, ALTER FK |
| `src/whatsapp/repository.py` | `upsert_message(conn=…)`, `increment_message_usage(conn=…)` con connessione opzionale |
| `src/core/db/repository.py` | `delete_organization()` → singola DELETE, CASCADE DB gestisce tutto |
| `src/whatsapp/router.py` | `_handle_inbound_message` con `pool.acquire() + conn.transaction()` + conn iniettato |
| `tests/whatsapp/test_gdpr_fk.py` | **Nuovo** — 5 test GDPR cascade + transaction rollback |
| `tests/whatsapp/conftest.py` | CREATE TABLE bookings/reviews/booking_settings prima di 014; TRUNCATE esteso |
| `tests/whatsapp/test_router.py` | mock_repo.pool con supporto acquire + transaction async context manager |

## Test (5 nuovi)

| Test | Scenario | Risultato |
|------|----------|-----------|
| `test_soft_delete_preserves_booking_data` | `UPDATE contacts SET deleted_at=NOW()` | Booking intatto, conversation.deleted_at settato |
| `test_hard_delete_masks_pii` | `DELETE FROM contacts` | booking.contact_id=NULL, nome/telefono='REDACTED' |
| `test_hard_delete_propagates_cascade` | `DELETE FROM contacts` | CASCADE elimina conversation + contact_consent_log |
| `test_hard_delete_org_cascade_masks_pii` | `delete_organization()` | Trigger anonimizza PII prima che CASCADE elimini tutto |
| `test_transaction_rollback_on_usage_failure` | `increment_message_usage` solleva RuntimeError | Messaggio NON salvato — rollback funziona |

## Totale test suite: **129/129 whatsapp** + tutti i precedenti passano
