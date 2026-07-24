# Prompt operativi per la roadmap del SaaS

Ogni blocco = un punto della roadmap. Contiene:
- **Tipo di lavoro** (per capire perché ho scelto quelle skill)
- **Skill da invocare, in ordine**
- **Prompt pronto da incollare** alla tua AI

Regola generale usata per scegliere le skill:
- Feature nuova/complessa → `brainstorming` → `writing-plans` → `test-driven-development` → `executing-plans` → `requesting-code-review` → `verification-before-completion`
- Bugfix / debito tecnico → `systematic-debugging` → `test-driven-development` → `verification-before-completion`
- Lavoro UI/design → `brainstorming` → `writing-plans` + skill di design proprie (`design-taste-frontend`, `minimalist-ui`, `high-end-visual-design`, `brandkit`) → `executing-plans` → `requesting-code-review`
- Task grandi con parti indipendenti → `dispatching-parallel-agents` o `subagent-driven-development`, eventualmente con `using-git-worktrees` per isolare i branch
- Sempre, in chiusura, `verification-before-completion` prima di dichiarare "fatto", e `finishing-a-development-branch` quando il lavoro è pronto per il merge

---

## P0 — Bloccanti per vendere

### 1. Integrazione WhatsApp Business reale
**Tipo:** feature critica, multi-componente (webhook, sicurezza, mapping tenant, invio messaggi, stati)
**Skill:** brainstorming → writing-plans → using-git-worktrees → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa la skill "brainstorming" per esplorare i requisiti dell'integrazione WhatsApp Business
Cloud API su questo progetto. Devo coprire:
- Webhook Meta Cloud API (GET per verifica, POST per ricezione eventi)
- Verifica firma X-Hub-Signature-256 su ogni richiesta in ingresso
- Mapping phone_number_id -> tenant (organization) nel nostro modello dati
- Invio risposte tramite Meta Graph API: messaggi di testo liberi entro la finestra
  delle 24h, template pre-approvati fuori finestra
- Gestione e persistenza degli stati messaggio (sent, delivered, read, failed)
- Gestione opt-in/opt-out utente e conformità alla WhatsApp Business Policy

Fammi domande su eventuali ambiguità (es. quale libreria HTTP client usare, come
gestiamo i retry, dove salviamo i template approvati) prima di proseguire.

Una volta chiariti i requisiti, usa "writing-plans" per creare un piano di
implementazione a step, poi "using-git-worktrees" per isolare il lavoro in un
worktree dedicato. Implementa con "test-driven-development" (test prima del
codice per: verifica firma, mapping tenant, invio messaggio, gestione stati).
Esegui il piano con "executing-plans" e fermati ai checkpoint di review.
Prima di dichiarare il lavoro completo, usa "verification-before-completion"
per far girare i test e mostrarmi l'output reale, poi "requesting-code-review"
per un self-check finale del codice prodotto.
```

---

### 2. Multi-tenancy + database persistente
**Tipo:** feature architetturale critica
**Skill:** brainstorming → writing-plans → using-git-worktrees → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa "brainstorming" per definire con me lo schema dati multi-tenant su
PostgreSQL, partendo dalle entità: organizations, users, business_profiles,
conversations, messages, bookings, reviews, documents (+ metadata RAG),
usage_events (per billing). Chiarisci con me relazioni, chiavi, indici e
strategia di migrazione dai dati attuali in RAM/Airtable.

Definisci anche la strategia di isolamento: organization_id obbligatorio su
ogni query e su ogni collection ChromaDB (collection separata o prefisso
org_{id}_). Chiedimi conferma su quale delle due strategie ChromaDB preferisco
prima di procedere.

Poi usa "writing-plans" per pianificare: migrazioni DB, refactor dei layer di
accesso dati per iniettare organization_id ovunque, script di migrazione dei
dati esistenti. Isola il lavoro con "using-git-worktrees". Implementa con
"test-driven-development", scrivendo prima i test che verificano l'isolamento
tra tenant (nessuna query deve poter leggere dati di un altro organization_id).
Esegui con "executing-plans", poi valida con "verification-before-completion"
(far girare le migrazioni e i test su un DB reale, non solo in teoria) e
concludi con "requesting-code-review".
```

