# Task 3: Ottimizzazione Performance, Eliminazione Loop JS e Accessibilità WCAG — Piano di Implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare l'esecuzione continua di loop e timer JS fuori dal viewport (Hero, Knowledge Base, HITL Simulator, Sync sequence) tramite `IntersectionObserver` e Page Visibility API per azzerare il consumo CPU in background, implementare focus ring `:focus-visible` WCAG AA, e rendere universale la gestione di `prefers-reduced-motion`.

**Architecture:** Modifica di `web/landing/app.js` per introdurre controller di ciclo di vita observer-driven (`observeAndControlLoop`) e ascoltatore `document.addEventListener('visibilitychange')`. Modifica di `web/landing/style.css` per introdurre un focus ring accessibile ad alto contrasto per tutti gli elementi interattivi e rafforzare il reset `prefers-reduced-motion`. Modifica di `web/landing/index.html` per aggiungere etichette `aria-label`, `aria-hidden` sugli elementi puramente decorativi e correggere il testo nel modal di registrazione.

**Tech Stack:** JavaScript (ES6 Vanilla), CSS3, WCAG 2.1 AA, DOM & IntersectionObserver / Page Visibility APIs.

**Spec:** Rispetto dei requisiti di efficienza energetica, zero regressioni funzionali e piena accessibilità da tastiera e screen reader.

## Global Constraints
- Nessuna libreria esterna (solo Vanilla JS e standard web API).
- Conservare intatto il comportamento visivo ed esperienziale quando le sezioni sono effettivamente visibili.
- Il checkout e i flussi modale esistenti non devono subire alterazioni logiche.
- `node --check web/landing/app.js` deve terminare con exit code 0.

---

### Task 3.1: Controllo Intelligente del Ciclo di Vita delle Animazioni JS (Stop Loop Off-Screen e Tab Nascosta)

**Files:**
- Modify: `web/landing/app.js:45-185` (Hero Assembly Loop)
- Modify: `web/landing/app.js:240-315` (HITL Simulator Loop)
- Modify: `web/landing/app.js:635-690` (Knowledge Base Upload Loop)
- Modify: `web/landing/app.js:690-760` (Sync & Review Typing Loop)

- [x] **Step 1: Creare un helper `createVisibilityController` o gestione observer per la Hero**
  - Quando la Hero (`.hero-stage` o `#hero`) esce dal viewport (`!isIntersecting`), cancellare i timeout pendenti (`timelineTimeouts`) e fermare il loop.
  - Quando rientra nel viewport, far ripartire la timeline o portarla al suo frame stabile.
  - Gestire `document.addEventListener('visibilitychange')`: se `document.hidden`, mettere in pausa tutti i timer; quando torna visibile, riprendere solo le animazioni degli elementi attualmente nel viewport.

- [x] **Step 2: Collegare l'upload loop di Knowledge Base a un `IntersectionObserver`**
  - Invece di avviare `setTimeout(runKbUploadCycle, 800)` unconditionally, osservare `.kb-block-wrap`.
  - Avviare il ciclo solo quando `.kb-block-wrap` è visibile.
  - Sospendere il timer quando scorre fuori dal viewport.

- [x] **Step 3: Rendere reversibili gli observer di HITL Simulator e Sync Automazioni**
  - Quando `.hitl-simulator-window` o `.sync-block-wrap` escono dal viewport, cancellare i timer ricorsivi pendenti per evitare calcoli inutili.

---

### Task 3.2: Accessibilità Globale da Tastiera e WCAG Focus Visible

**Files:**
- Modify: `web/landing/style.css`

- [x] **Step 1: Aggiungere regola `:focus-visible` ad alto contrasto per tutti gli elementi interattivi**
  - Aggiungere stile per `a:focus-visible`, `button:focus-visible`, `input:focus-visible`, `select:focus-visible`, `summary:focus-visible`:
    ```css
    a:focus-visible,
    button:focus-visible,
    input:focus-visible,
    select:focus-visible,
    summary:focus-visible {
        outline: 2px solid #22c55e;
        outline-offset: 3px;
    }
    ```
  - Verificare che il contrasto tra `#22c55e` e lo sfondo scuro `#0c0c11` rispetti il rapporto 3:1 (il verde `#22c55e` su `#0c0c11` ha un contrasto superiore a 8:1, superando brillantemente WCAG AAA per non-text contrast).

- [x] **Step 2: Rinforzare il reset globale `prefers-reduced-motion`**
  - Estendere il blocco `@media (prefers-reduced-motion: reduce)` in `style.css` per garantire che nessuna animazione o transizione forzata continui per utenti con sensibilità vestibolare.

---

### Task 3.3: Accessibilità DOM, ARIA Decorativi e Rifinitura Modal

**Files:**
- Modify: `web/landing/index.html`

- [x] **Step 1: Aggiungere `aria-hidden="true"` su decorazioni iconiche e simboliche**
  - Nelle card del Coworker Showcase (`.dash-mock-actions`, `.cw-dots`, `.cw-send-btn`).
  - Negli indicatori `+` dell'accordion FAQ (`.faq-icon`).

- [x] **Step 2: Aggiornare il claim nel modale di registrazione (`#signupModal`)**
  - In linea con il principio di prudenza approvato dall'utente, sostituire *"in meno di 10 minuti"* con *"in pochi passaggi"*.

---

### Verification and Test Plan

- [x] **Verifica 1: Controllo sintassi JavaScript con `node --check web/landing/app.js`**
- [x] **Verifica 2: Test script Node per verificare la presenza di `visibilitychange`, degli observer di pausa/ripresa e del corretto focus-visible in CSS**
- [x] **Verifica 3: Verifica assenza di "in meno di 10 minuti" nel modal e validità HTML**
