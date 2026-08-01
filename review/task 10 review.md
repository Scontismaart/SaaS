# Task 10 — CI/CD, Migrazioni, Observability

## Obiettivo

Cinque interventi di hardening trasversali: Docker readiness, CI/CD con GitHub Actions, Sentry + trace_id, requirements.txt pinnato + Pillow, verifica crittografia Fernet.

---

## Riassunto modifiche

### Punto 1 — Docker readiness
| File | Cosa |
|------|------|
| `docker-compose.yml` | Aggiunto servizio `postgres-dev:16` con `profiles: ["dev"]` — non parte in produzione. Named `postgres-dev`, porte `5433:5432`, volume persistente `pgdata_dev`. `depends_on` con `required: false` su api. |

### Punto 2 — CI/CD (GitHub Actions)
| File | Cosa |
|------|------|
| `.github/workflows/ci.yml` | **Nuovo** — Trigger: `pull_request` su `main`. Service container postgres:16. Steps: checkout → setup-python 3.12 → pip install → `ruff check` → `pytest`. Env vars `CI=true` e credenziali DB via env. |
| `.github/workflows/migrations.yml` | **Nuovo** — Trigger: `push` su `main` quando tocca `.sql`. Steps: auth stub SQL (CREATE SCHEMA auth + auth.users + auth.uid/auth.jwt) → whatsapp schema → core schema → triggers → tutte le migrazioni in ordine → test. |
| `tests/core/conftest.py` | Riscritto: se `CI=true`, `postgres_container` fixture restituisce _FakeContainer con DSN dal service container (evita testcontainers). Schema/migrazioni sempre applicati in entrambi i casi. |
| `tests/whatsapp/conftest.py` | Stesso pattern: `postgres_container` fixture condizionale. |

### Punto 3 — Sentry + trace_id
| File | Cosa |
|------|------|
| `requirements.txt` | Aggiunto `sentry-sdk>=2.0,<3` |
| `.env.example` | Aggiunto `SENTRY_DSN=` con commento. Se vuoto, Sentry non parte. |
| `src/api/main.py` | `sentry_sdk.init()` condizionale prima di creare `app`. Aggiunto `trace_id_middleware` HTTP: legge `X-Request-ID` o genera UUID, lo setta in `request.state.trace_id`, lo rimanda come header `X-Trace-ID` nella response. |
| `src/whatsapp/router.py` | `receive_webhook` estrae `trace_id` da `request.state.trace_id` e lo passa a `_handle_inbound_message`. Logging strutturato: `message_id=%s trace_id=%s event=...`. |

### Punto 4 — requirements.txt pinnato + Pillow
| File | Cosa |
|------|------|
| `requirements.txt` | Tutte le 26 dipendenze pinnate a versione esatta (`==X.Y.Z` invece di `>=X,<Y`). Aggiunto `Pillow==12.3.0`. Aggiunto `sentry-sdk>=2.0,<3`. |

### Punto 5 — Encryption verificata
**Risultato: nessuna modifica necessaria.**

| Cosa | Stato | Prova |
|------|-------|-------|
| Token OAuth WhatsApp | ✅ Cifrato Fernet | `repository.py:encrypt_token()` → encrypt alla save, `config.py:load_tenant_config()` → decrypt alla load |
| Email configs | Solo indirizzo (nessuna password) | Nessun segreto da cifrare |
| Altre API key | Nessuna nel DB | Tutte da env var: OPENROUTER_API_KEY, AIRTABLE_API_KEY, SOFTR_API_KEY, STRIPE_API_KEY |
| Test | ✅ Passa | `test_save_tenant_config_encrypts_token` verifica cifratura + decifratura |

---

## Risultato finale

```
304 passed, 4 warnings in 125.91s
```

Tutti i 5 punti implementati e verificati:

1. ✅ **Docker** — `docker-compose --profile dev up` disponibile
2. ✅ **CI/CD** — 2 workflow Actions: PR check (lint + test), migration validation su merge
3. ✅ **Sentry + trace_id** — Sentry condizionale, trace_id su ogni webhook, logging strutturato
4. ✅ **requirements.txt** — 26 dipendenze pinnate + Pillow presente
5. ✅ **Encryption** — Fernet già applicato ai token WhatsApp (confermato)
