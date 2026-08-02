# Review: Webhook Resilience (Task 6)

## Files modificati

### 1. `src/whatsapp/client.py` — MetaClient hardening
- **Timeout**: 5s → 10s (generale), connect 3s → 5s, read aggiunto 10s
- **Retry**: 2 → 3 tentativi, backoff 1-10s → 2-30s (exponential, multiplier=2)
- **Logging**: `logger.warning` con status code + body su HTTPStatusError, messaggio su timeout/connect error
- **Test**: `test_send_message_5xx_retryable` ora controlla 3 call (era 2), nuovo `test_send_message_retry_3x_log` verifica log con `caplog`

### 2. `src/whatsapp/router.py` — Webhook router resilience
- **Body limit**: funzione `_read_limited_body()` con streaming chunked-aware, limite 5MB, log strutturato JSON su oversize con evento `webhook_body_oversize`, status 413
- **Replay protection**: header `X-Timestamp` opzionale, tolleranza ±300s, log `webhook_timestamp_rejected` (403) / `webhook_timestamp_invalid` (400)
- **HMAC log**: log JSON strutturato con evento `webhook_hmac_rejected` su firma invalida (prima era silenzioso)
- **JSON log**: log JSON strutturato con evento `webhook_json_invalid` su body malformato
- **Verify token**: usa `hmac.compare_digest` costante (prima confronto diretto)
- **Test**: `test_post_payload_oversize`, `test_post_hmac_rejection_log`, `test_post_timestamp_replay`, `test_post_timestamp_invalid`

### 3. `src/core/db/repository.py` — Repository
- Aggiunto `process_stripe_event_in_tx(conn, event_id, org_id)` — dedup INSERT che riusa connessione/transazione esistente

### 4. `src/core/billing/webhook_handler.py` — Stripe atomico
- Tutto il processing Stripe in un'unica transazione: `pool.acquire() + conn.transaction()` avvolge dispatch handler
- Ogni handler (`_handle_checkout_completed`, `_handle_invoice_paid`, etc.) ora riceve `conn` e usa `conn.execute()` dirette, non piu metodi repo che aprono connessioni autonome
- `_lookup_org_by_customer` ora accetta `conn` e fa query inline nella stessa connessione
- Booking deposit update usa `conn.execute("UPDATE bookings SET...")` invece di `repo.update_booking_payment()`
- Se crash a meta rollba tutto — evento NON risulta processato
- **Test**: `test_stripe_atomic_rollback_on_failure` — evento con `subscription=None` non scrive processed_stripe_events

### 5. `src/api/main.py` — Rate limit LLM globale + CORS + health check
- **CORS fail-closed**: `CORS_ORIGINS` splittato con `.strip()`, vuoto dopo strip → `RuntimeError`
- **CORS whitespace**: origini spaziate (`"http://a.com , http://b.com"`) pulite automaticamente
- **Rate limit LLM globale**: variabili `LLM_GLOBAL_RATE_LIMIT` (default 200) / `LLM_GLOBAL_RATE_WINDOW` (default 60s), chiave `"llm:global"`, applicato alle route `LLM_ROUTES = {"/api/messaggio", "/api/recensione", "/api/documenti/chiedi"}`
- `_rate_limit_check` parametrizzata con `limit`/`window_seconds` opzionali
- Health check potenziato: verifica pool DB con `SELECT 1`, ritorna 503 se degraded
- **Test**: `test_rate_limit_llm_global`, `test_cors_header_present`, `test_cors_whitespace_stripped`, `test_cors_fail_closed_on_empty`

### 6. `src/whatsapp/repository.py` — Reply guard + heartbeat
- **Migrazione `012_reply_guard.sql`**: colonne `replied_at` e `heartbeat_at` su `messages`
- `try_mark_replied(message_id)`: update atomico `WHERE replied_at IS NULL RETURNING *` — lock ottimistico replica unica
- `update_heartbeat(message_id)`: tocca `heartbeat_at = NOW()` per segnalare worker vivo
- `claim_inbound_messages`: ora setta `heartbeat_at = NOW()` all'acquisto, filtra `replied_at IS NULL`
- `reap_stale_claims`: usa `heartbeat_at` (fallback `claimed_at` se NULL), aggiunto `dead_letter_count` per dead letter dopo 3 reclamazioni fallite
- **Test**: `test_race_condition_only_one_reply_sent` — due worker async in `asyncio.gather`, mock `try_mark_replied` concede vittoria al primo, `send_whatsapp_message` chiamato 1 sola volta

### 7. `src/whatsapp/inbound_processor.py` — Heartbeat loop + reply guard integration
- `_heartbeat_loop(msg_id)`: task `asyncio.ensure_future` ogni 30s, cancellato dopo risposta AI
- Tutti i path (opt-out, reminder, fast-path, escalation, AI reply) ora chiamano `try_mark_replied` invece di `update_message_status`
- AI path: solo dopo `try_mark_replied` vincente procede con `_send_ai_reply`
- **Test**: mock `try_mark_replied` e `update_heartbeat` aggiunti al fixture `mock_repo`, race condition test

### 8. `tests/` — Riepilogo nuovi test
| Test | Cosa verifica |
|------|---------------|
| `test_send_message_retry_3x_log` | 3 tentativi, log con status+body |
| `test_post_payload_oversize` | 413 su body >5MB |
| `test_post_hmac_rejection_log` | 403 + log JSON `webhook_hmac_rejected` |
| `test_post_timestamp_replay` | 403 su timestamp vecchio |
| `test_post_timestamp_invalid` | 400 su timestamp non intero |
| `test_rate_limit_llm_global` | 429 dopo 2 chiamate su route LLM |
| `test_cors_header_present` | `access-control-allow-origin` presente |
| `test_cors_whitespace_stripped` | origini con spazi funzionano |
| `test_cors_fail_closed_on_empty` | `RuntimeError` su CORS vuoto |
| `test_stripe_atomic_rollback_on_failure` | rollback non lascia processed_stripe_events |
| `test_race_condition_only_one_reply_sent` | 2 worker paralleli, 1 sola reply |

## Totale test suite: **291/291 passati** (+10 dalla baseline di 281)
