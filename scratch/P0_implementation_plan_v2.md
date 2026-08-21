# P0 Blockers — Piano di Implementazione v2 (Concurrency-Safe)

**Contesto**: Il tentativo v1 (branch `fix/p0-blockers`) è stato bocciato da QA/Security per 3 bug di concorrenza distinti. Rollback già eseguito. Questo documento sostituisce integralmente `P0_implementation_plan.md` per P0-1, P0-2, P0-3. P0-4 (Cancellation UI) non è toccato da questi problemi e resta valido così com'era.

---

## 0. Perché il tentativo v1 si è rotto (recap)

| # | Problema | Causa radice |
|---|----------|---------------|
| 1 | Quota Drain / Silent Bypass | Incremento della quota org fatto come operazione **separata** dal claim del messaggio, non atomica rispetto a se stessa sotto concorrenza |
| 2 | Outbox Race (doppio invio) | Nessun lock che serializzi due worker sullo **stesso** messaggio prima di chiamare l'AI/Meta |
| 3 | Spreco costi OpenAI | Nessuna cache della risposta AI già generata; il retry richiama il modello da zero |

**Principio guida per v2**: il claim del messaggio, il check della quota, e il lock anti-doppio-invio devono avvenire in **una sola transazione Postgres**, non in step separati coordinati "a mano" in Python.

---

## 1. Schema DB (sostituisce la proposta della colonna `billed` singola)

Invece di un solo booleano, usiamo uno **state machine per messaggio** con colonne dedicate — più debuggabile e permette di distinguere gli stati invece di dedurli:

```sql
ALTER TABLE messages
  ADD COLUMN billed_at TIMESTAMPTZ,           -- quando è stata scalata la quota (NULL = non ancora)
  ADD COLUMN ai_reply_cache TEXT,              -- risposta AI generata, per evitare rigenerazione su retry
  ADD COLUMN ai_reply_generated_at TIMESTAMPTZ,
  ADD COLUMN sent_at TIMESTAMPTZ,              -- quando è stato inviato a Meta (NULL = non ancora)
  ADD COLUMN meta_message_id VARCHAR(255),     -- id ritornato da Meta, per audit/debug
  ADD COLUMN quota_exceeded_at TIMESTAMPTZ;    -- se non nullo, il messaggio è stato scartato per limite raggiunto

-- source_message_id per P0-1 (booking idempotency) resta come da piano v1, invariato
```

Nota: manteniamo `messages_used_this_period` sulla tabella `organizations` (o dove già vive), ma il suo incremento **non è più un'operazione Python separata** — vedi §3.

---

## 2. Sequenza operativa corretta (sostituisce interamente la logica di `_process_one`)

