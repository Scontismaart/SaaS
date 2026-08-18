# Deploy — Infrastruttura production-ready

Guida operativa per mettere il servizio in produzione su VPS + Coolify.
Questo documento è lo stato reale della "preparazione deploy-ready": la
dockerizzazione è committata e verificata, ma **il deploy vero è rimandato
al lancio commerciale**. Prima del lancio, seguire `docs/CHECKLIST-PRE-LANCIO.md`.

---

## 1. Architettura (docker-compose)

Il servizio gira come 4 processi separati in un unico container network
`app_internal` (solo `api` espone una porta verso l'esterno):

| Servizio | Comando | Risorse (limite) | Ruolo |
|---|---|---|---|
| `api` | `uvicorn src.api.main:app` | 1.0 CPU / 1g RAM | API REST + webhook WhatsApp/Instagram + dashboard |
| `worker-inbound` | `python run_inbound_processor.py` | 0.5 CPU / 512m RAM | Processa messaggi in ingresso (claim transazionali) |
| `worker-retry` | `python run_retry_worker.py` | 0.3 CPU / 256m RAM | Retry consegne fallite |
| `supervisor` | `python run_supervisor.py` | 0.1 CPU / 128m RAM | Reap claim stale + dead-letter (rete di sicurezza indipendente) |

- **Database**: Supabase (Postgres gestito esterno). Nessun DB/Redis locale in
  produzione — `postgres-dev` esiste solo nel profile `dev`, per sviluppo.
- **Volume** persistente: `chroma_data` (solo per compatibilità; lo stack
  documenti è pgvector, vedi roadmap item 11).
- **Healthcheck**: ogni 30s su `GET /api/health` (verifica app + DB). I worker
  dipendono da `api` sano (`depends_on: condition: service_healthy`).
- L'immagine gira **non-root** (`USER appuser`, uid 1000) e **non contiene
  `.env` o segreti**: il file è escluso da `.dockerignore` (righe 1-4), i secret
  entrano solo a runtime (vedi §4).

### Limiti noti (consapevoli, non difetti da sistemare ora)

- **Rate limiting in-memory per processo** (`src/api/main.py`, `RATE_LIMIT_*`):
  su una singola istanza il conteggio è per worker `api`. Valido per il target
  a singola istanza; diventa incorretto solo con più repliche di `api`.
- **Niente Redis / code esterne**: i claim sono gestiti con `FOR UPDATE SKIP
  LOCKED` su Postgres (supervisor come rete di sicurezza). Valido su scala di
  lancio; se un giorno servissero code/fan-out reali, Redis diventa il passo
  successivo (fuori scope).
- **Monitoring**: solo Sentry (`SENTRY_DSN`). Niente Grafana/Datadog (rimandati).

---

## 2. Requisiti VPS

- **Raccomandato: 2 vCPU / 4 GB RAM / 20+ GB SSD**.
- Perché: somma dei `mem_limit` = 1.9 GB + overhead OS (~0.5 GB) + margine per
  la build delle immagini Docker. 2 GB RAM sarebbe al limite e renderebbe
  fragili i picchi di build/avvio simultaneo.
- **Nota per la build**: la build (pip install, librerie) avviene sul server
  con Coolify; serve spazio disco extra per le immagini (~3-4 GB) e per gli
  strati di build cache.
- Il VPS deve poter **raggiungere** Supabase (HTTPS/5432) e le API Meta/Google:
  nessun IP in whitelist da parte nostra, ma verificare che l'host non abbia
  un firewall di default che blocchi l'egress.

---

## 3. Deploy con Coolify

Coolify builda l'immagine dal repo git e la fa girare con i segreti iniettati
a runtime. Passi:

1. **Preparare il repo**: pushare il branch `main` (l'immagine si builda dal
   `Dockerfile` alla radice; `.dockerignore` esclude già segreti, `docs/`,
   `tests/`, `web/`, `scripts/`).
2. **Creare il progetto in Coolify**:
   - Source: repo GitHub `Scontismaart/SaaS` → branch `main`.
   - Build Pack: `Dockerfile` (è presente alla radice).
   - Port: `8000` (esposta da `api`; i 3 worker e il supervisor non hanno
     porta pubblica).
3. **Domain + TLS**: aggiungere il dominio (es. `api.tuodominio.it`) → Coolify
   emette automaticamente il certificato Let's Encrypt tramite il proxy
   (Traefik/Caddy secondo la versione).
4. **Impostare le env vars** nel secret manager di Coolify (vedi §4) —
   **mai** caricare un file `.env` sul server.
5. **Avviare** il deploy. Verificare con la checklist di §6.

> Per il deploy in locale (sviluppo), senza Coolify: `docker compose up -d
> --build` avvia solo i servizi prod + `docker compose --profile dev up -d`
> aggiunge `postgres-dev` per i test.

---

## 4. Env vars da secretizzare (secret manager Coolify)

Copiare da `.env.example`; ogni valore va inserito nel secret manager, NON in
un file sul server. Suddivise per ruolo:

**Obbligatorie all'avvio dell'app**
- `DATABASE_URL` (Supabase, con `sslmode=require`)
- `SUPABASE_URL`
- `API_KEY_SERVICE` (chiave di servizio per X-API-Key)
- `ENCRYPTION_KEY` (Fernet; se cambia si perdono i token crittografati)
- `CORS_ORIGINS` (dominio della dashboard + URL Softr)
- `RATE_LIMIT_REQUESTS` / `RATE_LIMIT_WINDOW_SECONDS`

**LLM (openrouter/groq/cerebras + routing)**
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL_CHEAP`, `OPENROUTER_MODEL_PREMIUM`,
  `OPENROUTER_MODEL_FALLBACKS`, `OPENROUTER_MODEL`, `LLM_MAX_CONCURRENT`,
  `LLM_LOW_BUDGET_RATIO`
- `GROQ_API_KEY`, `CEREBRAS_API_KEY`, `MISTRAL_API_KEY`

**Guardrails (task 12)**
- `OPENROUTER_MODEL_INTENT`, `GUARDRAIL_INTENT_LLM_ENABLED`,
  `GUARDRAIL_INTENT_TIMEOUT`, `GUARDRAIL_MAX_REPLY_CHARS`,
  `GUARDRAIL_CACHE_ENABLED`, `GUARDRAIL_CACHE_THRESHOLD`,
  `GUARDRAIL_CACHE_TTL_HOURS`, `GUARDRAIL_AB_VARIANTS`

**WhatsApp / Instagram (Meta Cloud API)**
- `META_APP_SECRET`, `META_VERIFY_TOKEN` (senza questi il webhook
  `/webhooks/whatsapp` non viene montato all'avvio)

**Google (Calendar + Business Profile/recensioni)**
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`,
  `GOOGLE_REVIEWS_REDIRECT_URI`, `FRONTEND_URL`

**Stripe**
- `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_PRO`, `STRIPE_PRICE_BUSINESS`,
  `STRIPE_TRIAL_DAYS`

**Notifiche email (HITL/escalation)** — se vuote, notifiche saltate con warning
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`

**GDPR (hard-delete)**
- `SOFTR_API_KEY`, `SOFTR_WEBHOOK_URL`

**Monitoring**
- `SENTRY_DSN` (vuoto = Sentry non inizializzato)

> Regola: **niente segreti nei layer dell'immagine**. Verifica rapida post-build:
> `docker history <immagine>` non deve mostrare env con valori reali, e
> `docker run --rm <immagine> ls -la` non deve contenere `.env` (vedi §6.2).

---

## 5. Backup del database (Supabase)

**Verificare prima del lancio sul dashboard Supabase → Database → Backups:**
qual è il piano, quanti backup esistono, qual è la retention, il PITR è
abilitato? Il comportamento reale dipende dal piano:

### Piano Free
- **Nessun backup automatico.** Un incidente sul progetto = perdita dati.
- Mitigazione minima pre-lancio: dump periodico off-site, es. da un host
  esterno al VPS:
  ```bash
  pg_dump "$DATABASE_URL" -Fc -f "backup_$(date +%F).dump"
  ```
  da schedulare via cron (o GitHub Actions) e copiare su storage separato.

### Piano Pro
- **Backup giornalieri automatici, retention rolling 7 giorni** (gestiti da
  Supabase, non scaricabili dal dashboard ma ripristinabili su richiesta).
- **PITR** disponibile come add-on a pagamento (time-based recovery).
- Consigliato comunque un pg_dump settimanale off-site come rete di sicurezza
  indipendente.

### Nota Storage
- **Nessun piano include i file dello Storage** (oggetti, es. documenti
  caricati) nei backup di default. Verificare il piano Storage scelto e
  documentare la procedura di recupero prima del lancio.

---

## 6. Verifica post-deploy

1. `GET /api/health` → `200 {"status":"ok", ...}` (healthcheck profondo: app + DB).
2. **Immagine non-root e senza segreti** (una tantum, da CI o manuale):
   ```bash
   docker build -t wa-check .
   docker run --rm wa-check id -u          # deve stampare 1000, non 0
   docker run --rm wa-check ls -a /app     # NON deve contenere .env / segreti
   ```
3. Webhook Meta: `GET /webhooks/whatsapp` con `hub.mode=subscribe` + il
   `META_VERIFY_TOKEN` di produzione → risposta 200 `hub.challenge`.
4. Un messaggio end-to-end di prova su un account reale (arriva risposta AI,
   compare in inbox, delivery status ok).
5. Sentry: evento di test raggiunge il progetto.