---

### 3. Autenticazione e autorizzazione
**Tipo:** feature critica di sicurezza
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa "brainstorming" per definire il sistema di autenticazione e autorizzazione:
- Provider auth (valuta Clerk, Supabase Auth, Auth0: chiedimi quale preferisco
  in base a budget/vendor lock-in)
- Ruoli: owner, manager, staff (sola lettura ticket) e permessi associati
- JWT/API key per i webhook interni (es. webhook WhatsApp)
- Rate limiting per endpoint AI (per tenant e per utente)
- Audit log delle azioni sensibili (modifica profilo, risposta manuale, ecc.)

Chiarisci con me eventuali dubbi su CORS (oggi allow_origins=["*"], va
ristretto) prima di scrivere codice.

Poi usa "writing-plans" per pianificare l'introduzione dell'auth in tutte le
route esistenti senza rompere l'app. Implementa con "test-driven-development"
(test di autorizzazione per ogni ruolo, test che un endpoint protetto rifiuti
richieste senza token valido). Esegui con "executing-plans". Prima di
chiudere, usa "verification-before-completion" per verificare concretamente
che le route siano protette (prova richieste reali senza/con token) e
"requesting-code-review" per revisione finale.
```

---

### 4. Billing e piani SaaS (Stripe)
**Tipo:** feature critica business
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa "brainstorming" per definire l'integrazione Stripe con questi piani:
- Starter 49€/mese: 1 numero WA, 500 msg/mese, 1 utente
- Pro 99€/mese: 2.000 msg, recensioni auto, 3 utenti
- Business 199€/mese: illimitato*, RAG avanzato, multi-sede
Copri: metering di messaggi AI/token LLM/documenti indicizzati, trial 14
giorni, Customer Portal Stripe, webhook invoice.paid e subscription.deleted
con conseguente sospensione servizio. Chiedimi conferma sui prezzi/limiti
esatti e su come vogliamo gestire l'overage (blocco o addebito extra) prima
di procedere.

Poi usa "writing-plans" per pianificare: modello dati usage_events collegato
al billing, integrazione webhook Stripe, logica di sospensione/riattivazione
account. Implementa con "test-driven-development" (test sui webhook Stripe
con eventi mockati, test sulla logica di sospensione). Esegui con
"executing-plans". Verifica con "verification-before-completion" usando la
CLI Stripe in modalità test per simulare eventi reali, poi
"requesting-code-review".
```

---

### 5. Sicurezza e compliance (GDPR)
**Tipo:** misto: bugfix di sicurezza immediati + feature di compliance
**Skill:** systematic-debugging (per i problemi esistenti) → brainstorming → writing-plans → test-driven-development → executing-plans → verification-before-completion

```
Prima usa "systematic-debugging" per fare un audit di sicurezza del repo
attuale: verifica cosa è effettivamente escluso da .gitignore, se .env,
token Gmail e client_secret.json rischiano di finire in un commit, e se
ENCRYPTION_KEY in .env è davvero usata da qualche parte nel codice. Dammi un
report puntuale di cosa è a rischio adesso, prima di qualsiasi altro intervento.

Poi usa "brainstorming" per definire il resto della compliance GDPR:
- creazione di .env.example (mancante ma referenziato in llm_config.py)
- cifratura a riposo dei token OAuth usando ENCRYPTION_KEY
- retention policy sui messaggi (default 90 giorni, configurabile)
- funzionalità di export/cancellazione dati cliente (diritto all'oblio)
- bozza di DPA per clienti B2B
- CORS ristretto ai soli domini del prodotto

Usa "writing-plans" per pianificare l'implementazione, "test-driven-development"
per i test (es. verifica che i token siano effettivamente cifrati a riposo,
che l'export/cancellazione dati funzioni per un intero tenant), esegui con
"executing-plans" e chiudi con "verification-before-completion" mostrando
l'output reale di .gitignore aggiornato, un token cifrato nel DB, e una prova
di export/cancellazione dati.
```

---

## P1 — Differenziazione prodotto

