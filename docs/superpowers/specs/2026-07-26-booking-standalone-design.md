# Modulo Prenotazioni Standalone — Design Doc

**Data**: 2026-07-26
**Stato**: Bozza
**Roadmap**: Punto 8 (Prenotazioni come prodotto standalone)

---

## 0. Stato attuale

### 0.1 Cosa esiste già

- **Database**: tabelle `bookings` e `booking_settings` con schema multi-tenant (organization_id), già deployate (schema.sql)
- **Repository**: `CoreRepository` in `src/core/db/repository.py` con CRUD base (create_booking, get_booking, list_bookings, update_booking_status, get_booking_settings, upsert_booking_settings)
- **Business logic legacy**: `src/core/prenotazioni.py` — logica semaforo/capienze con variabili globali a livello di modulo (`_prenotazioni_demo`, `_capienze_orarie`, `_fasce_orarie`) + lettura da Airtable via `airtable_client.py`
- **WhatsApp**: `WhatsAppService.send_whatsapp_message()` già funzionante per invio messaggi
- **Scheduler**: `apscheduler` già integrato in `scheduler.py` con job per report e retention
- **Billing**: webhook Stripe in `billing/webhook_handler.py` già integrato
- **Auth**: middleware ruoli (owner, manager, staff) già in uso su altre route
- **Test**: `test_repository_bookings.py` (6 test) e `test_repository_booking_settings.py` (2 test)

### 0.2 Bug strutturale da risolvere

`prenotazioni.py` usa variabili globali di modulo (`_prenotazioni_demo`, `_capienze_orarie`, `_fasce_orarie`) non isolate per organizzazione. Con un solo tenant non si nota; con più tenant in produzione, Locale A che cambia le fasce orarie modifica anche le fasce di Locale B. Le prenotazioni demo (`_prenotazioni_demo`) sono una lista condivisa e non filtrata per org. Zero isolamento — bug di sicurezza/dati oltre che funzionale.

### 0.3 Punto 2 (multi-tenancy + DB) completato

La migrazione da Airtable a PostgreSQL nativo è già stata pianificata ed eseguita. Lo script `scripts/migrate_airtable_to_bookings.py` trasferisce i dati da Airtable a `bookings`. Questo design non ripianifica la migrazione — la dà per già fattibile e si concentra sulle nuove funzionalità.

### 0.4 Limite noto: isolamento app-level, non RLS

`bookings` e `booking_settings` usano lo stesso pattern di `conversations`, `messages`: colonna `organization_id` + filtro manuale in ogni query Python, **senza** Row-Level Security a livello Postgres. Se una query nel repository dimentica `WHERE organization_id = $1`, non c'è rete di sicurezza dal database (a differenza di `audit_log`, `user_profiles`, `organization_memberships` che hanno RLS). Scelta accettata e coerente col resto del progetto.

---

## 1. Schema DB — Migrazione `007_booking_standalone.sql`

### 1.1 Nuove colonne su `bookings`

```sql
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS tipo_evento            TEXT NOT NULL DEFAULT '';
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS richiede_deposito      BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_link           TEXT NOT NULL DEFAULT '';
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_link_created_at TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS payment_status         TEXT NOT NULL DEFAULT 'none'
    CHECK (payment_status IN ('none','pending','paid','refunded','expired'));
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_sent_at       TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_status        TEXT NOT NULL DEFAULT 'none'
    CHECK (reminder_status IN ('none','sent','confirmed','rejected','cancelled','flagged'));
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reminder_responded_at  TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS completata_at          TIMESTAMPTZ;
ALTER TABLE bookings ADD COLUMN IF NOT EXISTS no_show_at             TIMESTAMPTZ;
```

### 1.2 Stati `bookings.stato` estesi

```sql
ALTER TABLE bookings DROP CONSTRAINT IF EXISTS bookings_stato_check;
ALTER TABLE bookings ADD CONSTRAINT bookings_stato_check
    CHECK (stato IN ('in_attesa','confermata','rifiutata','cancellata','no_show','completata','da_verificare'));
```

- `in_attesa` — in attesa di conferma staff
- `confermata` — confermata dallo staff
- `rifiutata` — rifiutata dallo staff (libera il posto)
- `cancellata` — cancellata da staff/cliente (libera il posto)
- `no_show` — cliente non presentato (libera il posto)
- `completata` — cliente arrivato e servito (occupa il posto nel conteggio)
- `da_verificare` — da verificare a fine giornata (occupa il posto)

