# Task 4: Topical Authority — Pagina Verticale di Settore (`/settori/ristoranti/`) — Piano di Implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare la prima landing page verticale ad alta intenzione di ricerca dedicata a Ristoranti e Pizzerie (`/settori/ristoranti/`), completa di copy benefit-first, markup semantico coerente con il design system Lemni, dati strutturati Schema.org (`BreadcrumbList`, `SoftwareApplication`, `FAQPage`), configurazione di routing Nginx/Docker e indicizzazione nella Sitemap XML.

**Architecture:** Creazione del file `web/landing/settori/ristoranti/index.html` con riferimenti agli asset globali (`/style.css`, `/logo.webp`, `/fonts/`). Aggiornamento di `web/nginx.conf`, `web/Dockerfile` e `web/landing/sitemap.xml`.

**Tech Stack:** HTML5, CSS3 (tokens esistenti), Schema.org JSON-LD (@graph), Nginx.

**Spec:** Applicazione delle skill `copywriting`, `cro`, `site-architecture`, `schema` e `ai-seo`: massimizzazione della rilevanza tematica per "assistente whatsapp ristoranti", "prenotazioni whatsapp ristorante", "riduzione no-show ristoranti".

## Global Constraints
- Nessuna alterazione al pricing: Essenziale 29 €/mese, Crescita 69 €/mese, Scala 149 €/mese, 7 giorni di prova senza carta.
- Claim prudente: "pochi passaggi" per la configurazione, trasparenza sulla Meta Cloud API.
- Zero dipendenze esterne o librerie CDN (stile e font rigorosamente self-hosted).
- `sitemap.xml` aggiornata con validità XML impeccabile.

---

### Task 4.1: Creazione della Pagina Verticale `web/landing/settori/ristoranti/index.html`

**Files:**
- Create: `web/landing/settori/ristoranti/index.html`

- [x] **Step 1: Creazione del documento con `<head>`, SEO on-page e Schema.org JSON-LD**
  - `<title>Melpis per Ristoranti · Assistente WhatsApp per Prenotazioni e Coperti | Prova 7 giorni</title>`
  - Canonical: `https://melpis.it/settori/ristoranti/`
  - Open Graph e Twitter Cards verticali.
  - JSON-LD composito `@graph`:
    - `BreadcrumbList` (Home -> Settori -> Ristoranti e Pizzerie)
    - `SoftwareApplication` specializzata per la ristorazione
    - `FAQPage` con 5 domande specifiche per ristoratori (gestione turni, no-show, intolleranze, disdetta e prova 7 giorni).

- [x] **Step 2: Struttura visiva, Hero e Benefici specifici per Ristoratori**
  - Navbar con link alla home e sezioni della pagina.
  - Breadcrumb visibile accessibile.
  - Hero Section:
    - Tag: `Verticale Ristoranti & Pizzerie`
    - H1: `Riempi i tavoli del tuo ristorante.<br>Senza passare il servizio al telefono.`
    - Subtitle: `Melpis gestisce le richieste dei clienti su WhatsApp anche nei momenti di punta. Conferma i coperti secondo i tuoi turni, risponde alle domande su menu e allergeni e sincronizza le prenotazioni sul tuo Google Calendar.`
    - CTA primarie e badge rassicuranti (7 giorni gratis, nessuna carta).
  - Mockup dimostrativo di prenotazione WhatsApp:
    - Richiesta coperti + intolleranza alimentare + verifica capienza + conferma con nota oraria.
  - Tre Card Vantaggi Concreti:
    1. *Zero chiamate perse durante il servizio*;
    2. *Controllo orari, turni serali e capienza della sala*;
    3. *Meno tavoli vuoti grazie ai promemoria automatici*.
  - Sezione "Come Funziona in 3 Semplici Passaggi per il tuo Locale".
  - Sezione FAQ Verticale per la Ristorazione (5 domande).
  - Final CTA Box e Footer completo.

---

### Task 4.2: Aggiornamento Routing Nginx e Dockerfile

**Files:**
- Modify: `web/nginx.conf`
- Modify: `web/Dockerfile`

- [x] **Step 1: Aggiungere le direttive location per `/settori/ristoranti/` in `web/nginx.conf`**
  ```nginx
  location = /settori/ristoranti     { return 301 /settori/ristoranti/; }
  location = /settori/ristoranti/    { try_files /settori/ristoranti/index.html =404; }
  ```

- [x] **Step 2: Aggiornare `web/Dockerfile` per copiare la directory `settori/` nel docroot**
  ```dockerfile
  COPY landing/settori/ /usr/share/nginx/html/settori/
  ```

---

### Task 4.3: Aggiornamento della Sitemap XML

**Files:**
- Modify: `web/landing/sitemap.xml`

- [x] **Step 1: Aggiungere l'URL `https://melpis.it/settori/ristoranti/` nella Sitemap**
  Con `priority` 0.8 e `changefreq` weekly.

---

### Verification and Test Plan

- [x] **Verifica 1: Parsing e validazione sintassi JSON-LD della nuova pagina verticale**
- [x] **Verifica 2: Verifica corrispondenza FAQ HTML ed entità FAQPage in JSON-LD**
- [x] **Verifica 3: Validità XML di `sitemap.xml`**
- [x] **Verifica 4: Verifica configurazione statica in `web/nginx.conf` e `web/Dockerfile`**
