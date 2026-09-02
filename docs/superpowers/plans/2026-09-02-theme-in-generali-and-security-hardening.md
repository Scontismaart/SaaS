# Piano: Spostamento Selettore Tema in "Generali" & Hardening Sicurezza Account (Best Practices)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 
1. Spostare il controllo del tema (Chiaro, Scuro, Sistema) nella sezione "Generali" delle Impostazioni tramite un moderno segmented control, eliminando il toggle dal menu utente in sidebar per massima pulizia.
2. Innalzare la postura di sicurezza nella sezione "Sicurezza account" adottando le best practice dei migliori developer SaaS:
   - **Doppio binario**:
     - *Binario A (Modifica diretta)*: Richiesta obbligatoria della **Password attuale** (Re-authentication) per prevenire modifiche da postazioni incustodite / session hijacking.
     - *Binario B (Reset sicuro via email)*: Pulsante dedicato **"Invia link di reset alla mia email"** con chiamata autenticata a `/api/auth/send-password-reset` che spedisce un magic link crittografato e temporizzato alla casella del proprietario.

**Architecture:**
- **Frontend UI (`web/index.html`, `web/style.css`, `web/app.js`)**:
  - Nuova card "Aspetto e Tema" in Impostazioni > Generali con segmented control a 3 stati (`light`, `dark`, `system`).
  - Rimozione del pulsante tema dal menu a tendina dell'avatar in sidebar (`#sidebar-theme-toggle`).
  - Form Password in Sicurezza aggiornato con campo "Password attuale" e blocco "Hai dimenticato la password attuale? Invia link alla tua email".
  - Logica JS in `web/app.js` estesa per supportare `system` (`prefers-color-scheme`) e il feedback email mascherato.
- **Backend Auth BFF (`src/core/auth/routes.py`)**:
  - Verifica della `current_password` su Supabase Auth in `/api/auth/password` prima di autorizzare la mutazione.
  - Nuovo endpoint `/api/auth/send-password-reset` per l'invio immediato del magic link all'email dell'utente autenticato, con mascheramento email nei dettagli di risposta.

---

### Task 1: Spostamento del Controllo Tema in Impostazioni > Generali

**Files:**
- Modify: `web/index.html` (Generali & Sidebar dropdown)
- Modify: `web/style.css` (Stili segmented control tema)
- Modify: `web/app.js` (Inizializzazione tema a 3 stati con `matchMedia`)

- [x] **Step 1: Rimuovere il toggle tema dal dropdown avatar in sidebar**
  - Rimosso `#sidebar-theme-toggle` da `web/index.html`.

- [x] **Step 2: Aggiungere la card "Aspetto e Tema" in Impostazioni > Generali**
  - Inserita card con Segmented Control a 3 stati: Chiaro, Scuro, Sistema.

- [x] **Step 3: Stili CSS per il segmented control tema in `web/style.css`**
  - Creati `.settings-theme-segmented` e `.theme-seg-btn` con transizioni cubiche e token di brand.

- [x] **Step 4: Aggiornare il controller JS `inizializzaTema` in `web/app.js`**
  - Implementato supporto per `light`, `dark` e `system` (con listener `matchMedia` reattivo in tempo reale).

---

### Task 2: Backend Hardening Sicurezza Account (`src/core/auth/routes.py`)

**Files:**
- Modify: `src/core/auth/routes.py`

- [x] **Step 1: Aggiornare `PasswordChange` e verificare `current_password`**
  - Modello esteso con `current_password`.
  - Re-autenticazione crittografica tramite Supabase Auth prima di consentire la modifica diretta.

- [x] **Step 2: Aggiungere l'endpoint `/api/auth/send-password-reset`**
  - Creato l'endpoint autenticato con invio magic link di reset sicuro e mascheramento privacy dell'email (`ma•••@dominio.it`).

---

### Task 3: Aggiornamento Frontend Sezione Sicurezza (`web/index.html`, `web/app.js`)

**Files:**
- Modify: `web/index.html` (Pannello Sicurezza)
- Modify: `web/app.js` (Handler form password e reset email)

- [x] **Step 1: Aggiornare il form Password in `web/index.html`**
  - Aggiunto campo obbligatorio "Password attuale" e blocco reset via email.

- [x] **Step 2: Aggiornare gli handler in `web/app.js`**
  - Gestione invio `current_password` al backend e click handler su `#security-send-reset-btn`.

---

### Task 4: Verifica, Collaudo e Sincronizzazione Graphify

**Files:**
- Test: `node -c web/app.js`
- Test: `python -m pytest tests/ -v` (o test auth dedicati)
- Update: `graphify update .`

- [x] **Step 1: Validare la sintassi JavaScript e Python** (JS OK, Python import OK, CSS bracket balance 1223/1223).
- [x] **Step 2: Eseguire la test suite Pytest** (15/15 passed in `test_account_security.py`, 5/5 passed in `test_audit_extended.py`).
- [x] **Step 3: Eseguire `graphify update .`** (Knowledge graph aggiornato a 24.832 nodi e 45.187 archi).