**Nota:** `completata` non libera capacità perché il cliente ha effettivamente occupato il tavolo. Per il calcolo di `verifica_disponibilita` su slot futuri questo non è rilevante (una prenotazione passata non confligge con una futura), ma è annotato per evitare bug in future funzioni di reportistica storica.

### 1.3 Nuova colonna `config` su `booking_settings`

```sql
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}';
```

Struttura del JSONB:

```json
{
  "deposito": {
    "enabled": false,
    "importo_default": 10.00,
    "valuta": "EUR",
    "criteri": {
      "coperti_min": null,
      "tipi_evento": [],
      "fasce": [],
      "date": []
    }
  },
  "reminder": {
    "anticipo_ore": 24,
    "timeout_ore": 12,
    "lead_time_minimo_ore": 24
  }
}
```

**Semantica criteri deposito:** valore `null` o array `[]` = criterio disattivato.
- `coperti_min: null` → la soglia coperti non viene valutata
- `tipi_evento: []` → nessun tipo evento attiva il deposito tramite questo criterio
- `fasce: []` → nessuna fascia oraria attiva
- `date: []` → nessuna data specifica attiva
- I criteri sono in OR: se UNO matcha, il booking richiede deposito

---

## 2. Booking Service — `src/core/bookings/service.py`

### 2.1 Struttura

Nuovo pacchetto `src/core/bookings/` con:
- `__init__.py`
- `service.py` — logica di business
- `routes.py` — FastAPI routes
- `reminder_job.py` — cron reminder + timeout
- `no_show_job.py` — cron fine-giornata

### 2.2 BookingService

```python
class BookingService:
    def __init__(self, core_repo: CoreRepository, whatsapp_service: WhatsAppService, app_config: AppConfig):
        self.repo = core_repo
        self.whatsapp = whatsapp_service
        self.app_config = app_config

    async def create_booking(self, org_id, input_data) -> Booking
        # 1. verifica disponibilità (migrato da prenotazioni.py, usa repo.list_bookings)
        # 2. se inventario ok → repo.create_booking()
        #    stati esclusi dal conteggio coperti: 'cancellata','cancellato','rifiutata','no_show'
        #    (include 'cancellato' maschile per backward compat Airtable)
        # 3. se lead_time < 24h → skip reminder (data già domani, reminder inutile)
        #    MA resta in_attesa come sempre — nessuna auto-conferma
        # 4. se deposito.enabled → valuta criteri → richiede_deposito
        # 5. notifica WhatsApp al cliente ("Richiesta pervenuta, ti aggiorniamo a breve")

    async def confirm(self, org_id, booking_id) -> Booking
        # staff conferma → stato = 'confermata'
        # se richiede_deposito → genera Stripe Payment Link, payment_status = 'pending'
        # notifica WhatsApp: conferma + eventuale link deposito

    async def reject(self, org_id, booking_id, motivo) -> Booking
        # staff rifiuta → stato = 'rifiutata'
        # notifica WhatsApp: "purtroppo non possiamo confermare" + motivo

    async def cancel(self, org_id, booking_id) -> Booking
        # staff/cliente → stato = 'cancellata'

    async def mark_no_show(self, org_id, booking_id) -> Booking
        # staff → stato = 'no_show', no_show_at = NOW()

    async def mark_completed(self, org_id, booking_id) -> Booking
        # staff → stato = 'completata', completata_at = NOW()

    async def verifica_disponibilita(self, org_id, data, ora, coperti=None) -> DisponibilitaSlot
        # migrato da prenotazioni.py, parametrizzato per org
        # capienze_orarie da repo.get_booking_settings(org_id)
        # prenotazioni attive da repo.list_bookings(org_id, data)

    async def semaforo_giorno(self, org_id, data) -> list[DisponibilitaSlot]
    async def prossimi_giorni_semaforo(self, org_id, giorni) -> list[DisponibilitaSlot]

    async def handle_reminder_reply(self, org_id, from_number, text) -> str | None
        # hook chiamato da inbound_processor prima dell'AI generica
        # 1. cerca booking con reminder_status='sent' per contatto+org
        # 2. classifica risposta: keyword match rapido (sì/confermo → confirmed; no/annulla → rejected)
        #    se ambiguo → classifica con AI prompt minimo
        # 3. confirmed → reminder_status='confirmed', WhatsApp "Grazie, confermata!"
        # 4. rejected/cancelled → reminder_status='rejected', stato='cancellata', WhatsApp cancellata
        # 5. ambiguo → reminder_status='flagged' (entra in HITL)
        # 6. NON passa mai all'AI generica
```