```
1. BEGIN transaction
2. SELECT id, billed_at, ai_reply_cache, sent_at FROM messages WHERE id = $msg_id FOR UPDATE
   → Questo lock serializza QUALSIASI altro worker che tenti di processare lo stesso messaggio.
     Se un secondo worker prova a fare lo stesso SELECT FOR UPDATE, si blocca finché
     il primo non fa COMMIT/ROLLBACK. Appena sblocca, vede lo stato aggiornato e agisce
     di conseguenza (non riparte da zero). QUESTO RISOLVE IL PROBLEMA 2 (outbox race).

3. IF sent_at IS NOT NULL:
     → il messaggio è già stato inviato con successo in un run precedente.
     → COMMIT (no-op), marca come completato, esci. Non richiamare mai più l'AI né Meta.

4. IF billed_at IS NULL:
     -- non ancora fatturato: proviamo a riservare la quota ATOMICAMENTE, nella stessa tx
     UPDATE organizations
        SET messages_used_this_period = messages_used_this_period + 1
      WHERE id = $org_id
        AND messages_used_this_period < messages_limit
      RETURNING messages_used_this_period;

     IF 0 righe ritornate:
        -- quota esaurita: NON abbiamo speso nulla, possiamo abortire pulito
        UPDATE messages SET quota_exceeded_at = now() WHERE id = $msg_id;
        COMMIT
        → gestisci fallback per il cliente (vedi §5), esci. QUESTO RISOLVE IL PROBLEMA 1
          (silent bypass), perché il check-e-incremento sono UN'UNICA operazione atomica
          rispetto a qualsiasi altro messaggio concorrente dello stesso org.

     ELSE:
        UPDATE messages SET billed_at = now() WHERE id = $msg_id;

5. COMMIT transaction
   -- Fine della parte "critica" a livello DB. Da qui in poi, se il worker crasha,
   -- il prossimo retry rientrerà al punto 2 e troverà billed_at valorizzato,
   -- quindi NON scalerà di nuovo la quota (RISOLVE IL PROBLEMA 1, lato "drain").

6. IF ai_reply_cache IS NULL:
     risposta = await genera_risposta_ai(...)          # chiamata costosa
     UPDATE messages SET ai_reply_cache = risposta,
                          ai_reply_generated_at = now()
      WHERE id = $msg_id
   ELSE:
     risposta = ai_reply_cache   # riusa quella già pagata — RISOLVE IL PROBLEMA 3

7. esito = await invia_a_meta(risposta, msg_id)          # chiamata di rete
   IF esito.success:
        UPDATE messages SET sent_at = now(), meta_message_id = esito.id
        WHERE id = $msg_id
        try_mark_replied(msg_id)   # comportamento P0-2 originale, invariato
   ELSE:
        -- non fare nulla di distruttivo: il messaggio resta "billed" ma non "sent".
        -- il retry successivo rientrerà al punto 2, troverà billed_at valorizzato
        -- e ai_reply_cache valorizzato, quindi salterà DIRETTAMENTE al punto 7
        -- (nessun nuovo addebito, nessuna nuova chiamata AI).
        lascia il messaggio in coda per retry (comportamento esistente del supervisor)
```

**Punto critico da comunicare al developer**: gli step 2–5 (lock, check quota, claim billing) DEVONO stare in un'unica transazione Postgres esplicita (`async with conn.transaction():`). Gli step 6–7 (chiamata AI, chiamata Meta) DEVONO stare **fuori** da quella transazione — non si tiene mai una transazione DB aperta a cavallo di chiamate HTTP esterne potenzialmente lente (rischio di lock prolungati e connection pool esaurito).

---

## 3. Integrazione con P0-1 (booking idempotency) — lo short-circuit richiesto da QA

Prima di eseguire lo step 6 (chiamata AI) per messaggi che sappiamo essere di tipo "prenotazione":

```sql
SELECT id FROM bookings
WHERE organization_id = $org_id AND source_message_id = $msg_id;
```

Se esiste già una booking per questo `source_message_id`, **non richiamare l'AI**: si sa già che la prenotazione è andata a buon fine in un tentativo precedente (probabilmente crashato dopo l'INSERT ma prima del salvataggio di `ai_reply_cache`/`sent_at`). In questo caso:
- se `ai_reply_cache` è vuoto, generare una risposta di conferma standard/template (non una nuova chiamata LLM costosa) usando i dati della booking già esistente;
- procedere allo step 7 come da flusso normale.

Questo chiude il problema 3 anche per il caso limite in cui il crash avviene tra l'INSERT della booking e il salvataggio della cache della risposta.

---

## 4. Cosa NON deve più fare il codice (esplicitamente vietato)

- ❌ Incrementare `messages_used_this_period` in Python con un check-then-act separato dal claim (`if used < limit: increment`) — è la race condition originale.
- ❌ Chiamare `_send_ai_reply` o l'endpoint Meta **prima** di aver acquisito il lock `SELECT ... FOR UPDATE` sul messaggio.
- ❌ Rigenerare la risposta AI se `ai_reply_cache` è già valorizzato.
- ❌ Tenere aperta una transazione Postgres durante una chiamata HTTP esterna (AI o Meta).
- ❌ Usare solo un booleano `billed` senza distinguere gli stati "fatturato ma non ancora inviato" da "inviato con successo" — serve a evitare doppio invio dopo che il billing è già stato claimed.

---

## 5. UX per il caso `quota_exceeded`

