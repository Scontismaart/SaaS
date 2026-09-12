# Task 5: Pagina Prezzi Dedicata (`/prezzi/`) con Calcolatore ROI & Dettaglio Piani — Piano di Implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare la pagina prezzi dedicata ad alta conversione (`/prezzi/`) con presentazione trasparente dei 3 piani (Essenziale 29€, Crescita 69€, Scala 149€), calcolatore ROI interattivo, tabella comparativa delle funzionalità, FAQ commerciali, dati strutturati Schema.org (`Product`, `AggregateOffer`, `FAQPage`), configurazione Nginx/Docker e indicizzazione nella Sitemap XML.

**Architecture:** Creazione del file `web/landing/prezzi/index.html` con calcolatore interattivo Vanilla JS inline o autonomo, tabella comparativa responsive, integrazione nel routing di `web/nginx.conf`, aggiornamento di `web/Dockerfile` e `web/landing/sitemap.xml`.

**Tech Stack:** HTML5, CSS3, JavaScript (Vanilla ES6), Schema.org JSON-LD (@graph), Nginx.

**Spec:** Rispetto assoluto delle regole utente sul pricing: Essenziale 29€, Crescita 69€, Scala 149€; 7 giorni di prova gratuita, nessuna carta di credito, nessun rinnovo automatico; trasparenza e prudenza su formule e claim.

## Global Constraints
- Piani rigorosamente allineati: 29€, 69€, 149€.
- 7 giorni di prova gratuita senza carta di credito chiaramente esplicitati.
- Zero claim gonfiati o ingannevoli nel calcolatore ROI (formule visibili ed euristiche prudenti).
- Accessibilità WCAG 2.1 AA (contrasto, focus ring e label sugli input range dello slider).

---

### Task 5.1: Creazione della Pagina `web/landing/prezzi/index.html`

**Files:**
- Create: `web/landing/prezzi/index.html`

- [x] **Step 1: Documento HTML, SEO on-page e Schema.org JSON-LD**
  - `<title>Prezzi e Piani · Melpis Assistente AI | Prova 7 Giorni Senza Carta</title>`
  - Canonical: `https://melpis.it/prezzi/`
  - JSON-LD `@graph`:
    - `BreadcrumbList` (Home -> Prezzi)
    - `Product` con `AggregateOffer` (lowPrice 29.00, highPrice 149.00 EUR)
    - `FAQPage` con 6 domande commerciali su fatturazione, superamento soglie, cancellazione e trial.

- [x] **Step 2: Struttura visiva, Schede Piani e Calcolatore ROI**
  - Navbar con link di ritorno alla home e sezioni.
  - Hero Section con focus su trasparenza e prova senza rischi.
  - Le 3 Card Pricing (Essenziale 29€, Crescita 69€ con badge Consigliato, Scala 149€).
  - Sezione Calcolatore ROI Interattivo:
    - Slider 1: Richieste giornaliere ricevute (10 - 150).
    - Slider 2: Valore medio prenotazione / cliente (15€ - 150€).
    - Risultati calcolati in tempo reale: ore risparmiate/mese, stima richieste salvate fuori orario, piano consigliato.
  - Tabella Comparativa Completa delle funzionalità (Canali, Messaggi, Knowledge Base, Calendario, Presa in carico staff, Assistenza).
  - FAQ commerciali dettagliate.
  - Final CTA Box e Footer globale.

---

### Task 5.2: Aggiornamento Routing Nginx e Dockerfile

**Files:**
- Modify: `web/nginx.conf`
- Modify: `web/Dockerfile`

- [x] **Step 1: Aggiungere routing per `/prezzi/` in `web/nginx.conf`**
  ```nginx
  location = /prezzi     { return 301 /prezzi/; }
  location = /prezzi/    { try_files /prezzi/index.html =404; }
  ```

- [x] **Step 2: Aggiornare `web/Dockerfile` per copiare `landing/prezzi/` nel docroot**
  ```dockerfile
  COPY landing/prezzi/ /usr/share/nginx/html/prezzi/
  ```

---

### Task 5.3: Aggiornamento della Sitemap XML

**Files:**
- Modify: `web/landing/sitemap.xml`

- [x] **Step 1: Aggiungere l'URL `https://melpis.it/prezzi/` nella Sitemap**
  Con `priority` 0.9 e `changefreq` weekly.

---

### Verification and Test Plan

- [x] **Verifica 1: Parsing e validazione sintassi JSON-LD della nuova pagina prezzi**
- [x] **Verifica 2: Verifica corrispondenza FAQ HTML ed entità FAQPage in JSON-LD**
- [x] **Verifica 3: Test del Calcolatore ROI (slider reattivi, formule corrette, nessuna divisione per zero)**
- [x] **Verifica 4: Validità XML di `sitemap.xml`**
- [x] **Verifica 5: Verifica configurazione statica in `web/nginx.conf` e `web/Dockerfile`**
