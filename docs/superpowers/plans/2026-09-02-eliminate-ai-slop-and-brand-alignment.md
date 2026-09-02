# Piano di Eliminazione "AI Slop" e Armonizzazione Cromatico-Tipografica del Brand

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminare radicalmente tutti i pattern di "AI slop" (emoji casuali come icone, colori Tailwind/OpenAI hardcodati, sovraccarico di card rettangolari e micro-copy prolisso in stile chatbot) per conferire alla dashboard un look & feel enterprise B2B autorevole, coerente al 100% con la palette del brand (`--green-deep: #0e8a38`, `--accent: #5eff00`, `--ink: #101310`, `--bg-elev: #f7faf5`).

**Architecture:** Adozione dei principi di `minimalist-ui`, `high-end-visual-design` e `make-interfaces-feel-better`:
1. **Zero-Emoji Policy**: rimozione integrale di emoji decorative a favore di micro-icone SVG monolinea (1.5–1.8px stroke) e badge tipografici geometrici (tag ISO).
2. **Palette Unificata**: riconduzione di tutti i colori hardcodati ai CSS Design Tokens ufficiali della landing.
3. **De-cluttering Superfici**: alleggerimento delle card inscatolate ("card soup"), eliminazione ombre pesanti, adozione di hairline dividers traslucidi.
4. **Micro-copy Professionale**: testi operativi sintetici, asciutti e autorevoli.

**Tech Stack:** HTML5, CSS3 Custom Properties (Light/Dark themes), Vanilla JavaScript ES6+.

---

## Global Constraints
- Tutte le modifiche devono mantenere l'allineamento perfetto tra Light mode (`:root`) e Dark mode (`html[data-theme="dark"]`).
- Non introdurre librerie esterne di icone: usare micro-SVG inline leggeri e manutenibili in `currentColor`.
- Non alterare le funzionalità JavaScript (ID, classi di query selector o event listener esistenti).
- Verificare costantemente con test automatizzati e `graphify update .`.

---

### Task 1: Eliminazione Totale dell'Inquinamento da Emoji (SVG & Typography Replacement)

**Files:**
- Modify: `web/index.html` (Conoscenza, Configurazione AI, Piano, Fatturazione, Sicurezza, Recensioni)
- Modify: `web/app.js` (Eventuali template dinamici che iniettano emoji)

- [x] **Step 1: Rimuovere le emoji dalle tab di Conoscenza e Configurazione AI**
  - Sostituite in `#kb-tabs` con SVG monolinea `currentColor` (FAQ, Documenti, Pagine web, Dati struttura).
  - Sostituite nelle 4 card di `configurazione-ai` con micro-icone SVG enterprise (Identità, Tono, Multilingua, Regole).

- [x] **Step 2: Sostituire le bandiere emoji con tag tipografici ISO**
  - In `configurazione-ai` eliminate tutte le bandierine e inserite pillole monospazio `.lang-tag` (`IT`, `EN`, `ES`, `FR`, `DE`) con evidenziazione del brand in stato checked.

- [x] **Step 3: Rimuovere emoji da Piano, Fatturazione, Sicurezza e Wizard**
  - Rimossa `💎` e sostituita con icona geometrica in Abbonamento.
  - Rimossa `💳` e sostituita con icona SVG in Fatturazione; bonificato il badge `Stripe Verified`.
  - Rimossa `🎉` dal wizard e sostituita spunta unicode con SVG in cerchio circolare pulito.
  - Rimossa `📁` dalla dropzone sostituendola con SVG monolinea upload.
  - Sostituita `⚠️` del banner conflitti con icona geometrica alert.

- [x] **Step 4: Pulire le emoji nella vista Recensioni**
  - Sostituito `⭐⭐⭐⭐⭐` nelle `<option>` con notazione pulita: `5 stelle — Eccellente`, etc.
  - Sostituite emoji di canali (`✍️`, `🌐`, `🦉`) con etichette tipografiche (`G`, `TA`, `Manuale`).
  - Sostituiti pollici `👍` e `👎` in `web/app.js` con micro-icone SVG vettoriali.

