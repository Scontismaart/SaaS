# 🚀 Master Launch Readiness & Pricing Strategy — Melpis SaaS

**Prodotto:** Melpis (Assistente AI per WhatsApp Business per Attività di Servizio)
**Documento di Riferimento:** Strategia di Go-to-Market, Pricing, Sicurezza, Compliance e Launch Checklist
**Data Aggiornamento:** 24 Agosto 2026 (v2 — integrazione compliance Meta/WhatsApp, AI Act, sicurezza AI, fatturazione internazionale)
**Target Fase 1:** PMI di servizio locali in Italia (Ristoranti, Pizzerie, Saloni & Parrucchieri, Studi Medici/Dentistici, Centri Fitness, Hotel & B&B)
**Target Fase 2:** Espansione UE/internazionale (vedi sezione 7)

**Architettura confermata:** Integrazione diretta con Meta Cloud API (nessun BSP terzo) — questo significa che Melpis agisce come **Tech Provider** che collega il WABA (WhatsApp Business Account) di ogni cliente tramite Embedded Signup. Questo introduce requisiti di compliance specifici (Sezione 3) che non esistevano nella versione precedente del documento.

---

## 📝 Cosa è cambiato in questa versione

Rispetto alla v1, sono state aggiunte:
1. **Sezione 3 (nuova):** Compliance Meta / WhatsApp Business Platform — critica perché usate Cloud API diretta
2. **Sezione 4 (nuova):** Conformità legale estesa (EU AI Act, Registro Trattamenti, DPIA)
3. **Sezione 8 (nuova):** Sicurezza AI-specifica (prompt injection, content moderation, cost control)
4. **Sezione 9 (nuova):** Fatturazione e pagamenti per espansione internazionale
5. Bloccanti assoluti: da 6 a 14, riorganizzati per categoria
6. Testing E2E: aggiunto isolamento multi-tenant, fallback AI, test su Meta review
7. Supporto Day-1: aggiunta SLA ed escalation matrix

---

## 🧭 1. Strategia di Pricing & Adattamento al Mercato Locale

### 💡 Il Problema dell'Ancoraggio Mentale nelle PMI Italiane

Il target di Melpis non è un responsabile IT di una startup B2B che calcola il ROI in ore-uomo, ma un **titolare di una piccola attività di servizio**. Questo segmento valuta il software confrontandolo con le sue spese correnti fisse:

- **Gestionale di cassa / POS:** €15 – €30/mese
- **Software prenotazioni verticali (es. Treatwell, Fresha, TheFork):** €0 – €30/mese (o a commissione)
- **Un dipendente part-time per il weekend:** €400 – €600/mese

👉 **Obiettivo psicologico del pricing:** Melpis a **€29 – €79/mese** deve sembrare *"incredibilmente conveniente e senza pensieri"* rispetto ad assumere un operatore part-time, abbattendo la barriera mentale del "costa 4 volte il mio gestionale".

### 📊 Struttura Piani (Good-Better-Best)

| Piano | Prezzo Mensile | Fatturazione Annuale (-25%) | Conversazioni AI | Target & Razionale |
|---|:---:|:---:|:---:|---|
| **Essenziale** | €29/mese | €24/mese (€288/anno) | 300/mese | Entry level, sotto la soglia psicologica dei €30. Massimizza trial-to-paid. |
| **Crescita** ⭐ *(Hero)* | €69/mese | €59/mese (€708/anno) | 1.200/mese | Piano-ancora. Recensioni Google AI + escalation umana (HITL). Target 80% delle attività. |
| **Scala** | €149/mese | €129/mese (€1.548/anno) | 5.000/mese | Multi-sede/catene. Fino a 5 sedi, RAG su PDF complessi, setup prioritario. |

**⚠️ Nota importante:** questi prezzi restano **ipotesi da validare**, non definitivi. Non attivarli su Stripe Live finché non hai completato il Van Westendorp (sotto). Se i risultati spostano il range in modo significativo, aggiorna la tabella prima del lancio pubblico — cambiare prezzo dopo aver acquisito i primi clienti paganti è molto più delicato (serve grandfathering, vedi skill pricing).

### Come Recuperare il Margine Senza Spaventare in Ingresso

