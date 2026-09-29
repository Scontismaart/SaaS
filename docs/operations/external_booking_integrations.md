# Runbook Operativo: Integrazione Sistemi di Prenotazione Esterni (PMS)

## 1. Architettura e Principi Guida

Melpis adotta un'architettura a **Porte e Adattatori (Hexagonal Architecture)** per dialogare con i gestionali di prenotazione esterni (es. SimplyBook.me per centri estetici/parrucchieri, WuBook ZaK per hotel/ospitalità).

```
Incoming WhatsApp Message
         ↓
ConversationOrchestrator
         ↓
  BookingService (Domain Logic)
         ↓
BookingAdapterRouter (Minimization + Send-Then-Mark)
          ├──> SimplyBookAdapter (Beauty/Wellness - Production Adapter)
          ├──> ApaleoAdapter (Hospitality / Hotel PMS - Production Adapter Raccomandato)
          ├──> Beds24Adapter (Hospitality / PMS & Channel Manager - In attesa di Verifica Live)
          ├──> CalComAdapter (1:1 Appointments / Fallback Universale - Production Adapter)
          ├──> ZakAdapter (Hospitality - Alternativa Secondaria Gated)
          └──> InternalBookingAdapter (PostgreSQL Locale)
```

### Tutte le 11 Invarianti Non Negoziabili
1. **Isolamento Multi-Tenant (Invariante 1)**: Le credenziali sono isolate per organizzazione e cifrate at-rest con Fernet envelope. Le query passano attraverso il repository verificato dal gate AST di CI.
2. **Data Scope Rigoroso (Invariante 2)**: Le tabelle `external_booking_credentials` e `external_booking_sync` appartengono a `TENANT_SCOPED_TABLES` con vincolo di foreign key su `organization_id`.
3. **Latenza Webhook (Invariante 3)**: L'acknowledge HTTP 200 a Meta avviene immediatamente (<500ms); la sincronizzazione con il PMS esterno è gestita in background via worker asincrono.
4. **Idempotenza a Monte (Invariante 4)**: Nessuna mutazione esterna avviene senza previa persistenza di un record `pending` in `external_booking_sync` con chiave `ext-book:{org_id}:{source_message_id}`. Replay automatico dei record `synced` e blocco delle chiamate concorrenti.
5. **Nessuna Azione AI Privilegiata (Invariante 5)**: L'LLM genera esclusivamente DTO non autoritativi; `BookingService` e `BookingAdapterRouter` validano deterministicamente ogni parametro prima di invocare le API esterne.
6. **GDPR & Fail-Closed Minimization (Invariante 6)**: Se il settore è `studio_medico` (o il verticale è sconosciuto/None per fallback di sicurezza), le note utente vengono sbiancate prima della trasmissione a meno che `medical_dpa_signed is True` (booleano stretto).
7. **Guardrail Pipeline (Invariante 7)**: Ogni messaggio generato per il cliente WhatsApp (conferme, alternative, fallback) attraversa la pipeline dei guardrail di conformità.
8. **Billing & Cost Governance (Invariante 8)**: Token accounting per-organizzazione e Circuit Breaker (5 errori consecutivi $\to$ apertura 60s) per prevenire consumo di quote e blocchi a valanga.
9. **Osservabilità (Invariante 9)**: Tracciamento end-to-end con `org_id`, `conversation_id`, `message_id`, `idempotency_key` e payload sanificato (nessun dato clinico o credenziale loggato in chiaro).
10. **Sicurezza Segreti (Invariante 10)**: Token di sessione e API keys cifrati at-rest; mai esposti al client o inviati a frontend.
11. **Escalation Umana Obbligatoria (Invariante 11)**: In modalità `authoritative`, se il gestionale fallisce o il circuit breaker è aperto, il sistema **NON** effettua fallback silenzioso su disponibilità locali fittizie: imposta `richiede_intervento=True` e allerta la Shared Inbox operatore.

---

## 2. Modalità Operative (`BookingMode`)

Ogni organizzazione può operare in una delle seguenti modalità specificate nel JSON `config`:

