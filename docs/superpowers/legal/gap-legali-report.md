# Report gap legali residui — Melpis

**Data:** 2026-08-16
**Stato:** documento di lavoro per la review legale — non sostituisce la consulenza di un avvocato o DPO.
**Documenti correlati:** DPA (`docs/superpowers/dpa/DPA-melpis.md`), bozze ToS e Informativa privacy (`docs/superpowers/legal/`), rotta pubblica `/api/gdpr/dpa`.

## 1. Executive summary

La disclosure AI Act art. 50(1) al primo contatto meccanico è implementata e
testata (147 pass). Il DPA e le bozze ToS/Informativa sono allineati al codice
reale (sub-responsabili, retention, misure di sicurezza, data breach). Restano
esclusivamente attività che richiedono la valutazione di un professionista o
dati aziendali non ancora disponibili. **Nessun documento va pubblicato o
fatto accettare a clienti finché non sussistono i punti di cui ai §2-§6.**

## 2. Segnaposto da compilare (bloccato dalla disponibilità dei dati)

I documenti sono ancora anonimi: non esiste attualmente una società né una
P.IVA (stato dichiarato dal committente al 2026-08-16). Da compilare in tutti
e tre i documenti prima della sottoscrizione con clienti reali:

| Segnaposto | Documenti | Note |
|---|---|---|
| `[RAGIONE SOCIALE FORNITORE]` | DPA, ToS, Informativa | Ragione sociale dell'eventuale società (o dati del soggetto erogatore) |
| `[INDIRIZZO]` / `[CITTÀ]` | DPA, ToS, Informativa | Sede legale e foro competente (DPA §14, ToS §12) |
| `[P.IVA]` | DPA, ToS, Informativa | Partita IVA del fornitore |
| `[DATA]` | DPA, ToS, Informativa | Data di ultimo aggiornamento |
| `[REV]` | ToS, Informativa | Punti markati per decisione legale (vedi sotto) |
| `[N]`/`[M]` giorni sospensione | ToS Appendice 1 | Termini commerciali di sospensione/disattivazione |
| contatto privacy effettivo | Informativa §7 | Sostituisce i "canali di supporto" generici; l'email `dpo@example.com` è stata rimossa |

Finché i documenti restano anonimi, il soggetto cui è imputabile ogni
obbligo giuridico (art. 28 GDPR, AI Act) è indeterminato.

## 3. Validazioni giuridiche richieste dal DPA

### 3.1 Base giuridica e messaggi proattivi (DPA §4.2, ToS §5.1)
- **Riscontro a messaggi in entrata.** Il Servizio risponde a messaggi in entrata avviati dal contatto
  (legittimo interesse del Titolare: nota §4.2). Va validato: se e in quali
  casi il legittimo interesse è invocabile per il riscontro.
- **Proattivi.** Promemoria prenotazione e richieste di recensione possono
  richiedere **consenso esplicito** ai sensi della normativa ePrivacy
  (art. 130 Codice Privacy; Decision 2006/459; linee guida WP29/EDPB). Il
  Servizio oggi registra `consent_status` (opt-in/opt-out) ma **non** raccoglie
  consenso esplicito strutturato per i messaggi proattivi. Decidere se il
  mantenimento di promemoria/richieste recensione a contatti senza opt-in sia
  accettabile o vada disattivabile per-configurazione.
- **Azioni possibili lato prodotto** (fuori dal presente repo): meccanismo di
  opt-in esplicito (es. bottone) per contatti destinatari di proattivi.

### 3.2 Trasferimenti extra-UE (DPA §6.3, Allegato B; Informativa §6)
- **Verifica strumenti e region.** Per ciascun sub-responsabile va confermato, alla data di
  sottoscrizione, lo **strumento di trasferimento effettivo**: SCC (2021/914)
  e/o EU-U.S. Data Privacy Framework, e le region/data-residency reali.
- **Elementi noti (da codice/credenziali, non da documentazione dei fornitori):**
  - Meta (WhatsApp Cloud API) — USA; strumento da confermare.
  - OpenRouter e LLM sottostanti — USA/variabile; data residency non
    documentata; valutare se il traffico a determinati provider sia
    configurabile/impedibile dal cliente.
  - Google (Business Profile/Calendar) — USA.
  - Stripe — USA/UE secondo configurazione; i dati di pagamento non transitano
    dal Servizio (solo identificativi).
  - Supabase — hosting DB: credenziali di progetto attuale su AWS `eu-central-1`
    (region EU, potenzialmente numero EU 1). Confermare la region di ciascun
    progetto e l'eventuale DPA Supabase sottoscritto.
  - Sentry — USA/UE secondo configurazione; attivo solo se configurato.
  - SMTP provider, Airtable, Softr — secondo configurazioni.