1. **Overage flessibile:** €0,10/conversazione oltre soglia (invece di €0,08)
2. **Sconto annuale al 25%** per garantire cash-flow e ridurre churn
3. **Setup fee opzionale** (€49-99 una tantum) per onboarding assistito sul piano Scala

### 🧪 Validazione Prezzo — Van Westendorp

Prima di rendere i prezzi definitivi in Stripe Live, somministrare a **15-20 lead o clienti pilota reali**:

1. A quale prezzo lo considereresti **così costoso** da scartarlo? (Troppo costoso)
2. A quale prezzo lo considereresti **così economico** da dubitare della qualità? (Troppo economico)
3. A quale prezzo lo riterresti **un affare eccellente**? (Prezzo conveniente)
4. A quale prezzo lo riterresti **costoso ma comunque valido**? (Prezzo limite)

---

## 🎯 2. I Gap Strategici di Marketing e Conversione

### 🏆 Gap #1 — Social Proof (Priorità Massima CRO)

- [ ] Raccogliere **3 citazioni reali** da clienti beta/pilota (nome, foto titolare, nome attività/città)
- [ ] Se non ci sono ancora clienti: attivare un **mini-pilota gratuito con 3-5 attività locali** in cambio di testimonianza e uso del logo
- [ ] Posizionare la sezione **subito PRIMA della tabella Prezzi**
- [ ] Micro-stat di fiducia sopra il fold: setup <10 min, risposta <5 sec, conformità GDPR & Meta API ufficiale

### 🔍 Gap #2 — SEO Tecnico (Quick Win)

- [ ] Schema `FAQPage` JSON-LD nell'`<head>` di `web/landing/index.html` (+20-35% CTR stimato da SERP)
- [ ] `sitemap.xml` esteso con pagine legali e `<lastmod>`

### 📊 Gap #3 — Tracking & Analytics (Bloccante per Advertising)

- [ ] Plausible Analytics o GA4 con Consent Mode v2
- [ ] Eventi minimi: `click_cta` (con location), `open_signup_modal`, `submit_signup_form`, `toggle_pricing_annual`
- [ ] Meta Pixel solo al lancio delle prime campagne (non prima)

### 🔁 Gap #4 — Ciclo di Vita Post-Signup (nuovo, spesso dimenticato)

Una landing perfetta non serve a nulla se dopo la registrazione l'utente si perde. Prima del lancio:

- [ ] **Sequenza email di onboarding** (3-5 email nei primi 7 giorni di trial: benvenuto, come collegare WhatsApp, come sfruttare le recensioni AI, promemoria scadenza trial)
- [ ] **Flusso di cancellazione/downgrade** con almeno un save-offer (es. sconto temporaneo o pausa abbonamento) prima della cancellazione definitiva
- [ ] **Programma referral** — per PMI locali il passaparola tra colleghi di settore (altri saloni, altri ristoranti della zona) converte molto più della pubblicità fredda; anche un semplice "invita un collega, un mese gratis per entrambi" aiuta

---

## 🔴 3. Compliance Meta / WhatsApp Business Platform (NUOVO — bloccante)

Con **Meta Cloud API diretta**, Melpis è un **Tech Provider** che collega il WABA di ogni cliente. Questo comporta requisiti che il documento originale non copriva:

