# Review — Task 8: Prenotazioni come prodotto standalone

**Data:** 2026-07-29
**Branch:** main
**Tipo:** feature esistente estesa/migrata (Punto 8 roadmap)

---

## Riepilogo

Il modulo prenotazioni era già implementato al ~80% (BookingService, reminder,
no-show, deposito Stripe, route API, scheduler). Questa task ha chiuso i buchi
nel wiring AI → prenotazione reale, pulito il legacy, e applicato fix immediati.

---

## Fase 0 — Fix immediati

### 0.1 — Mutable default in reject_booking
**File:** `src/core/bookings/routes.py:92-94`
**Prima:** `body: dict = {}` (flagged da ruff)
**Dopo:** `body: dict | None = None` + `body = body or {}` dentro la funzione

### 0.2 — POSTGRES_DSN → DATABASE_URL
**File:** `scripts/migrate_airtable_to_bookings.py:115`
**Prima:** `parser.add_argument("--dsn", default=os.getenv("POSTGRES_DSN"))`
**Dopo:** `parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"))`

### 0.3 — Idempotenza migration script
**File:** `scripts/migrate_airtable_to_bookings.py:86-110`
Prima di ogni insert, controlla se esiste già un booking con stessa
`id_conversazione` + `organization_id`. Se sì, skip con contatore `skipped`.
Se `id_conversazione` è vuoto, logga un warning che ri-esecuzione duplicherà.
Aggiunto contatore `inserted` esplicito (prima era perso).

### 0.4 — Worktree abbandonato rimosso
- Branch `feature/whatsapp-integration` eliminato
- Worktree `.worktrees/whatsapp-integration/` rimosso
- Verificato: la versione dello script di migrazione nel worktree era più
  vecchia (24/07) e mancava dello `STATO_MAP` fix presente su main (26/07)

---

## Fase 1 — Wiring AI → prenotazione reale

### 1.1 — BookingService init in lifespan (bug fix)
**File:** `src/api/main.py:104-152`
**Problema:** `booking_service` veniva inizializzato SOLO nel ramo `else`
(DATABASE_URL assente). Quando `DATABASE_URL` era presente, `app.state.booking_service`
non veniva mai settato — le route `/api/bookings/*` fallivano con 503.
**Fix:**
- Ramo `if dsn / try`: aggiunto `BookingService` con `CoreRepository(pool)`,
  `WhatsAppService(whatsapp_app_config, wrepo)`, `app_config=whatsapp_app_config`
- Ramo `except` (DB connessione fallita): aggiunto `BookingService` fallback
  con pool=None (stessa logica del ramo `else`)

### 1.2 — AI booking creation in inbound_processor
**File:** `src/whatsapp/inbound_processor.py:113-144`
**Nuovo flusso** dopo `genera_risposta_async()`:
1. Se `risposta.prenotazione` ha `data`, `ora`, `copetri` validi:
   - Chiama `booking_service.create_booking(org_id, nome_cliente, telefono,
     data, ora, coperti, origine="WhatsApp", richiede_intervento=risposta.richiede_umano,
     id_conversazione=...)`
   - Successo → log `Booking created from AI response`
   - `SlotPienoError` → modifica `risposta.risposta` con alternative e setta
     `risposta.motivo = "slot_prenotazione_pieno"`
   - Altri errori → log, non blocca il flusso
2. Poi continua con `richiede_umano` check (escalation HITL) — la prenotazione
   è già stata creata come `in_attesa` indipendentemente dal flag

### 1.3 — SlotPienoError con alternative
**File:** `src/core/bookings/service.py:13-16` (nuova classe)
```python
class SlotPienoError(ValueError):
    def __init__(self, message, alternative=None):
        super().__init__(message)
        self.alternative = alternative or []
```
- `create_booking()` lancia `SlotPienoError` invece di `ValueError` generico
- Porta con sé `disp.alternative` calcolato da `verifica_disponibilita()`
- Chi cattura (inbound_processor, routes) usa `e.alternative` senza rifare query
- `__init__.py` esporta `SlotPienoError` nel package
- `routes.py` gestisce `SlotPienoError` separatamente con `{"messaggio", "alternative"}`

### 1.4 — Cleanup prenotazioni.py
**File:** `src/core/prenotazioni.py`
**Rimosso:**
- `_get_service()` — tentativo incompleto di usare BookingService, non serviva
  più perché ora BookingService è accessibile via `app.state`
- `salva_prenotazione_ai()` — sostituita dal flusso in `inbound_processor.py`
  e `main.py` (demo route)
- Import di `DatiPrenotazione`, `RispostaOutput` (non più usati)
**Mantenuto:** tutto il resto (variabili globali demo, `verifica_disponibilita`,
`crea_prenotazione_dashboard`, `elenco_prenotazioni`, `semaforo_giorno`, ecc.)
perché serve al dashboard demo (`/api/prenotazioni/*`)

### 1.5 — create_booking: nuovi parametri
**File:** `src/core/bookings/service.py:115-117`
**Aggiunti:**
- `richiede_intervento=False` — passato a `repo.create_booking()` per
  preservare il campo che il vecchio `salva_prenotazione_ai` settava
- `id_conversazione=""` — passato a `repo.create_booking()` per
  tracciabilità (e per idempotenza futura)
- Il `SlotPienoError` lanciato con le alternative invece del ValueError nudo

### Impatto sulla route demo
**File:** `src/api/main.py:313-346` (`POST /api/messaggio`)
La route demo (sincrona, no pool) continua a usare `crea_prenotazione_dashboard`
in memoria. Non può chiamare `BookingService` perché è sync. La produzione usa
`inbound_processor.py` che è async e ha accesso a `booking_service`.
Rimossa l'import di `salva_prenotazione_ai`, errore loggato con `print()`.

---

## File modificati (7)

| File | Righe ± | Cosa |
|------|---------|------|
| `src/core/bookings/__init__.py` | +1 | Export `SlotPienoError` |
| `src/core/bookings/service.py` | +16/-2 | `SlotPienoError`, `richiede_intervento`, `id_conversazione` |
| `src/core/bookings/routes.py` | +7/-2 | Mutable default fix + `SlotPienoError` catch |
| `src/whatsapp/inbound_processor.py` | +29/-2 | AI booking creation + slot pieno handling |
| `src/api/main.py` | +26/-2 | BookingService init in lifespan + cleanup demo route |
| `src/core/prenotazioni.py` | +0/-56 | Rimossi `_get_service`, `salva_prenotazione_ai`, import morti |
| `scripts/migrate_airtable_to_bookings.py` | +15/-7 | `DATABASE_URL`, idempotenza `id_conversazione` |
| `.worktrees/whatsapp-integration/` | — | Eliminato (worktree + branch) |

---

## Fase 2 — Airtable migration (manuale)

Script pronto. Esecuzione per ogni tenant:
```bash
python scripts/migrate_airtable_to_bookings.py <org_id>
```

### Prima di eseguire
- Verificare che `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `DATABASE_URL` siano
  settati in `.env`
- Eseguire prima su un tenant di test
- Controllare `SELECT COUNT(*) FROM bookings WHERE organization_id='<org>'`
- Verificare 3-4 record a caso nel dashboard
- Poi eseguire sui tenant reali uno alla volta

### Dopo migrazione verificata
- Rimuovere `airtable_client.py`
- Rimuovere `AIRTABLE_API_KEY`, `AIRTABLE_BASE_ID`, `AIRTABLE_TABLE_NAME`
  da `.env` e `.env.example`

---

## Fase 3 — Google Reserve

Bloccata. Non avviata.