### 6. Human-in-the-loop (HITL)
**Tipo:** feature prodotto centrale
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa "brainstorming" per progettare il flusso HITL completo, partendo da quello
che già esiste (richiede_umano, priorità alta/media/bassa):
- Inbox condivisa per i ticket escalati
- Notifiche (push/email/SMS) al titolare quando serve intervento umano
- Risposta manuale dal pannello che venga inviata realmente su WhatsApp
- Stato conversazione: AI -> In attesa staff -> Risolto
- SLA visibili tipo "risposta umana entro 15 min"
- Assegnazione ticket a un membro specifico del team

Chiedimi conferma su quale canale di notifica dare priorità (email vs SMS vs
push PWA) prima di implementare tutto.

Poi "writing-plans" per pianificare l'inbox, gli stati conversazione e le
notifiche. Implementa con "test-driven-development" (test sulle transizioni
di stato, test che una risposta manuale venga effettivamente inviata via
WhatsApp API). Esegui con "executing-plans", verifica con
"verification-before-completion" e chiudi con "requesting-code-review".
```

---

### 7. Onboarding self-service (wizard)
**Tipo:** feature UI + logica di business
**Skill:** brainstorming → writing-plans → design-taste-frontend / minimalist-ui / brandkit → test-driven-development → executing-plans → requesting-code-review

```
Usa "brainstorming" per definire il wizard di onboarding self-service che
sostituisce i PROFILI_DEMO hardcoded, con questi step:
1. Tipo di attività (ristorante, parrucchiere, studio medico...)
2. Orari, servizi, tono di voce (con anteprima risposta AI generata al volo)
3. Regole di escalation (checkbox precompilate per settore)
4. Collegamento WhatsApp Business
5. Import menu/documenti (PDF)
6. Test conversazione guidata

Voglio anche template verticali: stesso motore AI, prompt di sistema diversi
per settore. Chiedimi quali verticali vuoi supportare al lancio (oltre ai
ristoranti) prima di disegnare i template.

Poi usa "writing-plans" per pianificare backend (storage profili per
verticale) e frontend (wizard multi-step). Per l'interfaccia usa
"design-taste-frontend", "minimalist-ui" e "brandkit" per uno stile coerente
col brand del prodotto, non un wizard generico. Implementa con
"test-driven-development" per la logica di salvataggio profilo e generazione
anteprima AI. Esegui con "executing-plans", chiudi con
"requesting-code-review" e "verification-before-completion" facendo
effettivamente completare il wizard end-to-end.
```

---

### 8. Prenotazioni come prodotto standalone
**Tipo:** feature esistente da estendere/migrare
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa "brainstorming" per pianificare l'evoluzione del modulo prenotazioni
(già presente con semaforo e capienze orarie) verso un prodotto standalone:
- Conferma/rifiuto prenotazione con messaggio WhatsApp automatico
- Reminder 24h prima ("Confermi la prenotazione?")
- Tracking no-show
- Integrazione con TheFork / Google Reserve / Calendly (chiedimi quale
  integrazione dare priorità)
- Migrazione da Airtable a DB nativo con API pulita (dipende dal punto 2:
  multi-tenancy + DB, verifica che sia già stato fatto o pianifica in parallelo)
- Deposito/cauzione per eventi tramite Stripe Payment Links

Poi usa "writing-plans" per pianificare la migrazione da Airtable e le nuove
funzionalità, separando chiaramente cosa dipende dal punto 2. Implementa con
"test-driven-development" (test su conferma/rifiuto, reminder schedulati,
no-show tracking). Esegui con "executing-plans", verifica con
"verification-before-completion" e chiudi con "requesting-code-review".
```

---

### 9. Recensioni automatiche
**Tipo:** feature nuova, sostituzione di stub esistenti
**Skill:** systematic-debugging (per capire cosa fanno oggi gli stub) → brainstorming → writing-plans → test-driven-development → executing-plans → verification-before-completion