- [ ] **B7. Business Verification su Meta Business Manager:** avviare la verifica aziendale di Melpis il prima possibile — può richiedere da alcuni giorni a diverse settimane e blocca l'onboarding di nuovi clienti se non completata. Iniziare in parallelo agli altri bloccanti, non alla fine.
- [ ] **B8. Embedded Signup funzionante e testato:** verificare che il flusso con cui un cliente collega il proprio numero WhatsApp Business funzioni end-to-end, incluso il caso in cui il cliente abbia già un numero WhatsApp personale/Business App da migrare (caso comunissimo tra parrucchieri e ristoratori).
- [ ] **B9. Message Template pre-approvati:** ogni messaggio "business-initiated" fuori dalla finestra di 24h dall'ultimo messaggio del cliente finale (es. conferme prenotazione proattive, promemoria appuntamento) richiede un template approvato da Meta *prima* del lancio. Sottomettere i template minimi (conferma prenotazione, promemoria, richiesta recensione) con largo anticipo: Meta può rigettarli e richiedere revisione.
- [ ] **B10. Rispetto della finestra di 24 ore:** verificare che la logica applicativa non tenti di inviare messaggi free-form oltre le 24h dall'ultimo messaggio del cliente finale (rischio ban del numero).
- [ ] **B11. Tier di messaggistica e scalabilità:** ogni nuovo numero WhatsApp Business parte da un tier limitato (es. 250 destinatari unici/24h) che sale in automatico in base alla qualità. Documentare per il team supporto cosa succede (e cosa dire al cliente) se un'attività molto trafficata raggiunge il tier limit nei primi giorni.
- [ ] **B12. Opt-in del cliente finale:** la policy di Meta richiede che l'utente finale (es. il cliente del salone) abbia dato consenso a ricevere messaggi. Questo è responsabilità del cliente Melpis (il titolare dell'attività), ma serve una guida esplicita in onboarding + una clausola nei Termini di Servizio che scarica la responsabilità sull'attività se non rispettata.
- [ ] **B13. Gestione sospensione/ban del numero:** procedura interna definita per quando un cliente Melpis riceve un warning o ban dal numero WhatsApp (succede, specie nei primi mesi con volumi bassi e qualità non ancora consolidata) — chi lo gestisce, in quanto tempo, cosa si comunica al cliente.

---

## ⚖️ 4. Conformità Legale Estesa (ampliato)

### 🤖 EU AI Act — Obbligo di Trasparenza (NUOVO, spesso ignorato)

Dal 2 agosto 2026 sono applicabili le disposizioni sulla trasparenza dell'AI Act (Art. 50): chi fa interagire un utente con un sistema di AI conversazionale ha l'obbligo di **informarlo che sta parlando con un'AI**, a meno che non sia già ovvio dal contesto.

- [ ] Verificare con un legale se il messaggio di benvenuto automatico su WhatsApp include una dicitura tipo *"Stai parlando con l'assistente virtuale di [Nome Attività], basato su intelligenza artificiale"* — va aggiunta se non è già "ovvio" dal contesto
- [ ] Verificare se serve disclosure anche per le risposte alle recensioni generate da AI (se pubblicate a nome dell'attività, valutare se serve menzione o resta responsabilità del titolare che le rivede prima di pubblicare — l'HITL/escalation umana già presente nel piano Crescita aiuta qui)

### 📋 GDPR — Documentazione Interna (ampliato)

- [ ] **Registro delle Attività di Trattamento** (Art. 30 GDPR) — obbligatorio, spesso dimenticato perché "invisibile" all'utente finale
- [ ] **DPIA (Data Protection Impact Assessment)** — valutare se necessaria: trattare in modo automatizzato conversazioni di clienti finali tramite AI, su larga scala, è un caso tipico in cui va quantomeno valutata l'opportunità di farla, anche se non sempre obbligatoria
- [ ] **Procedura di data breach notification** — piano scritto per notificare il Garante Privacy entro 72 ore in caso di violazione dei dati (richiesto da GDPR, oggi assente dal documento)
- [ ] DPA (Data Processing Agreement) già previsto all'endpoint `/api/gdpr/dpa` — verificare che elenchi correttamente tutti i sub-processori: Meta, Stripe, Supabase, OpenRouter (+ eventuali altri provider AI/email)

### 📄 Termini di Servizio — Clausole Specifiche da Non Dimenticare

- [ ] **Disclaimer allucinazioni AI:** clausola esplicita che l'attività resta responsabile di verificare le informazioni fornite dall'AI ai propri clienti (già gestito in FAQ, ma va formalizzato nei ToS con valore legale)
- [ ] **Limitazione di responsabilità** per malfunzionamenti Meta/WhatsApp non imputabili a Melpis (ban numero, downtime Meta, cambi di policy)
- [ ] **Clausola su opt-in del cliente finale** (vedi B12)

---

## 🔴 5. BLOCCANTI ASSOLUTI AL LANCIO (Giorno 0)

Aggiornati e riorganizzati per categoria. Tutti da risolvere e verificare prima del primo utente reale pagante.