- **Rischio.** Affermazioni generiche ("SCC e/o DPF come disponibili") sono
  non verificabili: il legale deve ottenere i documenti contrattuali dei
  fornitori o istruire il blocco di region non conformi.

### 3.3 AI Act (DPA §10, ToS §6.3)
- **Stato.** Il sistema comunica di essere IA al primo contatto (art. 50(1)),
  con opzione HITL ("OPERATORE"). È un sistema di IA standalone, non
  classificato high-risk in base alla finalità dichiarata (assistente di
  messaggistica); nessuna obbligazione sistematica di registrazione EU AI Act
  emergente per questa categoria, salvo valutazioni specifiche.
- **Da validare:** (a) correttezza della classificazione; (b) obblighi
  residui eventuali per utenti istituzionali o altri canali (DPA §10.2);
  (c) obblighi di trasparenza/formazione per il personale del Titolare che
  riceve le escalation HITL; (d) sviluppo futuro di funzionalità come recensioni
  generate o analisi di sentiment che potrebbero cambiare la classificazione.

## 4. Item operativi "parked" con implicazioni legali

1. **Disclosure mark-before-send** (ledger SDD Task 4/5, PARKED). La disclosure
   è marcata come inviata prima che l'invio avvenga effettivamente: in caso di
   fallimento di `_send_ai_reply` la disclosure risulta inviata senza esserlo.
   Rischio legale: contatto che riceve risposta IA senza disclosure (violazione
   art. 50(1) "una tantum"). **Azioni:** audit log `ai_disclosure_undelivered`
   in caso di fallimento; quindi eventuale retry/disclosure al contatto
   successivo. Indice di rischio basso (invio fallito = contatto non vede
   nemmeno la risposta).
2. **OPERATORE vs organizzazione sospesa** (ledger Task 5, by design). Il ramo
   OPERATORE viene processato prima del gate "org sospesa": un contatto può
   ottenere risposta "Ti passo una persona dello staff" anche da un'organizzazione
   con fatturazione sospesa. Valutare se ciò configuri erogazione di servizio a
   cliente non pagante. By design per la spec (§6); decisione commerciale.

## 5. Documenti ancora assenti / da decidere

- **Registro dei trattamenti (art. 30 GDPR):** non redatto; obbligo del
  Titolare (Cliente) e del Responsabile (Fornitore) separatamente. Da
  predisporre per il Fornitore prima del lancio.
- **DPA bilingue:** la versione italiana è autorevole; la rotta `/api/gdpr/dpa`
  resta in inglese (allineata ai fatti). Decidere se il cliente debba ricevere
  la versione italiana autorevole (es. allegandola alla sottoscrizione).
- **Notifica/autorizzazione dei sub-responsabili ai Titolari:** DPA §6.1
  prevede obbligo di informazione con opposizione; definire il canale (email
  in-app) e la procedura.
- **Valutazione d'impatto (DPIA):** valutare se richiesta per l'uso del canale
  WhatsApp/IA con dati di soggetti terzi, considerata anche la posizione del
  Garante sui chatbot (caso OpenAI/CA 2023).
- **ToS/Informativa:** bozze redatte (`docs/superpowers/legal/`): vanno
  convalidate (punti `[REV]`) e tradotte almeno in inglese se il servizio è
  offerto a clienti non italiani.

## 6. Prima del lancio a clienti reali (checklist minima)

- [ ] Società costituita / soggetto giuridico definito; segnaposto compilati
- [ ] Review legale di DPA, ToS, Informativa; `[REV]` risolti
- [ ] Strumenti di trasferimento confermati con i fornitori (DPA §6.3)
- [ ] Decisione su base giuridica dei messaggi proattivi (DPA §4.2/ePrivacy)
- [ ] Registro dei trattamenti Fornitore (art. 30 GDPR)
- [ ] Rimozione di ogni residuo placeholder (nessun `dpo@example.com` nell'HTML)
- [ ] Triage item operativi parked (§4)