| Modalità | Comportamento | Fallback / Errore |
| :--- | :--- | :--- |
| `authoritative` | Il gestionale esterno fa fede assoluta per disponibilità e prenotazioni. | Nessun fallback locale. Errore $\to$ Human Escalation immediata (`richiede_intervento=True`). |
| `shadow` | La prenotazione viene salvata primariamente sul DB Melpis locale; la chiamata al PMS avviene asincronamente per audit e monitoraggio. | Gli errori dell'adapter esterno vengono loggati e marcati come `failed` in sync, ma l'utente WhatsApp riceve conferma locale. |
| `mirror` | Riservata alla sincronizzazione bidirezionale continua con webhook in ingresso dal PMS. | Attualmente intercettata dal router con fallback di sicurezza ad `authoritative` e warning log. |
| `local_only` | Nessun provider esterno attivo o configurato. | Tutte le transazioni avvengono esclusivamente sul database PostgreSQL di Melpis. |

---

## 3. Configurazione Tenant & Credenziali

Le credenziali per i gestionali esterni vengono salvate cifrate nella tabella `external_booking_credentials` tramite `ExternalBookingRepository`.

### A. SimplyBook.me (Beauty / Servizi) — *Adapter di Produzione*
SimplyBook utilizza autenticazione JSON-RPC 2.0 tramite token di sessione generato con API Key e Company Login.

```json
{
  "provider": "simplybook",
  "is_active": true,
  "company_login": "<YOUR_SIMPLYBOOK_COMPANY_LOGIN>",
  "api_key": "<YOUR_SIMPLYBOOK_API_KEY>",
  "config": {
    "mode": "authoritative",
    "timeout_seconds": 4.0,
    "circuit_breaker_threshold": 5,
    "circuit_breaker_reset_seconds": 60.0
  }
}
```

> **Nota Architetturale su SimplyBook**: L'API JSON-RPC 2.0 di SimplyBook non supporta un header `Idempotency-Key` nativo. L'idempotenza poggia interamente sul meccanismo DB locale Send-Then-Mark (`external_booking_sync`).

### B. WuBook ZaK (Hotel / Ospitalità) — *Adapter Hardened KAPI (Gated / In attesa di Sandbox Live)*
WuBook ZaK opera tramite l'API gateway proprietaria KAPI (`https://kapi.wubook.net/kapi`) con chiamate RPC interamente in HTTP POST e autenticazione tramite header `x-api-key`.

> **Governance e Stato di Produzione (Relegato ad Alternativa Secondaria)**: 
> `ZakAdapter` è conforme alle specifiche KAPI reali di WuBook, tuttavia:
> 1. Con la disponibilità e la verifica live sul campo di `ApaleoAdapter`, **Apaleo è ora la soluzione primaria e raccomandata per l'hospitality (Hotel/B&B/Strutture Ricettive)** grazie all'onboarding self-service, al modello Cloud moderno e all'idempotenza nativa.
> 2. **WuBook ZaK viene relegato ad alternativa secondaria/futura**: verrà attivato esclusivamente se un cliente lo richiede esplicitamente ed è già provvisto di contratto commerciale attivo con WuBook per il modulo *ZaK API*.
> 3. Il divieto di attivazione immediata in produzione (modalità `authoritative` e `mirror`) rimane attivo fino a esecuzione del test live contro un account cliente reale contrattualizzato.

```json
{
  "provider": "zak",
  "is_active": true,
  "property_id": "hotel_bellavista_roma",
  "api_key": "zak_live_token_778899aabbcc",
  "config": {
    "mode": "shadow",
    "base_url": "https://kapi.wubook.net/kapi",
    "timeout_seconds": 5.0
  }
}
```