### Sicurezza Applicativa
- [ ] **B1.** Disabilitazione fail-closed `DEMO_MODE` in produzione (`src/core/auth/dependencies.py`)
- [ ] **B2.** Rate limiting su Redis condiviso tra worker (`RATE_LIMIT_BACKEND=redis`, `REDIS_URL`)
- [ ] **B3.** Migrazione GDPR token store da in-memory a Redis con TTL 15 minuti (`src/core/gdpr/routes.py`)
- [ ] **B4.** Generazione `ENCRYPTION_KEY` Fernet AES-32 byte in secrets manager di produzione
- [ ] **B14. (nuovo)** Audit dipendenze per vulnerabilità note (`pip-audit` / `npm audit` o Snyk) eseguito e vulnerabilità critiche risolte prima del deploy
- [ ] **B15. (nuovo)** Security headers configurati (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) — non solo HSTS
- [ ] **B16. (nuovo)** 2FA obbligatoria per account admin/staff Melpis con accesso a dati clienti multi-tenant

### Pagamenti
- [ ] **B5.** Stripe in modalità Live: `sk_live_...`, price ID di produzione (€29/€69/€149), webhook reale con `STRIPE_WEBHOOK_SECRET`

### WhatsApp / Meta
- [ ] **B6.** Webhook Meta WhatsApp Live con `META_APP_SECRET` e `META_VERIFY_TOKEN` ufficiali, numero verificato
- [ ] **B7-B13.** Vedi Sezione 3 sopra (Business Verification, template approvati, opt-in, tier messaging, ecc.)

---

## ⚙️ 6. Checklist Configurazioni Tecniche di Produzione

### 🌐 Dominio, DNS & SSL
- [ ] Dominio `melpis.it` con record A/AAAA, HTTPS forzato con HSTS
- [ ] Sottodominio `app.melpis.it` puntato all'infrastruttura applicativa
- [ ] DNS email: SPF, DKIM, DMARC (`p=quarantine` o `p=reject`)

### 🔐 Variabili d'Ambiente (`.env.production`)
- [ ] `ENVIRONMENT=production`
- [ ] `DEMO_MODE=false`
- [ ] `DATABASE_URL=postgresql://...?sslmode=require`
- [ ] `DB_POOL_MAX_SIZE=10`
- [ ] `REDIS_URL=redis://...`
- [ ] `RATE_LIMIT_BACKEND=redis`
- [ ] `CORS_ORIGINS=https://melpis.it,https://app.melpis.it`
- [ ] `ENCRYPTION_KEY=<chiave-fernet-32-byte>`
- [ ] `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_AUD`
- [ ] `STRIPE_SECRET_KEY=sk_live_...`, `STRIPE_WEBHOOK_SECRET`
- [ ] `META_APP_SECRET`, `META_VERIFY_TOKEN`
- [ ] `OPENROUTER_API_KEY` (+ **budget alert configurato**, vedi Sezione 8)
- [ ] `SENTRY_DSN`
- [ ] `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`
- [ ] **(nuovo)** Procedura documentata di rotazione periodica dei secret (chi, ogni quanto, come)

### 🏗️ Deploy & Ambienti (nuovo)
- [ ] Ambiente di **staging** separato da produzione, usato per testare ogni release prima del deploy
- [ ] Pipeline CI/CD con test automatici e lint obbligatori prima del merge su main/produzione
- [ ] Strategia di **rollback** rapido in caso di deploy problematico (versione precedente ripristinabile in minuti, non ore)
- [ ] CDN per asset statici della landing (immagini, CSS, JS) per tempi di caricamento rapidi anche da mobile

### 📧 Email Transazionali
- [ ] Verifica account e conferma registrazione, testata
- [ ] Reset password/recupero credenziali, testato
- [ ] Notifiche escalation operatore (HITL) e riepilogo giornaliero, testate

### 💾 Backup, Database & Monitoring
- [ ] Backup giornalieri automatici, retention 30 giorni
- [ ] Test di restore eseguito con successo (`run_backup_restore_drill.py`)
- [ ] Sentry attivo su backend e frontend
- [ ] Uptime monitor esterno su `/api/health` con alert Telegram/SMS
- [ ] **(nuovo)** Status page pubblica (anche minimale, es. su BetterStack) per trasparenza durante eventuali downtime — utile per PMI che dipendono da Melpis durante il servizio