```
Prima usa "systematic-debugging" per analizzare google_stub.py e
tripadvisor_stub.py: cosa dovrebbero fare, dove vengono chiamati, cosa rompe
oggi il NotImplementedError.

Poi usa "brainstorming" per progettare l'implementazione reale:
- Integrazione Google Business Profile API per fetch recensioni nuove
- Generazione bozza risposta AI -> approvazione one-click -> pubblicazione
- Alert automatico per recensioni <= 3 stelle (priorità alta, va nel flusso HITL)
- Analytics sentiment nel tempo (colleghiamolo alla dashboard esistente)

Chiedimi se vogliamo partire solo da Google o includere subito anche
TripAdvisor, dato il costo/complessità delle rispettive API.

Usa "writing-plans" per pianificare l'implementazione, "test-driven-development"
per i test (fetch recensioni mockato, generazione bozza, alert su rating
basso). Esegui con "executing-plans" e verifica con
"verification-before-completion" mostrando una recensione reale processata
end-to-end.
```

---

### 10. Canali aggiuntivi (Instagram, Messenger, Widget, Email)
**Tipo:** feature di estensione, parallelizzabile
**Skill:** brainstorming → writing-plans → dispatching-parallel-agents → test-driven-development → executing-plans → requesting-code-review

```
Usa "brainstorming" per definire come estendere i canali di messaggistica,
sfruttando il fatto che CanaleMessaggio ha già instagram non utilizzato:
- Instagram DM (stessa piattaforma Meta del WhatsApp, quindi riusa
  l'infrastruttura webhook del punto 1)
- Facebook Messenger
- Widget di chat sul sito web del locale
- Email (Gmail già parzialmente integrato, va completato)

Nota: come indicato nella roadmap, questo canale va sviluppato DOPO che
WhatsApp è stabile in produzione. Confermami che possiamo procedere prima di
continuare.

Usa "writing-plans" per pianificare ciascun canale come modulo indipendente
che si aggancia alla stessa pipeline di conversazione/AI. Dato che i canali
sono indipendenti tra loro, usa "dispatching-parallel-agents" per lavorare
in parallelo su Instagram, Messenger, widget ed email. Implementa ciascuno
con "test-driven-development", esegui con "executing-plans" e chiudi con
"requesting-code-review" per ogni modulo.
```

---

## P2 — Qualità AI e vantaggio competitivo

### 11. RAG integrato nelle risposte cliente
**Tipo:** feature critica di qualità prodotto (quick win ad alto impatto)
**Skill:** systematic-debugging → writing-plans → test-driven-development → executing-plans → verification-before-completion

```
Usa "systematic-debugging" per capire esattamente perché oggi /api/documenti/*
(RAG) e /api/messaggio (assistente clienti) sono disconnessi: dove si ferma
il flusso, cosa manca per collegarli.

Poi usa "writing-plans" per pianificare il collegamento:
- Retrieval su menu/prezzi/policy del locale prima di ogni risposta AI
- Citazione della fonte interna nei log (non mostrata al cliente, solo per audit)
- Aggiornamento automatico della knowledge base quando viene caricato un
  nuovo PDF menu
- Fallback esplicito: "Non ho questa informazione, ti metto in contatto con
  lo staff" quando il retrieval non trova nulla di rilevante

Implementa con "test-driven-development": test che verificano che una
domanda su un prezzo presente nel PDF produca una risposta corretta citata
correttamente in log, e che una domanda fuori knowledge base attivi il
fallback verso lo staff. Esegui con "executing-plans" e verifica con
"verification-before-completion" facendo una prova reale end-to-end con un
PDF di test.
```

---

### 12. Guardrails e qualità risposta
**Tipo:** feature di qualità/affidabilità
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → requesting-code-review → verification-before-completion

```
Usa "brainstorming" per definire i guardrail sulle risposte AI:
- Validazione output post-LLM (lunghezza massima, tono coerente col profilo,
  nessuna allucinazione su prezzi non presenti nel RAG)
- Classificatore di intent separato, con un modello economico, prima del
  responder principale
- A/B test dei prompt per tenant
- Feedback loop 👍/👎 sulle risposte, con log per iterare sui prompt
- Cache delle risposte FAQ più frequenti per risparmiare token

Chiedimi quale modello economico preferisci per il classificatore di intent
prima di implementarlo.

Usa "writing-plans" per pianificare l'ordine di implementazione (guardrail
di validazione output prima, poi classificatore, poi A/B test e feedback
loop). Implementa con "test-driven-development" (casi di test con risposte
che devono essere bloccate/corrette dal validatore). Esegui con
"executing-plans", chiudi con "requesting-code-review" e
"verification-before-completion".
```

