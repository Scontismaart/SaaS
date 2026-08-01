# Sempre — L'assistente WhatsApp che non stacca mai

## Cos'è Sempre

Sempre è un assistente AI per WhatsApp Business che risponde automaticamente ai clienti, gestisce prenotazioni e appuntamenti, e passa le richieste complesse al personale umano. Progettato per attività di servizio (ristoranti, saloni, bar, studi professionali, spa) che non possono stare attaccate al telefono mentre lavorano.

---

## Come funziona

1. **Colleghi il tuo WhatsApp Business** — pochi clic, nessuna configurazione tecnica.
2. **Personalizzi le regole** — orari, menu, preferenze, lingua dell'attività.
3. **L'AI lavora da sola** — risponde, conferma, organizza. 24/7.
4. **Quando serve, passa all'umano** — richieste complesse o sensibili vengono girate a un operatore con tutto il contesto già pronto.

---

## Cosa può fare

### Risposte automatiche AI
- Risponde istantaneamente su WhatsApp a ogni cliente
- Comprende la lingua del cliente (20+ lingue supportate)
- Usa il profilo dell'attività per rispondere in modo coerente (tono, menu, orari, policy)
- Mantiene la cronologia della conversazione per dare continuità

### Gestione prenotazioni
- Il cliente prenota via WhatsApp, l'AI verifica disponibilità e conferma
- Tracciamento coperti per fascia oraria con semaforo (verde/giallo/rosso)
- Crea, modifica e cancella prenotazioni da dashboard
- Impostazioni flessibili: capienze orarie, fasce orarie, coperti massimi per slot
- Doppio binario: demo locale (senza database) o PostgreSQL con async

### Human-in-the-loop (Shared Inbox)
- Se l'AI non sa rispondere o la richiesta è delicata, passa automaticamente a un operatore
- Sistema di ticket: claim, release, risolvi
- Risposta manuale via Meta Cloud API con supporto idempotency (evita doppie risposte)
- Ogni ticket include il contesto completo della conversazione

### Gestione recensioni
- Genera automaticamente bozze di risposta per recensioni (Google, TripAdvisor)
- Analisi del sentiment (positivo, neutro, negativo)
- Rilevamento recensioni che richiedono risposta urgente
- Categorizzazione automatica della recensione

### Knowledge Base (documenti & RAG)
- Carica documenti (menu, lista allergeni, carta vini, policy) tramite upload o testo
- L'AI risponde alle domande dei clienti basandosi solo sui documenti caricati
- Supporto per estrazione testo da file PDF, Word, e immagini
- Ricerca semantica con pgvector (PostgreSQL) o ChromaDB

### Report & Dashboard
- Dashboard in tempo reale con tutti gli eventi (messaggi, recensioni, prenotazioni)
- Filtro eventi prioritari: alta/media/bassa priorità con motore di calcolo
- Report giornaliero generato dall'AI con riepilogo dell'attività
- Storico completo delle conversazioni

### Fatturazione & Piani (Stripe)
- Integrazione Stripe per pagamenti ricorrenti
- Creazione sessioni di checkout e portale clienti
- Webhook Stripe per aggiornamento automatico abbonamenti
- Rate limiting per tenant e per utente

### Sicurezza & Compliance
- Autenticazione via JWT (Supabase Auth) o API Key
- Controllo ruoli: owner, manager, staff, service_role
- Organizzazione multi-tenant con isolamento dati
- Audit logging di ogni azione sensibile
- GDPR: diritto all'oblio con cancellazione dati a cascata
- Crittografia dati in transito e a riposo
- Rate limiting configurabile

---

## Piani e costi

| Piano | Prezzo | Messaggi/mese | Utenti | Funzionalità |
|-------|--------|---------------|--------|-------------|
| **Starter** | **€49/mese** | 500 | 1 | AI base, supporto 24/7 |
| **Pro** | **€99/mese** | 2.000 | 3 | AI avanzata, gestione recensioni |
| **Business** | **€199/mese** | Illimitati | Illimitati | RAG, integrazioni custom, account manager |

Tutti i piani includono:
- Prova gratuita di 7 giorni (nessuna carta richiesta)
- WhatsApp Business
- Supporto tecnico
- Attivazione in 3 minuti

---

## Tech Stack

| Componente | Tecnologia |
|-----------|-----------|
| Backend API | Python / FastAPI |
| AI / LLM | CrewAI + LiteLLM + OpenRouter |
| Database | PostgreSQL + asyncpg (pgvector per embedding) |
| Vector Store | pgvector (primario) o ChromaDB (fallback) |
| Messaggi | WhatsApp Cloud API (Meta) |
| Pagamenti | Stripe |
| Auth | Supabase Auth (JWT / RS256) |
| Email | SMTP (per notifiche escalation) |
| Documenti | Estrazione testo multi-formato (PDF, DOCX, immagini) |
| Ricerca semantica | Embedding + cosine similarity |
| Scheduler | Threading + APScheduler |

---

## Per chi è

- **Ristoranti, pizzerie, bar** — gestione tavoli e prenotazioni
- **Saloni, centri estetici, spa** — appuntamenti clienti
- **Studi professionali** — consulenze e appuntamenti
- **Palestre, centri benessere** — gestione clienti e classi
- **Qualsiasi attività** che riceve prenotazioni via WhatsApp

---

## Benefici

- **Mai più una prenotazione persa** mentre sei impegnato con un cliente
- **Risposta in meno di 10 secondi**, 24 ore su 24
- **Zero doppie prenotazioni** — calendario aggiornato in tempo reale
- **Clienti più soddisfatti** — nessuna attesa, nessun messaggio ignorato
- **Il personale si concentra sul servizio**, non sul telefono
- **Attivazione immediata** — funziona con il tuo WhatsApp Business esistente
- **Nessun vincolo** — disdici quando vuoi

---

## Demo

Sempre funziona anche senza database in modalità demo. Collegando un database PostgreSQL si attivano tutte le funzionalità multi-tenant, webhook WhatsApp reali, e pagamenti Stripe.