### ⚖️ Pagine Legali
- [ ] Privacy Policy con elenco sub-processori (Meta, Stripe, Supabase, OpenRouter)
- [ ] Termini di Servizio con clausole disclaimer AI e opt-in (vedi Sezione 4)
- [ ] Cookie Policy e banner conformi GDPR
- [ ] DPA accessibile su `/api/gdpr/dpa`
- [ ] **(nuovo)** Disclosure AI Act nel primo messaggio automatico (vedi Sezione 4)

---

## 🛡️ 7. Sicurezza AI-Specifica (NUOVO)

Un chatbot AI esposto a messaggi WhatsApp da utenti sconosciuti ha una superficie di rischio diversa da un form web tradizionale.

- [ ] **Difesa da prompt injection:** testare che un cliente finale non possa, scrivendo messaggi appositamente costruiti, far "dimenticare" all'AI le istruzioni di sistema, farle rivelare dati di altri clienti/attività, o farle fare promesse non autorizzate (es. sconti inesistenti)
- [ ] **Content moderation / guardrail sulle risposte:** l'AI non deve mai poter generare contenuti offensivi, discriminatori o inappropriati che danneggino la reputazione dell'attività che la usa — testare con input avversari prima del lancio
- [ ] **Isolamento dati multi-tenant nel RAG:** verificare che il retrieval AI di un'attività non possa mai accedere/mescolare documenti (PDF menu, listini) di un'altra attività
- [ ] **Validazione file upload per RAG:** i PDF caricati dalle attività (menu, listini) vanno scansionati/validati prima dell'indicizzazione (dimensione massima, tipo file, scansione antimalware) — un vettore spesso trascurato
- [ ] **Fallback su provider AI down:** se OpenRouter (o il provider AI) ha un'interruzione, cosa succede? L'utente finale deve ricevere un messaggio di cortesia ("un operatore ti risponderà a breve") invece di un errore silente o un timeout
- [ ] **Budget alert sui costi AI:** allarme automatico se la spesa giornaliera/mensile su OpenRouter supera una soglia configurata — previene bill shock in caso di abuso o bug che genera loop di chiamate

---

## 🌍 8. Fatturazione e Pagamenti — Preparazione all'Espansione Internazionale

Dato l'obiettivo dichiarato di rendere Melpis internazionale, questa sezione va pianificata **da subito** anche se il lancio iniziale resta sull'Italia, per non dover ristrutturare tutto in corsa.

### Fase 1 — Lancio Italia
- [ ] **Fatturazione elettronica SDI** obbligatoria per clienti con Partita IVA italiana — verificare integrazione con un provider di fatturazione elettronica (es. Fatture in Cloud, Aruba) collegato a Stripe o al proprio backend
- [ ] Gestione regime IVA standard per vendite B2B in Italia

### Fase 2 — Espansione UE (da preparare per non dover rifare tutto dopo)
- [ ] **Stripe Tax** abilitato per calcolo automatico IVA/VAT su clienti in altri paesi UE
- [ ] **Validazione P.IVA/VAT number tramite VIES** in fase di signup per clienti business UE extra-Italia, per applicare correttamente il meccanismo di reverse charge (B2B intra-UE, no IVA italiana addebitata se il cliente ha VAT number valido)
- [ ] Fatturazione standard (PDF, non SDI) per clienti non italiani — l'obbligo SDI vale solo per soggetti stabiliti in Italia
- [ ] Multi-valuta su Stripe (almeno EUR + eventualmente USD/GBP se si punta oltre UE)
- [ ] Termini di Servizio, Privacy Policy e UI **in inglese**, minimo, oltre all'italiano
- [ ] Verificare se l'AI Act (obblighi Art. 50) e il GDPR restano il framework di riferimento anche per clienti extra-IT ma dentro UE (sì, sono regolamenti UE) — per clienti extra-UE, valutare caso per caso con un legale se servono adempimenti aggiuntivi (es. UK GDPR post-Brexit se si espande lì)

### Gestione Pagamenti Fallati e Dispute
- [ ] Flusso di **dunning** per pagamenti falliti (retry automatico + email al cliente prima della sospensione)
- [ ] Procedura documentata per gestione **chargeback/dispute** su Stripe

