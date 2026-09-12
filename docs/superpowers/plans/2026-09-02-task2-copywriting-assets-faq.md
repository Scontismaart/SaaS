# Task 2: Riorganizzazione Copy, Value Proposition & Integrazione Asset Reali — Piano di Implementazione (Revisionato)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare i tecnicismi astratti dal copy della landing page, chiarire con onestà tecnica l'integrazione con WhatsApp Cloud API e Instagram, sostituire le promesse assolute sull'AI con spiegazioni pratiche su regole e coinvolgimento dello staff, espandere le FAQ a 8 domande reali senza claim indimostrati e sincronizzare markup HTML e JSON-LD.

**Architecture:** Modifiche mirate su `web/landing/index.html` (Satellite 3, Coworker Showcase, Conoscenza Aziendale, Final CTA, FAQ e JSON-LD) e `web/landing/app.js` (etichette dinamiche dei settori e messaggi dell'animazione di upload).

**Tech Stack:** HTML5, Vanilla JavaScript, CSS3 tokens, Schema.org (JSON-LD).

**Spec:** Rispetto dei vincoli di accuratezza tecnica (Meta Cloud API, assenza di claim deterministici assoluti, prova 7 giorni senza carta senza rinnovo automatico, claim prudente "in pochi passaggi").

## Global Constraints
- Prezzi confermati: 29 € / 69 € / 149 € con 7 giorni di prova gratuita senza carta di credito.
- Nessuna promessa di "AI senza allucinazioni assolute": spiegare invece regole, limiti e passaggio all'operatore.
- Spiegare con chiarezza che le chat WhatsApp su Meta Cloud API si gestiscono dalla Inbox web di Melpis.
- Usare la formulazione prudente per la Final CTA ("Configura Melpis in pochi passaggi e prova il servizio per 7 giorni senza carta.").
- Corrispondenza 1:1 tra le 8 FAQ visibili in HTML e i nodi Schema.org `FAQPage` in JSON-LD.
- Nessuna dipendenza o libreria esterna.

---

### Task 2.1: Satellite 3 e Coworker Showcase

**Files:**
- Modify: `web/landing/index.html`
- Modify: `web/landing/app.js`

- [x] **Step 1: Aggiornare Satellite 3 (regole di settore) in `web/landing/index.html` e `web/landing/app.js`**
  - Sostituire `"Fail-Closed clinico per urgenze"` con `"Passaggio operatore per urgenze"`.
  - In `app.js`, aggiornare il dizionario `sectorData.medici` con `"Passaggio operatore per urgenze"`.

- [x] **Step 2: Aggiornare Coworker Showcase in `web/landing/index.html`**
  - Titolo: `Il tuo collaboratore per WhatsApp, Instagram e Google Calendar.` (verificato che le 3 integrazioni sono implementate nel backend).
  - Sottotitolo: `Risponde alle richieste dei clienti in tempo reale, sincronizza gli appuntamenti direttamente in agenda ed elabora le recensioni. Con controllo umano istantaneo in un click.`

---

### Task 2.2: Conoscenza Aziendale & Regole

**Files:**
- Modify: `web/landing/index.html`
- Modify: `web/landing/app.js`

- [x] **Step 1: Riscrivere il modulo Conoscenza in `web/landing/index.html`**
  - Eyebrow: `CONOSCENZA AZIENDALE & REGOLE`
  - Titolo: `Risponde solo a quello che sai davvero.<br>Mai a caso.`
  - Descrizione: `Melpis genera risposte basate sulle informazioni che fornisci, come PDF, menu, listini e regole della tua attività. Quando non trova una risposta sicura o la richiesta esce dai limiti impostati, può avvisare lo staff invece di rispondere in modo arbitrario.`
  - Bullets:
    1. `Supporto per PDF, menu del giorno, listini prezzi e orari di apertura`
    2. `Riconoscimento di servizi, orari e condizioni impostate dall'attività`
    3. `Avviso cortese e notifica allo staff quando serve un accordo personalizzato`

- [x] **Step 2: Aggiornare il mock di upload in `web/landing/app.js`**
  - `"Estrazione vettoriale RAG..."` -> `"Lettura orari, servizi e listino..."`
  - `"Validazione guardrail e limiti..."` -> `"Applicazione regole e limiti del locale..."`
  - `"Pronto & sincronizzato"` -> `"Pronto per rispondere ai clienti"`

---

### Task 2.3: FAQ a 8 Domande Realistiche e Sincronizzazione JSON-LD

**Files:**
- Modify: `web/landing/index.html`

- [x] **Step 1: Aggiornare le 8 domande e risposte in `<div class="faq-list">` in `web/landing/index.html`**
  1. *Ho bisogno di un nuovo numero di telefono per usare Melpis?*
  2. *Come funziona la gestione delle chat e posso usare l'app dal telefono?*
  3. *Cosa succede se l'assistente non trova una risposta o riceve una richiesta complessa?*
  4. *Quanto tempo serve per configurare il servizio?*
  5. *Come funziona la prova gratuita di 7 giorni?*
  6. *I dati dei clienti sono al sicuro e conformi al GDPR?*
  7. *Posso personalizzare il tono di voce e le regole di risposta?*
  8. *Posso disdire l'abbonamento in qualsiasi momento?*

- [x] **Step 2: Aggiornare identicamente lo schema JSON-LD `FAQPage` in `<head>` con le 8 domande**

---

### Task 2.4: Final CTA Box

**Files:**
- Modify: `web/landing/index.html`

- [x] **Step 1: Aggiornare i testi della Final CTA in `web/landing/index.html`**
  - Titolo: `Meno lavoro manuale ogni giorno.<br>Più spazio per la tua attività.`
  - Sottotitolo: `Configura Melpis in pochi passaggi e prova il servizio per 7 giorni senza carta.`

---

### Verification and Test Plan

- [x] **Verifica 1: Controllo sintassi JS `web/landing/app.js` con `node --check`**
- [x] **Verifica 2: Test script di parità esatta tra DOM FAQ (8 nodi) e JSON-LD FAQ (8 nodi)**
- [x] **Verifica 3: Verifica assenza claim assoluti e verifica presenza claim prudenti**