---

### 13. Model routing intelligente
**Tipo:** feature di infrastruttura AI
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → verification-before-completion

```
Usa "brainstorming" per progettare il routing multi-modello, partendo dal
fatto che oggi c'è un solo modello (nvidia/nemotron-3-ultra-550b-a55b:free
via OpenRouter):
- Modello economico per FAQ semplici
- Modello premium per escalation/recensioni/casi complessi
- Fallback automatico se un provider è down
- Budget token collegato al piano Stripe del tenant (dipende dal punto 4)

Chiedimi quali modelli specifici vuoi usare per ciascun livello (economico
vs premium) prima di scrivere il codice di routing.

Usa "writing-plans" per pianificare la logica di routing e il collegamento
al sistema di billing/usage_events. Implementa con "test-driven-development"
(test che verificano la scelta del modello in base al tipo di richiesta e al
budget residuo del tenant, test sul fallback quando un provider risponde
errore). Esegui con "executing-plans" e verifica con
"verification-before-completion".
```

---

### 14. Multilingua
**Tipo:** feature di prodotto, relativamente contenuta
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → verification-before-completion

```
Usa "brainstorming" per progettare il supporto multilingua, sfruttando il
fatto che l'embedding usato (paraphrase-multilingual-MiniLM-L12-v2) è già
multilingue:
- Rilevamento automatico della lingua del messaggio in ingresso
- Risposta generata nella stessa lingua del cliente (utile per i turisti)
- Campo nel profilo business per definire le lingue supportate dal locale

Usa "writing-plans" per pianificare dove inserire il rilevamento lingua nella
pipeline (prima o dopo il retrieval RAG del punto 11) e come adattare il
prompt di sistema. Implementa con "test-driven-development" (test con
messaggi in italiano, inglese, tedesco che devono ricevere risposta nella
lingua corretta). Esegui con "executing-plans" e verifica con
"verification-before-completion" con esempi reali multilingua.
```

---

## P3 — Operazioni, scalabilità, go-to-market

### 15. Infrastruttura production-ready
**Tipo:** infrastruttura, parti largamente indipendenti
**Skill:** writing-plans → dispatching-parallel-agents → test-driven-development → executing-plans → verification-before-completion

```
Usa "writing-plans" per pianificare la messa in produzione dell'infrastruttura:
- Docker + docker-compose (API + Postgres + Redis)
- Scelta piattaforma di deploy (Railway, Fly.io o AWS ECS: chiedimi quale
  preferisco in base a budget e competenze del team)
- Redis per code messaggi e sessioni
- Worker separati: message_processor, reindex_worker (quest'ultimo esiste
  già parzialmente, va completato)
- Health check avanzato su /api/health (oggi controlla solo l'API key)
- Monitoring con Sentry + Datadog/Grafana
- Backup automatici di Postgres e ChromaDB

Dato che i sotto-task sono in gran parte indipendenti (dockerizzazione,
worker, monitoring, backup), usa "dispatching-parallel-agents" per
lavorarci in parallelo dopo aver definito il piano. Applica
"test-driven-development" dove ha senso (es. test di integrazione che il
worker processi effettivamente un messaggio dalla coda Redis). Esegui con
"executing-plans" e chiudi con "verification-before-completion" facendo
girare realmente docker-compose up e verificando che tutti i servizi
rispondano.
```

---

### 16. Fix debito tecnico immediato
**Tipo:** bugfix multipli, indipendenti tra loro
**Skill:** systematic-debugging → dispatching-parallel-agents → test-driven-development → verification-before-completion