---

## 🧪 9. Test End-to-End Finale (Smoke Test in Produzione) — Ampliato

### Test Funzionali Base (già previsti)
- [ ] Registrazione nuovo account dalla landing (`#signupForm`)
- [ ] Conferma email e primo accesso alla dashboard
- [ ] Connessione guidata WhatsApp e configurazione orari/menu
- [ ] Invio messaggio da cellulare reale, risposta AI entro 5 secondi
- [ ] Sottoscrizione Stripe Live con carta reale, verifica accredito
- [ ] Cancellazione abbonamento e transizione a stato sola-lettura

### Test Aggiuntivi Critici (nuovi)
- [ ] **Isolamento multi-tenant:** verificare esplicitamente che l'utente/attività A non possa in nessun modo vedere dati, conversazioni o documenti dell'attività B (test IDOR)
- [ ] **Fallback AI provider down:** simulare interruzione OpenRouter e verificare il comportamento (messaggio di cortesia, non errore)
- [ ] **Test su Meta Embedded Signup con numero reale già in uso** (caso comune: titolare con numero WhatsApp personale/Business App da migrare)
- [ ] **Test invio template message approvato** (es. promemoria appuntamento) fuori dalla finestra di 24h
- [ ] **Test carico concorrente:** simulare più conversazioni simultanee su più attività per verificare tenuta sotto carico realistico di lancio
- [ ] **Test cross-browser/device:** in particolare Safari iOS, dato che molti titolari di PMI gestiscono tutto da iPhone

---

## 📞 10. Supporto Clienti Day-1 — Ampliato

- [ ] Casella `support@melpis.it` attiva e monitorata
- [ ] Canale WhatsApp di assistenza rapida ai titolari, attivo durante le ore di servizio
- [ ] **(nuovo) SLA minima definita e comunicata:** es. "risposta entro 2 ore lavorative" — per un'attività che dipende da Melpis durante il servizio, sapere i tempi di risposta è una leva di fiducia, non solo operativa
- [ ] **(nuovo) Escalation matrix interna:** chi gestisce un ban del numero WhatsApp di un cliente, chi gestisce un bug critico che blocca le risposte AI durante orario di punta, chi è reperibile nei primi giorni post-lancio

---

## 📅 11. Piano d'Azione Aggiornato (Timeline)

### 🗓️ Settimana 1 — Bloccanti Tecnici, Meta, Legali
1. Avviare **Business Verification Meta** (B7) — parallelo a tutto il resto, ha lead time lungo
2. Risolvere B1-B6 (sicurezza/pagamenti) e B14-B16 (audit dipendenze, security headers, 2FA admin)
3. Sottomettere i **message template** a Meta per approvazione (B9) — anche questo ha lead time
4. FAQPage JSON-LD + sitemap estesa
5. Installare Plausible/GA4 con eventi CTA
6. Verificare/aggiornare Termini di Servizio con clausole AI Act, disclaimer allucinazioni, opt-in cliente finale

### 🗓️ Settimana 2-3 — Validazione Prezzo, Social Proof, Compliance Fine
1. 3 testimonianze reali posizionate sopra i Piani
2. Van Westendorp su 15-20 lead per validare €29/€69/€149
3. Test A/B nuova struttura prezzi
4. Registro Trattamenti + valutazione DPIA
5. Test Embedded Signup con numero reale, test template message
6. Sicurezza AI: test prompt injection e isolamento multi-tenant RAG

### 🗓️ Settimana 4 — Smoke Test Completo e Go-Live
1. Eseguire tutti i test E2E ampliati (Sezione 9)
2. Verificare stato Business Verification e template approvati con Meta
3. Attivare status page e uptime monitor
4. Go-live con monitoraggio attivo nelle prime 48-72 ore (nessun deploy "e poi si vedrà")

### 🗓️ Settimana 5+ — Scaling & Acquisizione
1. Meta Pixel e prime campagne Lookalike su P.IVA locali
2. Sequenza email onboarding attiva
3. Primo case study approfondito
4. Setup fee per onboarding assistito su piano Scala
5. Iniziare a preparare Fase 2 (Stripe Tax, VIES, ToS in inglese) senza fretta, ma senza rimandare a data indefinita