---

### Task 2: Armonizzazione Cromatica sui Token Ufficiali del Brand

**Files:**
- Modify: `web/style.css`

- [x] **Step 1: Bonificare tutti i colori esadecimali non conformi**
  - Eliminati tutti i rogue colors (`#10b981`, `#10a37f`, `#dc2626`, `#b91c1c`, `#f59e0b`, `#d97706`, `#1e293b`, `#635bff`).
  - Ricondotti tutti ai token ufficiali del brand: `--green-deep`, `--accent`, `--red`, `--red-soft`, `--amber`, `--amber-soft`, `--ink`, `--ink-soft`.

- [x] **Step 2: Calibrare il bilanciamento tra Forest Green (`#0e8a38`) e Lime (`#5eff00`)**
  - **Forest Green (`var(--green-deep)`)** utilizzato per navigazione attiva, badge primari, bordi e spunte.
  - **Lime (`var(--accent)`)** riservato come micro-accento tecnologico (focus ring, stato dark mode, dot animati).

- [x] **Step 3: Uniformare i badge di stato e priorità**
  - Implementate classi coerenti con sfondi soft e bordi traslucidi in armonia con le scale di colore.

---

### Task 3: De-cluttering della "Card Soup" & Raffinamento Spaziale

**Files:**
- Modify: `web/style.css`
- Modify: `web/index.html`

- [x] **Step 1: Alleggerire le card e i contatori di Conoscenza**
  - Riprogettata `.kb-summary-bar` a griglia fluida a 4 metriche con tipografia tabulare `1.45rem`, label maiuscole `0.72rem` e sfondo `--bg-elev` con bordo hairline `1px solid var(--line)`.
  - Contrast ratio delle tab attive (`.kb-tab-btn.active`) calibrato a `--green-deep` per garantire perfetta leggibilità.

- [x] **Step 2: Normalizzare bordi, ombre e raggi (Concentric Geometry)**
  - Allineati tutti i raggi interni ed esterni; ombre tinte sull'inchiostro naturale.

---

### Task 4: Riscrittura del Micro-copy (Eliminazione Tono da Chatbot)

**Files:**
- Modify: `web/index.html`

- [x] **Step 1: Riscrivere i sottotitoli prolissi in Conoscenza**
  - "Base di conoscenza": *"Informazioni aziendali indicizzate. I Dati struttura (Priorità 1) hanno precedenza autoritativa sulle risposte fornite ai clienti."*
  - Banner conflitti: *"Rilevata discrepanza di prezzi tra le fonti. L'assistente utilizzerà in priorità il dato autoritativo dei Dati struttura."*

- [x] **Step 2: Riscrivere i sottotitoli in Configurazione AI**
  - Sottotitoli operativi asciutti e diretti per Identità, Tono, Multilingua e Regole.

- [x] **Step 3: Riscrivere Sicurezza e Fatturazione**
  - Micro-copy di Stripe e garanzie crittografiche sintetizzato in modo chiaro e professionale.

---

### Task 5: Verifica, Collaudo e Sincronizzazione Graphify

**Files:**
- Test: `node -c web/app.js`
- Test: script di validazione HTML e CSS
- Test: `tests/core/test_configurazione_ai_e2e.py tests/core/test_conoscenza_e2e.py`

- [x] **Step 1: Validare la sintassi JS, HTML e CSS** (JS syntax OK, bracket balance 1216/1216, 0 rogue colors).
- [x] **Step 2: Eseguire la regression test suite pytest (100% verde)** (5/5 passati con successo in 22.92s).
- [x] **Step 3: Eseguire `graphify update .`** (Knowledge graph aggiornato: 24.817 nodi, 45.166 archi).
