# 🚀 Checklist Lancio Definitiva — Melpis SaaS

**Prodotto:** Melpis (Assistente AI per WhatsApp Business per Attività di Servizio)
**Ultimo aggiornamento:** 24 Agosto 2026 — consolidata post-esecuzione piano launch readiness (merge PR #28, CI verde)
**Target:** PMI di servizio locali (Ristoranti, Pizzerie, Saloni di Bellezza & Parrucchieri, Studi Medici & Dentistici, Centri Fitness, Hotel & B&B).

---

## ✅ 1. COMPLETATO (codice su `main`, verificato con review + CI)

### Bloccanti sicurezza (B1–B4)
- [x] **B1** — `DEMO_MODE` fail-closed: accesso anonimo negato in produzione + blocco avvio se attivo (`src/core/auth/dependencies.py`, `src/core/startup_guard.py`)
- [x] **B2** — Rate limiting distribuito su Valkey: `RATE_LIMIT_BACKEND=redis` attivo, contatori condivisi verificati cross-restart
- [x] **B3** — Export token GDPR su Redis con TTL 15 min, one-time atomico (`src/core/gdpr/token_store.py`)
- [x] **B4** — `ENCRYPTION_KEY` fail-fast all'avvio in produzione (mancante o non-Fernet → blocco) + fail-fast su chiavi Stripe `sk_live` fuori da produzione

### Pricing (B5 — parte codice)
- [x] Prezzi canonici: **Essenziale €29** / **Crescita €69** / **Scala €149**; annui **€24/€59/€129** (€288/€708/€1.548)
- [x] Checkout Stripe con `interval` monthly/yearly + price ID yearly nel webhook (`PRICE_TO_PLAN`)
- [x] Landing, FAQ, JSON-LD e Termini allineati ai nuovi prezzi

### Landing / CRO / SEO
- [x] Schema `FAQPage` JSON-LD (6 FAQ) + `SoftwareApplication` con prezzi nuovi
- [x] `sitemap.xml` con pagine legali + `<lastmod>`
- [x] Sezione social proof `#testimonial` pronta (nascosta finché non ci sono testimonianze reali)
- [x] Micro-stat di fiducia sopra il fold (setup <10 min, risposta <5s, GDPR 100%)
- [x] Plausible Analytics proxied same-origin (CSP invariata) + eventi: `click_cta`, `open_signup_modal`, `submit_signup_form`, `toggle_pricing_annual`
- [x] Cookie notice banner minimale conforme
- [x] Copia overage allineata al comportamento reale: **oltre quota il servizio va in pausa** (non "continui a 0,10€")

### Account & Legali
- [x] Flusso recupero password completo: `POST /api/auth/recover` + `/reset` + UI su /accedi/ (no enumerazione account, rate limit 5/h/IP)
- [x] `.env.production.example` completo di tutte le variabili (zero segreti)
- [x] Privacy Policy: sub-processori completi (Supabase, Meta, Stripe, OpenRouter, Plausible) + link DPA
- [x] DPA disponibile su `/api/gdpr/dpa`
- [x] Sentry integrato (serve solo il DSN), backup drill presente in compose

---

## 🔴 2. BLOCCANTI — da fare TU prima di pubblicare

- [ ] **2.1 Compilare il placeholder `[provider hosting]`** in `web/landing/privacy.html` (riga ~65) col nome reale del provider cloud.
- [ ] **2.2 Generare `ENCRYPTION_KEY` di produzione:**
      `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
      → nel secrets manager (MAI in git). Generarla nuova, non riusare quella di dev.
- [ ] **2.3 Stripe Live:**
      - Attivare account in modalità live, inserire `sk_live_...` + `STRIPE_WEBHOOK_SECRET=whsec_...`
      - Creare **6 price ID**: 3 mensili (29/69/149) + 3 annuali (24/59/129) → env `STRIPE_PRICE_STARTER/PRO/BUSINESS` + `_YEARLY`
      - Endpoint webhook: `https://melpis.it/api/billing/webhook`
      - ⚠️ **Prima di creare i price ID definitivi**, valida i prezzi con Van Westendorp (sez. 5)
- [ ] **2.4 Meta Business (B6):**
      - App WhatsApp verificata + numero reale
      - `META_APP_SECRET` + `META_VERIFY_TOKEN` nel secrets manager
      - Webhook `https://melpis.it/webhooks/whatsapp` (evento `messages`) + `/webhooks/instagram`
- [ ] **2.5 `.env.production` reale** sul server, partendo da `.env.production.example`:
      `APP_ENV=production`, **MAI** `DEMO_MODE`, `DATABASE_URL` con `sslmode=require`, `DB_POOL_MAX_SIZE=10`,
      `REDIS_URL=redis://valkey:6379/0`, `RATE_LIMIT_BACKEND=redis`,
      `CORS_ORIGINS=https://melpis.it,https://app.melpis.it`, `PUBLIC_APP_URL=https://melpis.it`
- [ ] **2.6 SENTRY_DSN di produzione configurato e testato:**
      Inserire la chiave `SENTRY_DSN` reale in `.env.production`. Se non valorizzata, i log `logger.critical` (incluso il blocco di fallback quota e fallimento escalation DB) restano su log file locale senza scatenare alert proattivi.
- [ ] **2.7 Filtro / Badge Inbox Dashboard per `escalation_failed` (PRIMA di avere traffico WhatsApp reale):**
      Aggiungere in `web/app.js` e nella Inbox operatore un filtro o badge di allerta visibile (es. badge rosso *"Escalation fallita — richiede intervento manuale"*) per i messaggi con `handling_type = 'escalation_failed'`. Completa la catena *"evento anomalo rilevato → staff allertato visivamente → intervento manuale immediato"*.

---

## ⚙️ 3. CONFIGURAZIONE SERVIZI ESTERNI

### 🌐 Dominio, DNS & SSL
- [ ] `A`/`AAAA` per `melpis.it` e `app.melpis.it` + HTTPS forzato con HSTS a livello Traefik (`stsSeconds=31536000, includeSubDomains`)
- [ ] Record email: `SPF`, `DKIM`, `DMARC` (`v=DMARC1; p=quarantine; rua=mailto:privacy@melpis.it`)

### 📧 Email transazionali
- [ ] SMTP di produzione su Supabase Auth + template IT "Confirm signup" e "Reset Password" + Site URL `https://melpis.it/accedi/`
- [ ] Testare 4 email: verifica account, recupero password, escalation HITL, report settimanale

### 💾 Backup & Monitoring
- [ ] Backup giornalieri con **retention 30 giorni** + drill verde: `docker compose run --rm backup-drill`
- [ ] `SENTRY_DSN` attivo (backend) + errore di test visibile su dashboard
- [ ] Uptime monitor esterno (BetterStack/UptimeRobot) su `/api/health` con alert Telegram/SMS

### 📞 Supporto Day-1
- [ ] Caselle `support@melpis.it`, `privacy@melpis.it`, `sales@melpis.it` attive e monitorate
- [ ] Numero WhatsApp di assistenza attivo in ore di servizio

### 📊 Analytics
- [ ] Account Plausible: aggiungere dominio `melpis.it` (lo script è già collegato via proxy `/plausible/`)

---

## 🧪 4. SMOKE TEST E2E (Go/No-Go, in produzione)

- [ ] Registrazione dalla landing (`#signupForm`) → email verifica → primo login dashboard
- [ ] Connessione guidata WhatsApp + orari/menu → messaggio reale → risposta AI < 5 secondi
- [ ] Sottoscrizione Stripe Live con carta reale (Crescita) → webhook `checkout.session.completed` → `GET /api/billing/subscription` coerente
- [ ] Cancellazione dal portale Stripe → stato sospeso/sola-lettura automatico
- [ ] Opt-out WhatsApp ("STOP") → consenso persistito, nessun invio successivo, audit event
- [ ] Escalation HITL → notifica email ricevuta

---

## 🎯 5. GO-TO-MARKET (settimane 2–4)

### Settimana 2–3: validazione prezzo & social proof
- [ ] **Van Westendorp** — le 4 domande a 15–20 lead/pilota:
      1. _A quale prezzo sarebbe **troppo costoso**?_
      2. _A quale prezzo **dubiteresti della qualità**?_
      3. _A quale prezzo sarebbe **un affare eccellente**?_
      4. _A quale prezzo sarebbe **costoso ma valido**?_
      → conferma (o rettifica) la griglia €29/€69/€149 PRIMA dei price ID Stripe definitivi
- [ ] **Mini-pilota gratuito** con 3–5 attività locali in cambio di testimonianza + autorizzazione uso nome/logo
- [ ] **3 testimonianze** (1-2 frasi, foto titolare, attività+città) → riempi `#testimonial` in `web/landing/index.html` e togli l'attributo `hidden`

### Settimana 4+: scaling & acquisizione
- [ ] **Meta Pixel** (richiede update CSP in `web/security-headers.conf`: `script-src 'self' https://connect.facebook.net`) + campagne Lookalike su titolari P.IVA locali
- [ ] Primo case study (es. _"Come la Trattoria Da Mario ha recuperato 45 coperti al mese"_)
- [ ] Setup fee onboarding assistito sul piano Scala

---

## 📌 Note operative

- **Overage**: con la decisione del 24/08 la copia promette "pausa oltre quota" (il backend blocca a limite raggiunto). Se in futuro implementi l'overage reale a €0,10/conversazione, aggiorna i testi mantenendo **identici** HTML e JSON-LD della FAQ.
- **Cache CSS/JS**: nginx ora serve CSS/JS con `max-age=300, must-revalidate` (niente più `immutable`); a ogni modifica di `style.css`/`app.js` fai bump del `?v=` negli HTML.
- **Test noti**: 1 failure + 6 errori pre-esistenti in locale da testcontainers Postgres spento (in CI con service container passano — verificato sul merge PR #28).