### 2.3 Capacity filter — stati che occupano/liberano lo slot

```python
STATI_OCCUPATI = {'in_attesa', 'confermata', 'da_verificare', 'completata'}
STATI_LIBERI = {'cancellata', 'cancellato', 'rifiutata', 'no_show'}
```

Il filtro include sia `cancellata` (femminile, ortografia nuovo schema) che `cancellato` (maschile, ortografia vecchi dati Airtable). Al prossimo giro di pulizia dati si può normalizzare.

### 2.4 Caricamento tenant_config per WhatsApp

```python
# loading dell'app_config (globale esistente)
app_config = _get_app_config()
# loading del tenant config per org (stesso pattern di inbound_processor.py)
from src.whatsapp.config import load_tenant_config
tenant_config = load_tenant_config(org_id, app_config, wrepo)
```

### 2.5 Dipendenze socket

- `CoreRepository(pool)` — booking CRUD + settings
- `WhatsAppRepository(pool)` — operazioni WhatsApp (send, status tracking)
- `WhatsAppService(app_config, WhatsAppRepository)` — invio messaggi
- `AppConfig` — config globale

I costruttori ricevono **sempre** repository già istanziati, mai pool grezzo. I job scheduler costruiscono tutti i repository necessari esplicitamente.

---

## 3. API Routes + Hook Reminder + Scheduler

### 3.1 Hook risposta reminder in `inbound_processor.py`

Prima dell'AI generica, dopo l'opt-out check:

```python
# 1. Opt-out check (GDPR) — sempre primo, vince su tutto
if await whatsapp_service.check_opt_out(text):
    return handle_opt_out(...)

# 2. Reminder reply hook
reminder_reply = await booking_service.handle_reminder_reply(org_id, from_number, text)
if reminder_reply:
    return reminder_reply  # già inviato, non passare all'AI

# 3. AI responder generico
response = await responder_agent.generate(org_id, text, ...)
```

L'opt-out vince sempre, prima di ogni altra logica — obbligo GDPR.

### 3.2 Route API — `src/core/bookings/routes.py`

Ordine di registrazione (critico in FastAPI: route statiche prima di `{id}`):

```python
# Route statiche
GET    /api/bookings/semaforo              → owner/manager/staff
GET    /api/bookings/settings              → owner/manager
PUT    /api/bookings/settings              → owner/manager
GET    /api/bookings                        → owner/manager/staff

# Route parametrizzate
POST   /api/bookings                        → owner/manager

# Route con {id} — DOPO le statiche
GET    /api/bookings/{id}                   → owner/manager/staff
POST   /api/bookings/{id}/confirm           → owner/manager
POST   /api/bookings/{id}/reject            → owner/manager
POST   /api/bookings/{id}/cancel            → owner/manager
POST   /api/bookings/{id}/mark-no-show      → owner/manager
POST   /api/bookings/{id}/mark-completed    → owner/manager
```

Tutte richiedono autenticazione. `POST reject` accetta `{"motivo": "..."}` (opzionale).

### 3.3 Scheduler — job per-org con loop esplicito

Tre nuovi job in `avvia_scheduler()`:

```python
async def _run_reminder_check():
    pool = _pool()
    app_config = _get_app_config()
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        wrepo = WhatsAppRepository(pool)
        core_repo = CoreRepository(pool)
        whatsapp = WhatsAppService(app_config, wrepo)
        service = BookingService(core_repo, whatsapp, app_config)
        await service.send_reminders(org["id"])

async def _run_reminder_timeout():
    pool = _pool()
    app_config = _get_app_config()
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        wrepo = WhatsAppRepository(pool)
        core_repo = CoreRepository(pool)
        whatsapp = WhatsAppService(app_config, wrepo)
        service = BookingService(core_repo, whatsapp, app_config)
        await service.check_reminder_timeouts(org["id"])

async def _run_no_show_check():
    pool = _pool()
    app_config = _get_app_config()
    orgs = await pool.fetch("""
        SELECT id FROM organizations
        WHERE subscription_status NOT IN ('canceled', 'incomplete', 'past_due')
    """)
    for org in orgs:
        wrepo = WhatsAppRepository(pool)
        core_repo = CoreRepository(pool)
        whatsapp = WhatsAppService(app_config, wrepo)
        service = BookingService(core_repo, whatsapp, app_config)
        await service.mark_da_verificare(org["id"])
```