```
Usa "systematic-debugging" per analizzare uno per uno questi problemi noti
nel codice, senza correggerli finché non hai chiarito la causa radice di
ciascuno:
1. Il frontend usa IMAP mentre il backend usa Gmail OAuth: disallineamento
   tra app.js e index.html
2. avvia_polling_email non viene mai chiamato: va collegato nel lifespan
   dell'app
3. Pillow è usato nel codice ma manca da requirements.txt
4. routes.py legacy non è montato da nessuna parte: va rimosso o integrato
5. Lo stato dell'applicazione si perde ad ogni restart per mancanza di DB
   persistente (collegato al punto 2 della roadmap)
6. Manca completamente un README
7. Non ci sono test automatici
8. Il repository Git non è nemmeno inizializzato

Per i punti 1-4 (bug indipendenti), usa "dispatching-parallel-agents" per
risolverli in parallelo una volta chiarita la causa di ciascuno.
Per il punto 6 (README), scrivi documentazione di setup e architettura.
Per il punto 7, usa "test-driven-development" per introdurre i primi test
con pytest su prenotazioni, escalation e webhook.
Per il punto 8, inizializza il repo Git e imposta una CI di base con GitHub
Actions (lint + test).
Chiudi ogni fix con "verification-before-completion", mostrandomi l'output
reale (es. requirements.txt aggiornato, test che passano, CI verde).
```

---

### 17. Analytics e report vendibili
**Tipo:** feature di prodotto, estensione di asset esistente
**Skill:** brainstorming → writing-plans → test-driven-development → executing-plans → requesting-code-review

```
Usa "brainstorming" per potenziare il report giornaliero AI già esistente,
trasformandolo in un asset vendibile:
- Report settimanale in PDF inviato via email
- KPI: tempo medio di risposta, % gestito da AI senza intervento umano,
  numero di prenotazioni generate, recensioni a cui è stato risposto
- Benchmark rispetto al settore ("i tuoi tempi sono migliori del 40% della
  media")
- Export CSV per commercialista/contabilità

Chiedimi da dove prendiamo i dati di benchmark di settore (dato reale,
stimato, o rimandato a fase 2) prima di implementare quella parte.

Usa "writing-plans" per pianificare generazione PDF, invio email schedulato
e export CSV. Implementa con "test-driven-development" (test sul calcolo dei
KPI a partire da dati mock, test sulla generazione PDF). Esegui con
"executing-plans", chiudi con "requesting-code-review" e verifica
generando un report reale su dati di test.
```

---

### 18. White-label / agenzie
**Tipo:** feature di scalabilità go-to-market, non urgente
**Skill:** brainstorming → writing-plans → design-taste-frontend / brandkit → test-driven-development → executing-plans → requesting-code-review

```
Usa "brainstorming" per definire il programma white-label per agenzie di
marketing locali:
- Dominio custom per cliente (es. assistenza.trattoriadamario.it)
- Logo e colori personalizzabili per tenant
- Programma partner/reseller con tracciamento commissioni

Chiedimi se questo va prioritizzato ora o rimandato dopo aver validato i
punti P0/P1, dato che la roadmap lo colloca tra le fasi più avanzate.

Usa "writing-plans" per pianificare il supporto multi-dominio e il
theming per tenant. Usa "design-taste-frontend" e "brandkit" per garantire
che il theming dinamico resti coerente ed elegante per ogni cliente.
Implementa con "test-driven-development" (test che verificano che il
dominio custom carichi il tenant corretto e il tema giusto). Esegui con
"executing-plans" e chiudi con "requesting-code-review".
```

---

### 19. Landing page + marketing site
**Tipo:** contenuto/design, non applicativo
**Skill:** brainstorming → writing-plans → design-taste-frontend / high-end-visual-design / brandkit → requesting-code-review

```
Usa "brainstorming" per definire la struttura del sito marketing pubblico
(oggi manca, esiste solo la dashboard interna):
- Landing page con demo video, orientata all'outreach commerciale
- Pricing page allineata ai piani Stripe (Starter/Pro/Business)
- Case study "Trattoria Da Mario"
- Integrazione Calendly per prenotare demo call
- Blog SEO, a partire da un articolo tipo "Come rispondere alle recensioni
  Google con l'AI"

Usa il posizionamento suggerito: non vendere "chatbot WhatsApp" (commodity
satura), ma "l'assistente clienti che non fa perdere prenotazioni,
recensioni e ticket urgenti". Le killer feature da mettere in evidenza sono:
risponde su WhatsApp mentre sei in servizio, prenotazioni automatiche con
semaforo disponibilità, avvisa solo quando serve un umano, report serale su
cosa è successo in giornata.

Usa "writing-plans" per pianificare le pagine da creare. Usa
"high-end-visual-design", "design-taste-frontend" e "brandkit" per il design
visivo, "minimalist-ui" se preferiamo un'estetica più essenziale (chiedimi
quale direzione preferisco prima di procedere). Chiudi con
"requesting-code-review" per verificare qualità del codice frontend prodotto.
```

