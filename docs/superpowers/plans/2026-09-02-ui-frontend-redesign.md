# Redesign UI & Front-End: Pulsanti, Piano & Abbonamento e Sicurezza - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevare la qualità visiva e l'esperienza d'uso (haptic UX) della dashboard attraverso: 1) pulsanti tattili e rifiniti in Prenotazioni, Conoscenza e Impostazioni con bottoni di eliminazione a testo esplicito; 2) redesign enterprise della sezione Piano & Abbonamento con badge "Consigliato", card Doppelrand e feature list; 3) redesign della sezione Sicurezza con schede credenziali moderne e card di sicurezza crittografica.

**Architecture:** Sistema CSS design-engineering coerente ispirato a `emil-design-eng`, `make-interfaces-feel-better` e `high-end-visual-design`: feedback tattile (`:active scale(0.97)`), curve cubic-bezier personalizzate, raggio concentrico ottico, numeri tabulari e pulsanti secondari/distruttivi soft con testo esplicito.

**Tech Stack:** HTML5, CSS3 nativo con CSS Custom Properties (Light/Dark mode compliance), Vanilla JavaScript ES6+.

**Spec:** Requisiti utente:
1. Migliorare pulsanti in Prenotazioni, Conoscenza e Impostazioni.
2. Sostituire le "✕" con bottoni ad azione esplicita ("Elimina").
3. Ridisegnare la sezione Piano e Abbonamento aggiungendo il badge "Consigliato" al piano Crescita (€69/mese).
4. Ridisegnare la sezione Sicurezza dell'account.

---

## Global Constraints
- Tutte le modifiche CSS devono supportare sia il tema chiaro (`:root` / `html[data-theme="light"]`) sia il tema scuro (`html[data-theme="dark"]`).
- Nessun `transition: all`: specificare sempre le proprietà animate (`transform, background-color, border-color, box-shadow, color`).
- Tutte le animazioni interattive devono usare curve cubic-bezier (`cubic-bezier(0.16, 1, 0.3, 1)` o `cubic-bezier(0.23, 1, 0.32, 1)`) con durata 150-200ms.
- Hit area minima per tutti i pulsanti e controlli interattivi >= 40px (desktop e mobile).
- Mantenere la piena compatibilità con FullCalendar e le funzioni JS esistenti in `web/app.js`.

---

### Task 1: Sistema Globale di Pulsanti Tattili e Segmented Controls (CSS)

**Files:**
- Modify: `web/style.css`
- Test: Verifica rendering sintassi CSS con script Node / browser.

**Interfaces:**
- Consumes: CSS tokens (`--accent`, `--ink`, `--card-bg`, `--card-border`, `--radius-sm`, `--radius-md`).
- Produces: Classi pulsanti riutilizzabili con haptic feedback (`.review-analyze`, `.report-refresh`, `.btn-danger`, `.kb-btn-delete`, `.booking-calendar-views`).

- [ ] **Step 1: Aggiornare le classi base dei pulsanti primari e secondari in `web/style.css`**
  - Aggiungere `:active { transform: scale(0.97); }` a `.review-analyze`, `.report-refresh`, `.btn-danger`, `.inbox-quick-action`.
  - Impostare transizioni mirate con `cubic-bezier(0.16, 1, 0.3, 1)` a 160ms.
  - Aggiungere `box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16)` sui pulsanti primari scuri per profondità ottica.

- [ ] **Step 2: Aggiungere la classe `.kb-btn-delete` per eliminazioni a testo esplicito**
  - Introdurre `.kb-btn-delete`:
    - Layout: `display: inline-flex; align-items: center; gap: 5px;`
    - Padding: `5px 12px;`
    - Bordo: `1px solid var(--card-border);`
    - Hover: sfondo `rgba(220, 38, 38, 0.08)`, bordo `rgba(220, 38, 38, 0.35)`, testo `#dc2626`.
    - Active: `transform: scale(0.96);`.

- [ ] **Step 3: Ridisegnare lo switch viste di Prenotazioni (Segmented Pill)**
  - Aggiornare `.booking-calendar-views`:
    - Contenitore a capsula con sfondo attenuato (`background: var(--chip-bg)`), padding 4px e bordo sottile.
    - Pulsanti interni con `border-radius: 999px`, font-size 0.82rem, font-weight 600.
    - Stato attivo con sfondo bianco/elevated, ombra sottile morbida (`0 1px 3px rgba(0,0,0,0.08)`), colore `--ink`.

---

### Task 2: Pulsanti a Testo Esplicito in Conoscenza e Prenotazioni (HTML & JS)

**Files:**
- Modify: `web/index.html` (FAQ, Web & Documenti, Tabelle)
- Modify: `web/app.js` (`_creaRigaServizio`, `renderFAQ`, `renderWebPages`)

**Interfaces:**
- Consumes: Event listeners per cancellazione servizi, FAQ e link web.
- Produces: Markup con `<button type="button" class="kb-btn-delete">Elimina</button>`.

- [ ] **Step 1: Aggiornare `_creaRigaServizio` in `web/app.js`**
  - Sostituire `removeBtn.textContent = "✕"` con classe `kb-btn-delete` e icona cestino + etichetta "Elimina".