Registrazione cron:

```python
scheduler.add_job(_run_reminder_check, CronTrigger(minute="*/30"), id="booking_reminder")
scheduler.add_job(_run_reminder_timeout, CronTrigger(minute="*/30"), id="booking_reminder_timeout")
scheduler.add_job(_run_no_show_check, CronTrigger(hour=23, minute=30), id="booking_no_show")
```

### 3.4 Comportamento reminder

1. **send_reminders(org_id):** booking con `data = domani`, `stato = confermata`, `reminder_status = none`, lead_time >= 24h → invia WhatsApp, setta `reminder_status = sent`, `reminder_sent_at = NOW()`
2. **check_reminder_timeouts(org_id):** booking con `reminder_status = sent` e `reminder_sent_at + 12h < NOW()` e `data >= oggi`:
   - Se cliente ha risposto (reminder_status già cambiato da `handle_reminder_reply`) → nulla
   - Se nessuna risposta → `reminder_status = flagged` (entra in HITL inbox)
3. No-show a fine giornata: `data = oggi`, `stato = confermata`, `completata_at IS NULL`, `no_show_at IS NULL` → `stato = da_verificare`

---

## 4. Deposito/Cauzione — Stripe Payment Links

### 4.1 Flusso

1. **Configurazione**: `booking_settings.config.deposito` (toggle + criteri)
2. **Creazione booking**: se `enabled` e criteri matchano → `richiede_deposito = True`
3. **Conferma staff**: se `richiede_deposito`:
   - `stripe.PaymentLink.create()` con `line_items[{price_data{unit_amount: importo_default*100, currency: valuta}, quantity: 1}]`, `metadata = {booking_id, organization_id}`, `after_completion.type = redirect` alla dashboard
   - Salva `payment_link = link.url`, `payment_link_created_at = NOW()`, `payment_status = 'pending'`
   - WhatsApp: "Deposito di €X: <link>"
4. **Pagamento**: webhook Stripe `checkout.session.completed` con `mode = payment` → lookup `metadata.booking_id` → `payment_status = 'paid'`
5. **Scadenza**: cron 24h dopo `payment_link_created_at` se `payment_status = 'pending'` → `payment_status = 'expired'`, flagga per staff (rimane confermata ma con badge visibile)

### 4.2 Webhook Stripe — modifica a `billing/webhook_handler.py`

Il ramo `checkout.session.completed` viene instradato per mode:

```python
if data.get("mode") == "subscription":
    # logica billing esistente (subscription_id, org lookup, plan upgrade)
    ...
elif data.get("mode") == "payment":
    # logica deposito booking
    metadata = data.get("metadata", {}) or {}
    booking_id = metadata.get("booking_id")
    org_id = metadata.get("organization_id")
    if booking_id and org_id:
        await core_repo.update_booking_payment(org_id, booking_id, "paid", session_id)
```

Non c'è più `return None` per `mode = "payment"` — viene gestito esplicitamente.

### 4.3 Metodo CoreRepository

```python
async def update_booking_payment(self, organization_id, booking_id, payment_status, session_id=None):
    # UPDATE bookings SET payment_status = $3, ... WHERE organization_id = $1 AND id = $2
```

### 4.4 Vincoli

- Il deposito NON blocca la conferma — `confirm` e pagamento sono indipendenti
- Se `expired`, lo staff decide se onorare comunque la prenotazione
- Stripe `payment_intent` non viene creato direttamente (uso `PaymentLink` che gestisce tutto da solo)

---

## 5. Test (TDD)

Tutti i test usano PostgreSQL di test con schema applicato (stessa fixture già usata per test_repository_bookings.py).

### Servizio

