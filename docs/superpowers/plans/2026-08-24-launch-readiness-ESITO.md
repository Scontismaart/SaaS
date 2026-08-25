# Esito Esecuzione Piano Launch Readiness — 24/08/2026

**Branch:** `feature/launch-readiness` (19 commit da baseline `9d89939`)
**Esito final review:** APPROVED_WITH_FIXES → fix wave applicata → **re-review CLEAN**
**Test:** 188 passed; 1 failed + 6 errori pre-esistenti ambientali (testcontainers Postgres, verificati identici sulla baseline)

## ✅ Completato (task codice)

| Task | Cosa | Commit |
|---|---|---|
| 1 — B1 | DEMO_MODE fail-closed: `is_demo_mode()` negato in produzione + guard `assert_production_safe()` all'avvio | `13cfad7` |
| 2 — B3 | Export token GDPR su Redis (TTL 15 min, one-time atomico via GETDEL, fallback memory dev/test) | `1dfb5ad` |
| 3 — B4 | ENCRYPTION_KEY fail-fast in produzione (mancante o non-Fernet → blocco avvio) | `346e606` |
| 4 — B2 | Rate limiting distribuito VERIFICATO: contatore 1→2 attraverso restart api (Valkey) | config `.env` |
| 5 — B5a | Prezzi 29/69/149 (annui 288/708/1548), nomi Essenziale/Crescita/Scala, checkout `interval` monthly/yearly, PRICE_TO_PLAN include yearly | `6626fe1`+`d18927f` |
| 7 | Prezzi landing + note annuali + overage badge "fino a −17%" | `f07fff4`+`0655cab` |
| 8 | FAQPage JSON-LD (6 FAQ verbatim) + SoftwareApplication prezzi nuovi + sitemap con pagine legali | `7b62c44` |
| 9 | Sezione social proof `#testimonial` (nascosta finché testimonianze reali) + micro-stat allineate | `ea3d21a` |
| 10 | Plausible proxied same-origin (`^~ /plausible/`, CSP invariata) + 4 eventi (click_cta/open_signup_modal/submit_signup_form/toggle_pricing_annual) | `7f8bfdf` |
| 11 | Cookie notice banner minimale (localStorage flag, z-index sotto modal) + bump app.js v4 | `ed0a6ca`+`3c8d51c` |
| 12 | Password reset: POST /api/auth/recover + /reset (no enumerazione account, throttle 5/h/IP) + UI 3 stati su /accedi/ | `3761f6c` |
| 13 | `.env.production.example` completo (205 righe, zero segreti) | `6ed4201` |
| 17 | Sub-processori legali: OpenRouter + Plausible + link DPA nel footer privacy | `80c3cc8` |
| Fix wave | Copia overage allineata al backend reale (pausa oltre quota), Plausible nei legali, fail-fast sk_live fuori da produzione, warning token store memory in prod | `37af91b`..`7afbba7` |

## 🔴 Bloccanti pre-pubblicazione (TUOI)

1. **`[provider hosting]` placeholder** in `web/landing/privacy.html:65` — compilare col nome reale del provider
2. **Docker Desktop spento**: riavvialo ed esegui `docker compose up -d --build web` per servire la landing finale su :8080

## 📋 Task OPS rimasti (checklist originale)

- **Task 6 (B6):** app Meta Business + `META_APP_SECRET`/`META_VERIFY_TOKEN` + webhook live + numero verificato
- **Task 13-ops:** Stripe Live: `sk_live_`, 6 price ID (3 mensili + 3 yearly), webhook + `STRIPE_WEBHOOK_SECRET`
- **Task 14:** DNS melpis.it/app.melpis.it, HSTS su Traefik, SPF/DKIM/DMARC
- **Task 15:** SMTP produzione + template Supabase IT (Confirm signup, Reset Password) + Site URL `https://melpis.it/accedi/`
- **Task 16:** backup retention 30gg + drill + Sentry DSN + uptime monitor
- **Task 18:** caselle support@/privacy@/sales@ + WhatsApp assistenza
- **Task 19:** smoke test E2E (6 punti della checklist)
- **Task 20:** Van Westendorp + pilota 3-5 attività + 3 testimonianze → riempire `#testimonial` e togliere `hidden`
- **Task 21:** Meta Pixel (richiede update CSP) + campagne + setup fee Scala
- **Plausible:** creare account e aggiungere dominio `melpis.it`

## 📝 Minor deferred (non bloccanti, triage final review: deferred-ok)

Elenco completo nel ledger `.superpowers/sdd/2026-08-24-launch-readiness/progress.md` (13 voci; le principali: json.loads senza guardia in token_store.py, test che mutano globali senza reset, wa_csrf senza prefisso __Host-, note legali su giurisdizione OpenRouter da review legale).

## ⚠️ Nota comportamento prodotto

Con la decisione "allinea i testi": oltre quota il servizio **va in pausa** (non overage). Se in futuro implementi l'overage reale a 0,10€, riaggiorna i testi mantenendo verbatim HTML↔JSON-LD.