#### Gestione Soggiorni Multi-Notte e Cambio Ora Legale (DST)
A differenza degli appuntamenti singoli (taglio capelli, tavolo ristorante), un soggiorno alberghiero è un intervallo di date. 
- Il modello canonico [`CreateBookingRequest`](file:///C:/Users/muzzo/Desktop/whatsapp-ai-responder/src/core/bookings/ports/base.py#L103) include il campo esplicito `data_fine: date | None = None`.
- `ZakAdapter` calcola la data di check-out dando priorità a `data_fine` esplicita e determina le notti di soggiorno tramite differenza di calendario: `nights = (checkout_date - checkin_date).days`.
- Questo calcolo di calendario è **completamente immune alle anomalie di cambio ora legale (DST)** (giornate di 23 o 25 ore reali a fine marzo o fine ottobre), evitando gli errori dovuti all'aritmetica fittizia sui minuti (`durata_minuti = 1440 * notti`).

### C. Cal.com (Appuntamenti 1:1, Consulenze, Fallback Universale) — *Adapter di Produzione*

Cal.com opera tramite la moderna API REST v2 (`https://api.cal.com/v2`) con autenticazione Bearer token basata su API Key (`cal_live_...`) ed enforcement dell'header di versione `cal-api-version: 2024-08-13`.

#### 1. Razionale Strategico e Verticali di Destinazione
A differenza dei verticali altamente specializzati (es. WuBook per hospitality multi-notte o SimplyBook per beauty multi-staff con cabine):
- **Ruolo Primario**: Gestione di appuntamenti 1:1 con slot discreti (es. 15, 30, 60 minuti), consulenze professionali, liberi professionisti (avvocati, commercialisti, consulenti, personal trainer) e prime visite ambulatoriali.
- **Ruolo di Fallback Universale Self-Service**: Di fronte alla chiusura o alle barriere commerciali dei gestionali verticali tradizionali (dove l'accesso API richiede lunghi iter di partnership B2B o fee di migliaia di euro), Cal.com fornisce a qualunque tenant una **via d'uscita self-service immediata**: il cliente apre un account Cal.com in 2 minuti, genera un'API key, crea uno o più Event Types e attiva Melpis all'istante in modalità `authoritative`.
- **Differenziazione rispetto a SimplyBook**:
  - `SimplyBook`: raccomandato per saloni e spa con cataloghi estesi di trattamenti, assegnazione operatore specifica per servizio, listini differenziati e sale dedicate.
  - `Cal.com`: raccomandato per professionisti individuali, team flessibili, consulenze e come alternativa snella quando SimplyBook non è desiderato dal tenant.

> [!WARNING]
> **REGOLA OPERATIVA DI CONFIGURAZIONE: VINCOLO A CAPACITÀ SINGOLA**
> Cal.com come fallback universale è raccomandato e garantito **esclusivamente per risorse a capacità singola (1:1)** (un professionista, uno slot orario, un cliente per volta).
> **NON utilizzare Cal.com per risorse multi-capacità o prenotazioni parallele** (es. tavoli ristorante con più coperti, saloni con più poltrone simultanee sullo stesso slot, classi o corsi di gruppo). Poiché Cal.com API v2 non supporta l'idempotenza nativa lato server su slot condivisi a capienza multipla, un retry dovuto a disconnessione di rete potrebbe generare prenotazioni duplicate per lo stesso orario. Per scenari multi-capacità utilizzare i gestionali verticali dedicati (SimplyBook per beauty, ZaK per hotel) o l'adapter locale interno Melpis.

#### 2. Idempotenza (Invariante 4)
- **Assenza di Idempotenza Nativa nel Provider**: L'API v2 di Cal.com (`POST /v2/bookings`) **non supporta** header HTTP di idempotenza (`Idempotency-Key`). Due chiamate identiche su uno slot non esclusivo genererebbero due prenotazioni distinte su Cal.com.
- **Presidio Locale Send-Then-Mark**: La garanzia di idempotenza ricade **interamente sul pattern locale Send-Then-Mark** del `BookingAdapterRouter` (`external_booking_sync`). Se una richiesta di creazione viene ritentata a seguito di instabilità di rete, il router rileva lo stato `synced` e restituisce immediatamente la prenotazione memorizzata senza contattare Cal.com.
- **Tracciabilità Esterna**: Per favorire audit e riconciliazione su Cal.com, l'adapter inietta `idempotency_key`, `source_message_id` e `internal_booking_id` all'interno dell'oggetto `metadata` di Cal.com.

#### 3. Data Minimization GDPR e Dati Sensibili (Invariante 6)
- La protezione dei dati particolari (art. 9 GDPR) è **completamente centralizzata nel `BookingAdapterRouter`**.
- Se un tenant configura Cal.com per il settore sanitario (`studio_medico`, `clinica`, `fisioterapia`, ecc.), la `DataMinimizationPolicy` intercetta la richiesta prima della chiamata HTTP: se `medical_dpa_signed` non è esplicitamente `True`, il campo `note` viene azzerato a monte e non viene trasmesso a Cal.com (il body JSON omette il campo `notes`).

#### 4. Barriera Data Quality per Fallback Email (RFC 2606)
- **Vincolo Cal.com v2**: Cal.com richiede tassativamente un'email valida per l'attendee (`attendee.email: required string`); l'omissione provoca HTTP 422.
- **Soluzione Sicura RFC 2606**: In assenza di email dall'utente WhatsApp, l'adapter sintetizza deterministicamente `wa_{clean_phone_digits}@{placeholder_domain}` (default: `noemail.invalid`, TLD riservato RFC 2606 garantito a livello DNS per non instradare mai pacchetti SMTP).
- **Barriera a Valle in Lettura**: In conformità all'art. 5.1(d) GDPR (esattezza dei dati), `CalComAdapter.get_customer` rileva tramite `is_synthetic_email` se l'indirizzo memorizzato su Cal.com è un placeholder e restituisce rigorosamente `CustomerResult.email = None`, impedendo che downstream (CRM, mailing, notifiche esterne) ricevano un'identità fittizia.

#### 5. Modello di Accesso API, Piani e Costi
- **API Key Self-Service**: L'amministratore del tenant genera la chiave in autonomia dal dashboard Cal.com (*Settings > Security > API Keys*). I secret live hanno prefisso `cal_live_`.
- **Rate Limits Standard**: Cal.com impone per impostazione predefinita **120 richieste al minuto** per API Key (adeguato a gestire oltre 7.000 interazioni/ora per singolo tenant).
- **Governance Multi-Tenant e Trade-Off Onboarding (BYOK - Bring Your Own Key)**: 
  - Cal.com offre piani individuali/team e istanze enterprise. Dal 15 dicembre 2025 Cal.com ha sospeso le nuove sottoscrizioni all'offerta "Platform" (managed users OAuth embedded); per questo motivo Melpis **non offre l'attivazione centralizzata con 1-click trasparente** per Cal.com.
  - Ogni cliente Melpis opera in modalità **BYOK**: crea autonomamente il proprio account Cal.com, configura i propri Event Types e genera la propria API Key, inserendola nel pannello di onboarding di Melpis. Questo passaggio deve essere esplicitato chiaramente nella comunicazione cliente per evitare fraintendimenti sull'onboarding.
  - **Opzione Self-Hosting**: Poiché il core di Cal.com è open source, un tenant o il provider SaaS possono eseguire un'istanza self-hosted di Cal.com configurando il parametro `base_url` (es. `https://cal.mio-dominio.it/v2`), azzerando qualsiasi costo di licenza cloud o dipendenza di terze parti.

```json
{
  "provider": "calcom",
  "is_active": true,
  "api_key": "<YOUR_CALCOM_API_KEY>",
  "config": {
    "mode": "authoritative",
    "base_url": "https://api.cal.com/v2",
    "event_type_id": "123456",
    "timezone": "Europe/Rome",
    "placeholder_email_domain": "noemail.invalid",
    "medical_dpa_signed": false,
    "timeout_seconds": 5.0,
    "circuit_breaker_threshold": 5,
    "circuit_breaker_reset_seconds": 60.0
  }
}
```

### D. Apaleo PMS (Hotel / Hospitality) — *Production Adapter Raccomandato*

Apaleo è il Cloud Hospitality PMS europeo leader per architettura API-first aperta e moderna. Opera tramite REST API su HTTPS (`https://api.apaleo.com`) con Identity server OAuth 2.0 (`https://identity.apaleo.com`).

#### 1. Razionale Strategico: Perché Apaleo è la Scelta Primaria per Hospitality
A differenza dei PMS tradizionali con barriere commerciali B2B (come WuBook ZaK o Octorate):
- **Accesso e Onboarding Self-Service**: Il cliente o sviluppatore può creare un'applicazione personalizzata (*Simple Client*) in autonomia senza passare da contratti manuali o approvazioni discrezionali.
- **Supporto Nativo Multi-Notte**: Gestione completa di soggiorni di calendario (`arrival`, `departure`, `num_nights`), tariffe lorde dinamiche (`totalGrossAmount`), tipologie di camera (`Unit Groups`), occupancy (`adults`, `childrenAges`) e ripartizione giornaliera (`timeSlices`).
- **Idempotenza Nativa (Invariante 4)**: Apaleo supporta l'header HTTP `Idempotency-Key` su creazione (`POST /booking/v1/bookings`) e modifica (`PUT /booking/v1/reservation-actions/{id}/amend`), garantendo persistenza e deduplica lato server per 24 ore. In combinazione con il pattern locale `external_booking_sync` (Send-Then-Mark), il rischio di overbooking o prenotazioni duplicate per retry di rete è pari a zero.

#### 2. Autenticazione OAuth 2.0 Coroutine-Safe
Implementata in `ApaleoOAuthClient` con:
- Supporto a **Client Credentials M2M** (flusso standard raccomandato per singoli hotel/client privati).
- Supporto ad **Authorization Code / Refresh Token** con rotazione automatica del refresh token e persistenza DB at-rest.
- **Double-Checked Locking** con `asyncio.Lock()`: garantisce che chiamate concorrenti non scatenino "token storms", eseguendo esattamente 1 richiesta HTTP di refresh.
- **Buffer Clock Skew**: margine di sicurezza preventivo di 60 secondi prima della scadenza effettiva del token.

#### 3. Rilevamento Dinamico PII e Resilienza Privacy
- **Configurazione PII in Apaleo**: L'account dell'hotel può impostare la visibilità PII su `Retrieve` (dati in chiaro) o `Omit linked` (dati mascherati con asterischi `***`).
- **Resilienza Runtime Dinamica**: `ApaleoAdapter.get_customer` non assume mai una modalità fissa, ma analizza ciascun campo della risposta: se un valore è mascherato (es. `"***"`), viene automaticamente sanificato ad stringa vuota o `None`, prevenendo che il bot WhatsApp si rivolga al cliente come "Signor ***".
- **Fallback Cortese nel Dominio**: Il DTO canonico `CustomerResult` espone la proprietà `.display_name`, che in assenza di nome anagrafico ricorre deterministicamente all'appellativo sicuro *"Gentile ospite"*.

#### 4. Auto-Discovery Struttura & Configurazione JSON
Se `property_id` non è specificato nel config del tenant, l'adapter effettua l'auto-discovery dinamico via `GET /inventory/v1/properties`.

```json
{
  "provider": "apaleo",
  "is_active": true,
  "client_id": "<YOUR_APALEO_CLIENT_ID>",
  "client_secret": "<YOUR_APALEO_CLIENT_SECRET>",
  "property_id": "<YOUR_APALEO_PROPERTY_ID>",
  "config": {
    "mode": "authoritative",
    "base_url": "https://api.apaleo.com",
    "channel_code": "Direct",
    "timezone": "Europe/Berlin",
    "timeout_seconds": 8.0,
    "circuit_breaker_threshold": 5,
    "circuit_breaker_reset_seconds": 60.0
  }
}
```

### E. Beds24 PMS & Channel Manager (Hotel / Hospitality) — *Implementazione Completa, Verifica Live in Sospeso (In attesa di registrazione trial / credenziali)*

Beds24 è un PMS e Channel Manager leader a livello globale per strutture alberghiere e property management. L'integrazione è basata nativamente su **Beds24 REST API v2** (`https://api.beds24.com/v2`).

#### 1. Verifica Preliminare di Accesso: Self-Service vs Gated
La verifica sul campo e l'analisi della documentazione ufficiale (`wiki.beds24.com`) rivelano due percorsi di accesso ben distinti:
- **Canale Diretto per Singola Struttura / Hotel (Self-Service)**:
  - Il gestore della struttura (hotel o property manager) accede autonomamente al pannello Beds24 su `(SETTINGS) ACCOUNT > ACCOUNT ACCESS` oppure `(SETTINGS) MARKETPLACE > API`.
  - Clicca su **"Generate invite code"**, seleziona i permessi necessari (`bookings`, `bookings-personal`, `inventory`, `properties`) e genera immediatamente l'**Invite Code**.
  - Non richiede alcuna approvazione discrezionale da parte di Beds24, né contratti di partnership firmati o fee di listing.
  - L'adapter Melpis scambia l'invite code per un `refreshToken` (e relativo access token) invocando l'endpoint `GET /v2/authentication/setup`.
- **Canale Marketplace Partner Pubblico (Gated)**:
  - L'inserimento come partner pubblico ufficiale nel catalogo Marketplace di Beds24 richiede l'invio di una candidatura ("Become a partner"), la stipula di un accordo formale ("signed agreement") e l'apertura di ticket manuali per convertire l'account in "partner account".
- **Ambiente di Test / Valutazione & Stato di Validazione**:
  - Beds24 offre una prova gratuita di 14 giorni ("Free Trial") senza carta di credito su `beds24.com/join.html`, con funzionalità API v2 complete.
  - Per un testing automatizzato continuo e permanente oltre i 14 giorni è necessario mantenere un account attivo (abbonamento standard Beds24 a consumo a partire da ~10€/mese) oppure essere accreditati come Integration Partner.
  - **Stato Operativo**: *Implementazione completa, verifica live in sospeso*. Tutti i contratti e i flussi API v2 sono validati con test unitari e di contratto mockati (30/30 test passati). La verifica live con log di esecuzione reale (come fatto per Apaleo e SimplyBook) è subordinata alla creazione di un account trial o alla fornitura di un `inviteCode` reale.

#### 2. Politica Unificata di Dominio: Validazione Rigorosa del Nome Ospite
In conformità alle regole hospitality e per evitare l'inquinamento del PMS della struttura:
- **Rifiuto Tassativo dei Placeholder Generici**: sia `ApaleoAdapter` che `Beds24Adapter` **bloccano la creazione** se il nome o cognome dell'ospite è assente, mascherato con caratteri PII (`*` o `•`) o composto da valori fittizi come `"Ospite WhatsApp"`, `"Guest"`, `"Unknown"`.
- In tal caso, la richiesta fallisce a monte con `success=False`, `stato="rifiutata"` ed `error_code="missing_guest_name"`, senza effettuare chiamate inutili al provider.
- **Auto-Splitting**: Se l'utente WhatsApp invia un nome completo in una sola stringa (es. `"Mario Rossi"`), entrambi gli adapter dividono automaticamente la stringa in `firstName="Mario"` e `lastName="Rossi"`.

#### 3. Caratteristiche Tecniche di Beds24Adapter
- **Protezione Anti-Overbooking Nativa**: Il payload `POST /bookings` include `actions: {"checkAvailability": true}`, ordinando a Beds24 di rifiutare la transazione se le unità sono esaurite.
- **Idempotenza a Livello Provider**: Il campo `apiReference` viene popolato con la chiave di idempotenza deterministica (`req.idempotency_key`), affiancando il pattern locale Send-Then-Mark (`external_booking_sync`).
- **Token Lifecycle & Coroutine Safety**: Utilizzo di *Double-Checked Locking* su `asyncio.Lock` per prevenire token storms durante il refresh su `GET /v2/authentication/token`.
- **Gestione Rolling Credit Limit**: Rilevamento automatico di HTTP 429 con parsing dell'header proprietario `X-FiveMinCreditLimit-ResetsIn` o `Retry-After`.

```json
{
  "provider": "beds24",
  "is_active": true,
  "property_id": "98765",
  "token": "beds24_access_token_or_empty",
  "refresh_token": "beds24_refresh_token_xyz",
  "config": {
    "mode": "authoritative",
    "base_url": "https://api.beds24.com/v2",
    "timezone": "Europe/Rome",
    "timeout_seconds": 8.0,
    "circuit_breaker_threshold": 5,
    "circuit_breaker_reset_seconds": 60.0
  }
}
```

### F. Endpoint REST Operativi per la Dashboard Tenant
L'interazione da parte delle dashboard o dei sistemi di onboarding dei singoli tenant avviene tramite gli endpoint REST implementati in [`src/api/routes/integrations.py`](file:///C:/Users/muzzo/Desktop/whatsapp-ai-responder/src/api/routes/integrations.py):

1. **`POST /api/v1/integrations/booking`**
   - **Autorizzazione**: `owner`, `manager` (estrazione sicura `organization_id` da contesto JWT, immune a tenant spoofing).
   - **Payload**: `provider` (es. `simplybook`, `zak`), `credentials` (dict con chiavi API), `mode` (`authoritative`, `shadow`, `mirror`, `local_only`), `config` (es. `medical_dpa_signed: bool`).
   - **Enforcement di Governance WuBook ZaK**: Se `provider in ("zak", "wubook", "wubook_zak")`, l'endpoint respinge con HTTP 400 qualsiasi modalità diversa da `shadow` o `local_only`.
   - **Cifratura at-rest**: Le credenziali vengono cifrate lato server con Fernet prima del salvataggio su DB; la risposta HTTP conferma solo i metadati (provider, mode, updated_at) **senza mai restituire le credenziali**.

2. **`GET /api/v1/integrations/booking/status`**
   - **Autorizzazione**: `owner`, `manager`, `staff`.
   - **Output**: `is_configured`, `provider`, `mode`, `is_active`, `medical_dpa_signed`, stato del circuit breaker e dettagli dell'ultimo sync (`status`, `external_booking_id`, `retry_count`, `updated_at`).
   - **Zero Secrets Leak**: Nessun token o segreto viene mai esposto, nemmeno mascherato.

3. **`PATCH /api/v1/integrations/booking/mode`**
   - **Autorizzazione**: `owner`, `manager`.
   - **Payload**: `{"mode": "shadow" | "authoritative" | ...}`.
   - **Controllo ZaK**: Stesso vincolo anti-bypass; tentativo di passaggio di ZaK ad authoritative $\to$ HTTP 400.

4. **`DELETE /api/v1/integrations/booking`**
   - **Autorizzazione**: `owner`, `manager`.
   - **Comportamento**: Rimuove la riga da `external_booking_credentials` disattivando immediatamente l'integrazione e riportando il tenant a `local_only`.

---

## 4. Circuit Breaker e Fast-Fail

Per evitare che problemi di rete o downtime del gestionale blocchino il flusso WhatsApp (rispettando il limite di risposta dei webhook Meta):

1. **Soglia di Intervento**: 5 fallimenti consecutivi (timeout di rete, errori 5xx o 429 persistenti).
2. **Stato Aperto**: Quando la soglia è raggiunta, l'adapter entra in stato `OPEN` per 60 secondi.
3. **Fast-Fail Istantaneo (0ms)**: Qualsiasi successiva richiesta viene immediatamente interrotta sollevando `CircuitOpenError` senza attendere i 4 secondi di timeout HTTP.
4. **Comportamento nel Servizio**: Il `BookingService` intercetta l'eccezione, registra il log strutturato e restituisce `richiede_intervento=True`, instradando la conversazione WhatsApp su risposta di cortesia con notifica all'operatore umano:
   > *"Gentile cliente, al momento il nostro sistema di prenotazione è momentaneamente occupato. Ho inoltrato la sua richiesta a un nostro responsabile che le risponderà a breve."*

---

## 5. GDPR e Data Minimization (Sanitizzazione Clinica)

L'invariante 6 stabilisce che i dati personali particolari (art. 9 GDPR - sanitari, sintomi, referti) non debbano mai raggiungere server terzi senza un Data Processing Agreement (DPA) validato.

### Regola Fail-Closed
La classe `DataMinimizationPolicy` in `src/core/bookings/router.py` applica la seguente matrice:

- **Verticale `studio_medico`** e `medical_dpa_signed is False`: campo `note` sbiancato (`""`).
- **Verticale sconosciuto (`None` o vuoto)**: trattato in modalità fail-closed come potenzialmente sensibile $\to$ campo `note` sbiancato se `medical_dpa_signed` non è `True`.
- **Parametro `medical_dpa_signed`**: richiede strettamente `is True` (valori come `None`, `"false"`, `0`, `[]` vengono respinti e trattati come False).
- **Settori commerciali (ristorante, parrucchiere, hotel)**: note conservate (es. intolleranze alimentari, preferenze tavolo o camera).

---

## 6. Troubleshooting e Risoluzione Problemi

### A. Monitoraggio Prenotazioni non Sincronizzate
Per visualizzare le transazioni fallite o in attesa di riconciliazione:

```sql
SELECT 
    id, 
    organization_id, 
    idempotency_key, 
    status, 
    error_message, 
    retry_count, 
    created_at, 
    updated_at
FROM external_booking_sync
WHERE status IN ('failed', 'pending_retry')
ORDER BY created_at DESC
LIMIT 50;
```

### B. Gestione degli Allarmi `richiede_intervento = True`
Quando un cliente WhatsApp riceve la notifica di intervento umano:
1. Aprire la **Shared Inbox** operatore di Melpis.
2. Controllare il `trace_id` o `message_id` nei log applicativi.
3. Se l'errore è dovuto a credenziali PMS errate (`SimplyBookAuthError` / `HTTP 401`):
   - Richiedere all'amministratore del tenant di aggiornare l'API Key / Company Login dal pannello impostazioni.
4. Se l'errore è dovuto a slot occupato contemporaneamente (`slot_full` / `HTTP 409`):
   - Proporre al cliente tramite chat un orario alternativo.

### C. Riconciliazione Automatica
Il metodo `@system_scope ExternalBookingRepository.get_pending_reconciliations` permette ai worker in background di riprovare i record con `status='pending'` che abbiano superato il timeout di sicurezza (es. per crash di rete durante la risposta HTTP).

---

## 7. Manutenzione Programmata e Governance Post-Lancio

### A. Gate Obbligatorio di Hardening per WuBook ZaK
Prima di attivare `ZakAdapter` per la prima struttura ricettiva reale (Hotel, B&B o Resort):
1. **Ambiente Sandbox Ufficiale WuBook**: Richiesta account sviluppatore WuBook ZaK con struttura di test attiva.
2. **Reverse Engineering Protocollo & Errori**: Mappatura dei codici di risposta proprietari di ZaK (conflitti overbooking OTA, vincoli di minimum stay, chiusure per manutenzione).
3. **Piani Tariffari & Occupazione**: Gestione avanzata di trattamenti (Solo Pernottamento, B&B, Mezza Pensione) e tariffe differenziate per fasce d'età degli ospiti.
4. **Test Live Sandbox Air-Gapped**: Sviluppo di `test_zak_live_sandbox.py` con credenziali dedicate e cancellazione automatica garantita.
5. **Divieto di Attivazione Immediata**: È fatto esplicito divieto di impostare `provider='zak'` su organizzazioni con clienti reali fino al superamento del ciclo di hardening documentato.

### B. Sweep Periodico di Bonifica Sandbox SimplyBook
Per prevenire l'accumulo di prenotazioni orfane nel calendario di test (causate da eventuali cadute di connessione occorse prima che il client registrasse l'ID per il `finally` locale):
- È disponibile lo script operatore [`scripts/sweep_simplybook_sandbox.py`](file:///C:/Users/muzzo/Desktop/whatsapp-ai-responder/scripts/sweep_simplybook_sandbox.py).
- Eseguibile manualmente o schedulabile (es. cron settimanale su CI o server staging) con le variabili `SIMPLYBOOK_SANDBOX_COMPANY_LOGIN` e `SIMPLYBOOK_SANDBOX_API_KEY`.
- Identifica ed elimina in blocco tutte le prenotazioni marcate con la sentinella `[TEST-MELPIS]`.