- [ ] **Step 2: Aggiornare il rendering delle FAQ e delle Pagine Web in `web/app.js`**
  - Nei template di `renderFAQ` e `renderWebPages`, sostituire il pulsante cancella "✕" con `.kb-btn-delete` completo di etichetta "Elimina".

- [ ] **Step 3: Aggiornare i pulsanti d'azione del tester e dei form di Conoscenza in `web/index.html`**
  - Aggiornare `#kb-faq-save-btn`, `#kb-faq-cancel-btn`, `#kb-salva-dati-btn`, `#doc-chiedi-btn` con icone e gerarchia visiva chiara.

---

### Task 3: Redesign Enterprise della Sezione "Piano e Abbonamento" (HTML, CSS & JS)

**Files:**
- Modify: `web/index.html` (`data-settings-panel="piano"`)
- Modify: `web/style.css` (`.account-summary`, `.account-plans`, `.account-plan-card`)
- Modify: `web/app.js` (`caricaAccount`, `ACCOUNT_PLANS`)

**Interfaces:**
- Consumes: `ACCOUNT_PLANS` array in `web/app.js` e API `/api/billing/subscription`.
- Produces: Griglia pricing rifinita con badge "Consigliato" su `pro`, feature list chiara e hero card del piano attivo.

- [ ] **Step 1: Aggiornare i dati del piano in `ACCOUNT_PLANS` in `web/app.js`**
  - Aggiungere lista vantaggi e highlight al piano Crescita (`popolare: true`).

- [ ] **Step 2: Aggiornare la generazione HTML delle card in `caricaAccount` in `web/app.js` con badge Consigliato e lista vantaggi**
  - Renderizzare il badge `Consigliato` (`<span class="account-badge-popolare">Consigliato</span>`) per `p.popolare`.
  - Includere la lista dei vantaggi con icona di spunta verde (`<ul class="account-plan-feat-list">`).

- [ ] **Step 3: Stili CSS avanzati per la sezione Abbonamento in `web/style.css` (Doppelrand, Pulse dot, hover lift)**
  - Hero card del piano attivo (`.account-summary`): bordo rifinito, gradiente soffuso di accento, visualizzazione dello stato vivo (`account-stato-pill`) con puntino luminoso (`animation: pulseDot 2s infinite`).
  - Card del piano raccomandato (`.account-plan-card.popolare`):
    - Elevazione Z-axis (`box-shadow: 0 8px 24px -4px rgba(0,0,0,0.08)`),
    - Bordo attivo `--accent`,
    - Badge "Consigliato" in alto con sfondo accento e testo a contrasto.
  - Hover state con leggero lift (`transform: translateY(-3px)`) e pulsante CTA primario invitante.

---

### Task 4: Redesign Sezione "Sicurezza Account" (HTML & CSS)

**Files:**
- Modify: `web/index.html` (`data-settings-panel="sicurezza"`)
- Modify: `web/style.css` (`.security-grid`, `.settings-security`)

**Interfaces:**
- Consumes: Form `#security-password-form` e `#security-email-form`.
- Produces: Layout a 2 card con Doppelrand, iconografia di sicurezza, requisiti chiari e scheda garanzia privacy/multi-tenant.

- [ ] **Step 1: Aggiornare il markup di Sicurezza in `web/index.html` con card distinte Password ed Email, più card informativa crittografia**
  - Suddividere in 2 schede distinte:
    1. **Card Chiavi di Accesso (Password)**: con icona lucchetto, requisiti visivi chiari ("Minimo 10 caratteri", "1 carattere speciale"), campi con focus ring e bottone "Aggiorna password".
    2. **Card Recapito Ufficiale (Email)**: con icona busta, campo email e bottone "Aggiorna email".
  - Aggiungere sotto una card informativa: **"Protezione e Crittografia Dati"** (Crittografia TLS in transito, hashing PBKDF2/Argon2 su database isolato tenant-by-tenant, zero-knowledge di password in chiaro).

- [ ] **Step 2: Stili CSS per le card di Sicurezza in `web/style.css` (badge icone, focus ring nitido, requisiti a pill)**
  - Definire `.security-card`: card con header dedicato, badge icona con cerchio soffuso (`background: rgba(var(--accent-rgb), 0.1)`).
  - Requisiti password stilizzati come micro-pill (`.security-req-badge`).
  - Input password/email con bordi netti, focus ring nitido `outline: 2px solid var(--accent)` e padding ergonomico.
  - Adattabilità mobile fluida (`grid-template-columns: 1fr` sotto i 768px).

---

### Task 5: Verifica, Collaudo Cross-Browser e Test di Regressione

**Files:**
- Test: `tests/core/test_configurazione_ai_e2e.py`
- Test: `tests/core/test_conoscenza_e2e.py`
- Test: `node -c web/app.js`

- [ ] **Step 1: Validare la sintassi JavaScript (`node -c web/app.js`)**
- [ ] **Step 2: Eseguire la suite di test pytest (100% verde)**
- [ ] **Step 3: Aggiornare il knowledge graph (`graphify update .`)**