Da decidere esplicitamente col team prodotto prima dell'implementazione (manca nel piano v1 originale):
- opzione A: risposta automatica generica al cliente ("stiamo ricevendo molte richieste, ti risponderemo a breve") senza intervento umano;
- opzione B: escalation immediata a un operatore umano/notifica al titolare dell'attività;
- **non è accettabile** che il messaggio sparisca senza alcun riscontro — ricrea il problema che P0-2 doveva risolvere, solo per un'altra via.
*Scelta stabilita:* Fallback stringa ("Stiamo ricevendo troppe richieste...") + escalation umano, marcato come `quota_exceeded`.

---

## 6. Piano di esecuzione (agenti coinvolti)

1. **Architect Agent**: revisiona e approva questo documento; produce la migration SQL definitiva (§1) e le firme di funzione aggiornate per `repository.py` e `inbound_processor.py`.
2. **Developer Agent**: implementa su nuovo branch `fix/p0-blockers-v2`, seguendo *esattamente* la sequenza §2 — nessuna deviazione senza segnalarla.
3. **QA Agent**: esegue la suite di test §7, **inclusi i test di concorrenza reale** (non solo simulazioni sequenziali di crash-retry come nel piano v1).
4. **Security Agent**: verifica specificamente che non esistano finestre temporali in cui una chiamata esterna (AI/Meta) possa avvenire senza che il claim/lock sia già stato committato.
5. Solo con tutti e 4 i via libera → merge in `main`.

---

## 7. Test obbligatori prima del merge

I bug del tentativo v1 sono emersi da concorrenza reale, non da logica sequenziale — quindi i test devono simulare **worker realmente concorrenti**, non solo "crash simulato + retry in sequenza".

```python
# Esempio concettuale — da adattare allo stack di test esistente (pytest-asyncio + DB reale, non mock)

async def test_no_double_billing_under_concurrent_retries():
    """Due worker processano lo stesso msg_id in parallelo: la quota deve
    incrementare di 1, non di 2."""
    await asyncio.gather(
        process_message(msg_id, worker="A"),
        process_message(msg_id, worker="B"),
    )
    org = await get_org(org_id)
    assert org.messages_used_this_period == used_before + 1

async def test_no_double_send_under_concurrent_workers():
    """Due worker processano lo stesso msg_id in parallelo: Meta deve
    ricevere una sola chiamata di invio."""
    ...
    assert meta_send_mock.call_count == 1

async def test_no_ai_regeneration_on_retry_after_meta_failure():
    """Meta fallisce al primo tentativo: il retry NON deve richiamare l'AI
    una seconda volta, deve riusare ai_reply_cache."""
    ...
    assert ai_call_mock.call_count == 1

async def test_quota_exceeded_does_not_bill():
    """Org già al limite: nessun incremento, nessuna chiamata AI, nessun invio."""
    ...
    assert ai_call_mock.call_count == 0
    assert meta_send_mock.call_count == 0

async def test_concurrent_messages_same_org_respect_hard_limit():
    """N messaggi concorrenti diversi per lo stesso org con quota residua < N:
    esattamente 'quota residua' devono passare, il resto deve finire in
    quota_exceeded_at, mai sforare il limite."""
    ...

async def test_booking_short_circuit_skips_ai_on_retry():
    """Retry dopo che la booking è già stata creata: non deve chiamare l'AI,
    deve riusare/generare la conferma dal dato esistente."""
    ...
    assert ai_call_mock.call_count == 0
```

Tutti questi test vanno eseguiti contro un **Postgres reale** (container di test), non contro mock del DB — è proprio il comportamento delle transazioni/lock di Postgres sotto concorrenza che va verificato, e un mock non lo riprodurrebbe.

---

## 8. Checklist pre-merge

- [ ] Migration SQL applicata e testata (rollback della migration testato anche lui)
- [ ] Nessuna chiamata esterna (AI/Meta) dentro una transazione DB aperta
- [ ] Lock `SELECT ... FOR UPDATE` acquisito prima di qualunque side-effect
- [ ] Tutti i test di §7 verdi, eseguiti contro Postgres reale
- [ ] UX per `quota_exceeded` decisa e implementata (non silenziosa)
- [ ] Short-circuit booking→AI verificato per P0-1
- [ ] Code review incrociata Developer↔Security specificamente sulla finestra temporale tra lock e chiamata esterna
- [ ] Nessuna regressione sui test esistenti di P0-1/P0-2/P0-4 già scritti in precedenza