---

### 20. Mobile app o PWA
**Tipo:** feature prodotto, dipende da HITL (punto 6)
**Skill:** brainstorming → writing-plans → design-taste-frontend / minimalist-ui → test-driven-development → executing-plans → requesting-code-review

```
Usa "brainstorming" per progettare la PWA per i titolari dei locali, che
useranno prevalentemente dal telefono:
- Notifiche push per i ticket urgenti (si aggancia al flusso HITL del punto 6)
- Azione rapida "approva risposta" e "conferma prenotazione" con un solo tap

Conferma che il flusso HITL (punto 6) sia già implementato o pianificato in
parallelo, dato che questa feature ne dipende direttamente.

Usa "writing-plans" per pianificare service worker, notifiche push e le
azioni rapide. Usa "design-taste-frontend" e "minimalist-ui" per un'interfaccia
mobile essenziale e veloce da usare con un tap. Implementa con
"test-driven-development" (test sulle notifiche push simulate, test che
un'azione rapida aggiorni correttamente lo stato del ticket/prenotazione).
Esegui con "executing-plans", chiudi con "requesting-code-review" e
"verification-before-completion" testando la PWA su un device reale o
emulato.
```

---

## Quick wins (1–2 settimane, alto impatto)

**Tipo:** bugfix + task rapidi, indipendenti tra loro → ottimo caso per parallelizzare
**Skill:** systematic-debugging (dove serve) → dispatching-parallel-agents → verification-before-completion

```
Voglio affrontare questi 6 quick win in parallelo, dato che sono
indipendenti tra loro. Usa "dispatching-parallel-agents" per assegnarli a
task separati, e per ciascuno segui questo approccio:

1. README + .env.example: scrivi la documentazione di setup del progetto e
   crea il file .env.example mancante (oggi referenziato in llm_config.py
   ma assente), così i beta tester possono fare onboarding da soli.

2. Fix .gitignore: usa "systematic-debugging" per verificare esattamente
   cosa rischia di finire in un commit oggi (oltre a data/chroma/), poi
   correggi il .gitignore per proteggere .env, token Gmail e
   client_secret.json PRIMA di qualsiasi nuovo commit.

3. Collegare il RAG al responder: implementa il collegamento minimo tra
   /api/documenti/* e /api/messaggio (versione base del punto 11 della
   roadmap) per un miglioramento immediato della qualità delle risposte.

4. Persistenza eventi su SQLite: sposta _storico_eventi dalla RAM a SQLite
   come bridge temporaneo verso la migrazione Postgres completa (punto 2).

5. Notifiche email su escalation: implementa un invio email semplice al
   titolare quando una conversazione viene marcata come richiede_umano,
   come primo passo verso il flusso HITL completo (punto 6).

6. Template WhatsApp pre-approvati: prepara e documenta i template di
   messaggio necessari per l'integrazione Meta Cloud API (punto 1), anche
   se l'integrazione vera e propria non è ancora pronta.

Per ciascuno dei 6, chiudi con "verification-before-completion" mostrandomi
l'output reale (file creati, query SQLite eseguite, email di test inviata,
ecc.) prima di passare al successivo.
```

---

## Note d'uso

- I punti **1, 2, 3** sono fortemente interdipendenti: valuta se farli partire in un ordine preciso (di solito: 2 DB persistente → 3 auth → 1 WhatsApp) oppure in worktree paralleli se il team è più di una persona.
- Per ogni punto "grande" (1, 2, 6, 7, 15), se lavori con più agenti/sessioni in parallelo, usa **subagent-driven-development** per eseguire il piano tramite sotto-agenti nella stessa sessione invece di seguirlo manualmente passo-passo.
- Quando un punto è pronto per essere unito al branch principale, chiama esplicitamente **finishing-a-development-branch** per far decidere all'AI se mergiare, aprire PR o tenere il branch aperto.
- Se in una risposta noti output tagliato o placeholder tipo `// TODO` al posto di codice reale, richiama **full-output-enforcement**.