| Test | Cosa verifica |
|------|--------------|
| `test_create_booking_success` | Crea booking con disponibilità OK |
| `test_create_booking_slot_full` | Rifiuta se slot pieno |
| `test_confirm_sends_whatsapp` | Confirm → WhatsApp inviato (mockato) |
| `test_reject_sends_whatsapp` | Reject → WhatsApp inviato |
| `test_reject_frees_capacity` | Dopo reject, stesso slot torna disponibile |
| `test_mark_no_show` | No-show registrato, coperti liberati |
| `test_mark_completed` | Completata registrata, coperti non liberati |
| `test_cancellata_frees_capacity` | Cancellata libera posto |
| `test_capacity_excludes_cancellata_no_show` | Filtro include entrambe le ortografie |
| `test_reminder_skip_lead_time_short` | Booking creato < 24h prima → skip reminder |
| `test_reminder_skip_keeps_in_attesa` | Lead time corto salta reminder, NON auto-conferma |
| `test_reminder_reply_confirm` | Risposta "sì" → reminder_status = confirmed |
| `test_reminder_reply_reject` | Risposta "no" → reminder_status = rejected, stato = cancellata |
| `test_reminder_reply_ambiguous` | Risposta ambigua → flagged |
| `test_reminder_timeout_no_reply` | Nessuna risposta in 12h → flagged |
| `test_no_show_check_pending` | Fine giornata → booking confermata → da_verificare |

### Deposito

| Test | Cosa verifica |
|------|--------------|
| `test_deposito_enabled_matches_criteri` | Booking matcha criterio → richiede_deposito = True |
| `test_deposito_enabled_no_match` | Booking non matcha → richiede_deposito = False |
| `test_deposito_disabled` | Toggle off → nessun booking marcato |
| `test_deposito_criteri_coperti_min` | Soglia coperti: >= N matcha, < N no |
| `test_deposito_criteri_tipi_evento` | Tipo evento in whitelist matcha |
| `test_deposito_criteri_null_disabled` | coperti_min: null → criterio ignorato |
| `test_deposito_criteri_empty_list_disabled` | tipi_evento: [] → criterio ignorato |
| `test_deposito_genera_payment_link` | Confirm con richiede_deposito → Stripe API chiamata |
| `test_deposito_genera_senza_link` | Confirm senza richiede_deposito → niente Stripe |
| `test_deposito_webhook_payment` | Webhook mode=payment → payment_status = paid |
| `test_deposito_expired` | 24h dopo creazione link pending → expired |

### Multi-tenancy

| Test | Cosa verifica |
|------|--------------|
| `test_cross_tenant_isolation` | Org A non vede booking di Org B |
| `test_cross_tenant_settings` | Org A modifica settings → Org B non influenzato |
| `test_capacity_per_org` | Ogni org ha la propria capacità indipendente |

### API

| Test | Cosa verifica |
|------|--------------|
| `test_route_static_before_id` | GET /semaforo non matcha {id} |
| `test_route_confirm_unauthorized` | Staff non può confermare |
| `test_route_settings_owner_only` | Owner può modificare settings |
| `test_route_list_staff_readonly` | Staff può solo leggere lista |

---

## 6. Piano di implementazione

### Step 1: DB migration
- Creare `src/core/db/migrations/007_booking_standalone.sql` con ALTER TABLE
- Eseguire su DB di test

### Step 2: Estendere CoreRepository
- `update_booking_payment()`, `list_bookings_by_status()`, `list_bookings_for_reminder()`

### Step 3: Creare booking service
- `src/core/bookings/service.py` — logica completa
- Riscrivere `prenotazioni.py` come thin adapter che chiama BookingService, poi rimuovere

### Step 4: API routes
- `src/core/bookings/routes.py` — montare su app
- Test di integrazione

### Step 5: Hook reminder in inbound_processor
- Chiamata a `booking_service.handle_reminder_reply()` dopo opt-out check

### Step 6: Job scheduler
- `reminder_job.py`, `no_show_job.py`
- Registrazione in `scheduler.py`

### Step 7: Deposito Stripe
- Modifica `webhook_handler.py` per mode = payment
- `BookingService._genera_payment_link()`

### Step 8: Pulizia
- Rimuovere variabili globali da `prenotazioni.py`
- Rimuovere dipendenza `airtable_client.py` dal flusso booking (se non già fatto)
- Verificare che nessun import rotto punti al vecchio modulo
