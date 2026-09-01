# Landing Page Critical Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare i 3 bug critici della landing `web/landing/`: (1) la CSP blocca gli handler inline rompendo toggle prezzi / signup / menu mobile, (2) link e asset relativi rotti nelle pagine legali servite da URL puliti, (3) contenuto `.reveal`/`.stagger-*` invisibile senza JavaScript.

**Architecture:** Sito statico vanilla (zero dipendenze) servito da nginx con `Content-Security-Policy: script-src 'self'` (niente `unsafe-inline`). Quindi: tutti i gestori evento devono essere `addEventListener` in `app.js` (file esterno, ammesso dalla CSP); nessuno script inline è possibile. Il fallback no-js si ottiene gateando le regole CSS che nascondono il contenuto sotto `html.js`, classe aggiunta da `app.js` come prima istruzione.

**Tech Stack:** HTML/CSS/JS vanilla, nginx (header in `web/security-headers.conf`), Playwright + Chrome di sistema per la verifica (già presente in `node_modules`), server statico Node temporaneo fuori dal repo.

**Spec:** Analisi del 2026-09-01 (conversazione) — sezione "🔴 Critici". Nessun documento separato.

## Global Constraints

- Non introducare script inline nell'HTML: la CSP di produzione (`script-src 'self'`, `web/security-headers.conf`) li blocca.
- Non modificare `web/security-headers.conf` né `web/nginx.conf` in questo piano (scope: solo i 3 punti critici lato frontend).
- Nessun nuovo asset, nessuna dipendenza npm.
- Il repo ha WIP non commitato preesistente **negli stessi file** (`web/landing/app.js`, `index.html`, ecc. erano già modificati a inizio sessione): i task NON fanno commit mirati per non mescolare WIP altrui; la revisione/commit è rimandata all'utente.
- Il servizio Docker monta `web/landing/index.html`, `style.css`, `app.js` come volumi bind: le modifiche a questi 3 file sono visibili senza rebuild; le pagine legali e `404.html` richiedono rebuild immagine.

**File interessati (mappa completa):**

| File | Responsabilità |
|---|---|
| `web/landing/index.html` | Rimozione attributi `onclick`/`onsubmit`; link brand assoluti |
| `web/landing/app.js` | Aggiunge `html.js`; cabla menu mobile, billing toggle, submit form |
| `web/landing/style.css` | Regole `.reveal`/`.stagger-*` gateate sotto `html.js` |
| `web/landing/privacy.html`, `termini.html`, `cookie.html`, `404.html` | Tutti gli `href`/`src` relativi → assoluti |
| (temporaneo, fuori repo) `$TEMP/landing_audit/` | Server statico con header di produzione + script Playwright |

---

### Task 1: Riferimenti assoluti nelle pagine legali e 404 — ✅ GIÀ APPLICATO

**Files:**
- Modify: `web/landing/privacy.html`, `web/landing/termini.html`, `web/landing/cookie.html`, `web/landing/404.html`, `web/landing/index.html` (solo brand link)

**Stato:** applicato via `sed` durante la sessione (verificato: `grep -P '(href|src)="(?!https?:|/|#|data:)'` non trova più nulla in questi file). Mapping usato:

- `href="index.html"` → `href="/"`
- `href="privacy.html"` → `href="/privacy/"`
- `href="termini.html"` → `href="/termini/"`
- `href="cookie.html"` → `href="/cookie/"`
- `href="logo.webp"` / `src="logo.webp"` → `/logo.webp`
- `href="style.css?v=white-theme-7"` → `href="/style.css?v=white-theme-7"` (necessario in `404.html`, servita a profondità arbitraria)

- [x] **Step 1:** sostituire i riferimenti (comando `sed` con i mapping sopra su 4 file legali + index.html per i brand link)
- [x] **Step 2:** verificare assenza di riferimenti relativi residui:

```bash
grep -nE '(href|src)="(?!https?:|/|#|data:)[^"]+"' -P privacy.html termini.html cookie.html 404.html
# Expected: nessuna riga (exit 1)
```

### Task 2: Rimozione handler inline da index.html — ✅ GIÀ APPLICATO

**Files:**
- Modify: `web/landing/index.html:79-85` (menu mobile), `:1255-1256` (billing toggle), `:1424` (form signup)

**Stato:** applicato con Edit. Gli attributi rimossi:

- `onclick="closeNav()"` dai 6 link `.mobile-link` e dal CTA `data-signup` dell'overlay
- `onclick="setBilling('monthly')"` / `onclick="setBilling('annual')"` da `#btnMonthly` / `#btnAnnual`
- `onsubmit="handleSignupSubmit(event)"` da `#signupForm`

- [x] **Step 1:** rimuovere gli attributi (mantenere `id`, `class`, `data-*` intatti)
- [ ] **Step 2 (dipende da Task 3):** verificare via Playwright che i comportamenti siano cablati (Task 5)

### Task 3: Cablaggio listener in app.js (CSP-safe)

**Files:**
- Modify: `web/landing/app.js` (4 punti)

**Interfaces:**
- Consumes: elementi DOM `#navHamburger`, `#mobileOverlay`, `#btnMonthly`, `#btnAnnual`, `#signupForm` (già presenti in index.html senza handler)
- Produces: nessuna API globale nuova (rimossa `window.closeNav`, `window.setBilling`, `window.handleSignupSubmit` — erano esposte solo per gli handler inline)

- [ ] **Step 1: aggiungere la classe `js` come prima istruzione dell'IIFE** (abilita il gating CSS del Task 4)

