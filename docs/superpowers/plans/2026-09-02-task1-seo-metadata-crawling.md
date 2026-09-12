# Task 1: SEO On-Page, Metadata, Headings e Coerenza Crawling — Piano di Implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ottimizzare metadati SEO, title tag, open graph, dati strutturati Schema.org JSON-LD, gerarchia degli heading e pulizia della sitemap XML per la landing page di Melpis senza alterare il design visivo né le funzionalità esistenti.

**Architecture:** Modifiche mirate a `web/landing/index.html` (head metadati, JSON-LD `@graph`, H1 e gerarchia H2) e `web/landing/sitemap.xml` (rimozione URL non indicizzabili contrassegnati da noindex). Validazione tramite syntax check e test di parsing JSON-LD.

**Tech Stack:** HTML5 semantico, Schema.org (JSON-LD), XML Sitemap standard, Node.js (`node --check`).

**Spec:** Risoluzione delle problematiche SEO on-page emerse nell'audit, allineamento search intent B2B per attività locali/PMI italiane, rispetto del pricing confermato a 29/69/149 € e trial di 7 giorni.

## Global Constraints
- Mantenere il pricing attuale: Essenziale 29 €/mese, Crescita 69 €/mese, Scala 149 €/mese.
- Mantenere il periodo di prova gratuita a 7 giorni senza carta di credito richiesta.
- Non modificare il layout grafico o le classi CSS esistenti.
- Non introdurre dipendenze esterne (zero CDN, zero librerie JS terze).
- Mantenere la compatibilità con il CSP rigoroso definito in `web/security-headers.conf`.
- Rimuovere da `sitemap.xml` le pagine con `noindex` (`/privacy/`, `/termini/`, `/cookie/`) per eliminare gli errori di crawling in Search Console.

---

### Task 1.1: Ottimizzazione Head Metadati, Open Graph e Twitter Cards

**Files:**
- Modify: `web/landing/index.html:1-25`

**Interfaces:**
- Input: Metadati attuali (title generico, description prolissa, mancanza twitter tags).
- Output: `<title>`, `<meta name="description">`, `<meta name="robots">`, Open Graph completi e Twitter Cards allineati all'intento di ricerca.

- [x] **Step 1: Modificare il blocco `<head>` in `web/landing/index.html`**
Aggiornare i tag `<title>`, `<meta name="description">`, aggiungere `<meta name="robots" content="index, follow">`, ed espandere i tag Twitter.

- [x] **Step 2: Verifica manuale del markup HTML dei metadati**
Verificare che i tag non presentino doppi apici non chiusi o caratteri speciali non codificati.

---

### Task 1.2: Implementazione Dati Strutturati Schema.org JSON-LD (@graph)

**Files:**
- Modify: `web/landing/index.html:26-42`

**Interfaces:**
- Input: Vecchio schema `SoftwareApplication` incompleto con prezzi isolati.
- Output: Schema composito `@graph` contenente `Organization`, `WebSite`, `SoftwareApplication` (con offerte 29/69/149 €) e `FAQPage` (con le 5 domande attuali).

- [x] **Step 1: Creare il blocco JSON-LD completo in `web/landing/index.html`**
Sostituire il tag `<script type="application/ld+json">` esistente con il blocco unificato `@graph`.

- [x] **Step 2: Validare la sintassi del JSON estratto**
Eseguire un comando per validare che il blocco JSON-LD sia sintatticamente corretto (`JSON.parse`).

---

### Task 1.3: Ottimizzazione H1 della Hero e Normalizzazione Gerarchia Heading

**Files:**
- Modify: `web/landing/index.html:298-340`

**Interfaces:**
- Input: H1 attuale generico (*"Assistenti AI per tutte le conversazioni dei tuoi clienti"*), mancanza di H2 che introduca la sezione `#panoramica`.
- Output: H1 mirato su WhatsApp Business e prenotazioni, gerarchia heading H1 -> H2 -> H3 continua e accessibile per crawler e screen reader.

- [x] **Step 1: Aggiornare H1 e sottotitolo nella Hero (`hero-text-block`)**
In `web/landing/index.html`:
```html
<h1 class="hero-headline">Meno messaggi da gestire. Più tempo per far crescere la tua attività.</h1>
<p class="hero-subtitle">Melpis è il tuo assistente AI per WhatsApp, Instagram e i canali di contatto della tua attività. Risponde alle richieste dei clienti, organizza le prenotazioni e automatizza il lavoro ripetitivo secondo le tue regole.</p>
```

- [x] **Step 2: Aggiungere un H2 di sezione accessibile all'inizio di `#panoramica`**
Subito dopo `<section class="narrative-journey-section" id="panoramica">`:
Inserire:
```html
<h2 class="sr-only">Come Melpis automatizza le conversazioni della tua attività</h2>
```

---

### Task 1.4: Pulizia di Sitemap XML (Risoluzione Conflitto Noindex)

**Files:**
- Modify: `web/landing/sitemap.xml`

**Interfaces:**
- Input: Sitemap con `/privacy/`, `/termini/`, `/cookie/` che contengono `noindex`.
- Output: Sitemap valida contenente esclusivamente gli URL pubblici indicizzabili.

- [x] **Step 1: Aggiornare `web/landing/sitemap.xml`**
Rimuovere gli URL legali dotati di `noindex`.

- [x] **Step 2: Verificare la rispondenza di robots.txt**
Verificare che `web/landing/robots.txt` punti correttamente a `https://melpis.it/sitemap.xml`.

---

### Verification and Test Plan

- [x] **Verifica 1: Controllo sintassi JavaScript/Node**
Eseguire `node --check web/landing/app.js` per garantire zero regressioni.

- [x] **Verifica 2: Estrazione e validazione JSON-LD**
Eseguire uno script Node rapido per fare il parsing del JSON-LD in `web/landing/index.html` e verificare l'assenza di errori di sintassi.

- [x] **Verifica 3: Controllo presenza tag critici**
Verificare via grep che `og:title`, `twitter:card`, `SoftwareApplication`, `FAQPage`, e l'H1 aggiornato siano presenti nel markup.

- [x] **Verifica 4: Validità XML della sitemap**
Verificare che `web/landing/sitemap.xml` sia un file XML ben formato senza tag aperti.