```js
(function () {
    'use strict';

    // Segnala JS attivo: il CSS nasconde .reveal/.stagger-* solo sotto html.js,
    // così il contenuto resta visibile se app.js non si carica o JS è disabilitato.
    document.documentElement.classList.add('js');
```

- [ ] **Step 2: sostituire `window.closeNav = closeNav;` con il cablaggio dei link dell'overlay**

```js
    // Chiusura menu da link e CTA nell'overlay (sostituisce i vecchi onclick inline)
    if (overlay) {
        overlay.querySelectorAll('.mobile-link, .btn-pill-cta').forEach(function (el) {
            el.addEventListener('click', closeNav);
        });
    }
```

- [ ] **Step 3: convertire `window.setBilling` in funzione locale + listener**

```js
    /* ---------- Billing Toggle (Mensile / Annuale -20%) ---------- */
    function setBilling(period) {
        // ... corpo invariato (toggle classi active, swap data-monthly/data-annual, trackEvent)
    }

    var btnMonthlyEl = document.getElementById('btnMonthly');
    var btnAnnualEl = document.getElementById('btnAnnual');
    if (btnMonthlyEl) btnMonthlyEl.addEventListener('click', function () { setBilling('monthly'); });
    if (btnAnnualEl) btnAnnualEl.addEventListener('click', function () { setBilling('annual'); });
```

- [ ] **Step 4: convertire `window.handleSignupSubmit` in funzione locale + listener**

```js
    function handleSignupSubmit(e) {
        e.preventDefault();
        // ... corpo invariato (trackEvent + redirect /registrati/?email=...&settore=...)
    }

    var signupForm = document.getElementById('signupForm');
    if (signupForm) signupForm.addEventListener('submit', handleSignupSubmit);
```

### Task 4: Fallback no-js per `.reveal` e `.stagger-*`

**Files:**
- Modify: `web/landing/style.css:4210-4219` (regole `.reveal`), `:2285-2290` (regole `.stagger-*`)

**Rationale specificità:** `html.js .reveal` = (0,2,1) batte `.reveal.visible` = (0,2,0), quindi anche lo stato visibile va gateato. Per gli stagger, i selettori di reveal `.split-block-wrap.is-visible .stagger-text` = (0,3,0) battono già `html.js .stagger-text` = (0,2,1), quindi basta gateare solo la regola base. Il blocco `prefers-reduced-motion` usa `!important` e resta valido.

- [ ] **Step 1: gateare le regole**

```css
/* PRIMA */                      /* DOPO */
.reveal {                        html.js .reveal {
    opacity: 0;                      opacity: 0;
    ...                              ...
}                                }
.reveal.visible {                html.js .reveal.visible {
    opacity: 1;                      opacity: 1;
    transform: translateY(0);        transform: translateY(0);
}                                }
.stagger-text, .stagger-mockup { html.js .stagger-text,
                                     html.js .stagger-mockup {
    opacity: 0;                      opacity: 0;
    ...                              ...
}                                }
```

- [ ] **Step 2: verifica statica** — con JS disattivato nessuna regola nasconde contenuto:

```bash
grep -n "^\.reveal {" web/landing/style.css          # Expected: nessun match (solo html.js .reveal)
grep -n "^\.stagger-text" web/landing/style.css      # Expected: nessun match
```

### Task 5: Verifica end-to-end con CSP di produzione (Playwright)

**Files:**
- Create (temporaneo, FUORI dal repo): `$TEMP/landing_audit/server.js` + `$TEMP/landing_audit/audit.cjs` — eliminati a fine verifica

- [ ] **Step 1: server statico con header di produzione** (réplica la CSP di `web/security-headers.conf`; serve `web/landing/` con mapping URL puliti `/privacy/` ecc.). Attenzione Windows: `path.normalize()` sulla root prima del confronto `startsWith`.
- [ ] **Step 2: script di verifica** (Playwright, `executablePath` = Chrome di sistema, ogni passo in `try/catch` isolato con stampa progressiva):

Aspettative post-fix, tutte sotto CSP `script-src 'self'`:
1. Click reale su `#btnAnnual` → prezzo featured diventa **55**, bottone `.active`
2. Click su CTA hero (via JS) → modale `.open`
3. Submit form → URL diventa `/registrati/?email=...&settore=hotel_bnb` (NON `/?email=...` GET nativo)
4. Menu mobile: apertura + click su link → overlay si chiude
5. Console: **zero** errori "violates the following Content Security Policy directive"
6. `.reveal` sotto `html.js` osservato visibile dopo scroll (meccanismo invariato)
- [ ] **Step 3: girare lo script, correggere finché tutte le aspettative passano**
- [ ] **Step 4: smontare server e file temporanei**

### Task 6: Aggiornamento grafo e consegna

- [ ] **Step 1:** `graphify update .` (AGENTS.md lo richiede dopo modifiche al codice)
- [ ] **Step 2:** NO commit automatico (vincolo Global Constraints) — riepilogo diff all'utente
- [ ] **Step 3:** review finale via skill `requesting-code-review`

## Self-Review

1. **Copertura spec:** ✅ punto 1 (CSP/handler) = Task 2+3; punto 2 (link legali) = Task 1; punto 3 (no-js) = Task 4. Verifica = Task 5.
2. **Placeholder:** il corpo invariato di `setBilling`/`handleSignupSubmit` è segnato come "corpo invariato" perché il piano documenta una trasformazione meccanica di codice esistente riportato per intero nella conversazione; le parti nuove (listener, classe `js`) sono inline complete.
3. **Coerenza nomi:** `closeNav`, `setBilling`, `handleSignupSubmit`, `#btnMonthly`, `#btnAnnual`, `#signupForm`, `#mobileOverlay` — coerenti tra HTML e app.js.
