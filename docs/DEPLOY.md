# Deploy a costo zero — profilo sandbox

Questa procedura non crea risorse e non autorizza addebiti. Il target scelto è
una VM Oracle Cloud Always Free, perché l'app richiede API e worker sempre
attivi; un piano con sleep o senza background worker non basta. Disponibilità e
quote dell'account vanno verificate nel portale prima del GO.

## Architettura

- Caddy è l'unico servizio esposto e gestisce TLS e proxy same-origin.
- Nginx serve il frontend; FastAPI non espone porte direttamente.
- I worker gestiscono inbox webhook durabile, risposte, retry e lease stale.
- Valkey mantiene rate limiting con AOF.
- Supabase Free fornisce PostgreSQL/pgvector via TLS.

Il manifest `compose.production.yml` non monta il sorgente, richiede riferimenti
OCI `repository@sha256:<64-hex>` emessi dal workflow (i tag, inclusi i tag SHA,
sono rifiutati dal preflight), usa processi non privilegiati, limiti risorse e rotazione
log. Solo Caddy pubblica 80/443.

## Preparazione

1. Crea Supabase Free nella regione appropriata e abilita pgvector.
2. Applica in ordine le migrazioni, incluse `052_webhook_inbox.sql`,
   `053_billing_reliability.sql` e `054_supabase_advisor_hardening.sql`.
3. Verifica nel pannello Groq che l'account sia FREE e senza billing attivo;
   solo allora imposta `GROQ_FREE_ACCOUNT_CONFIRMED=true`.
4. Usa esclusivamente Stripe Test Mode e Meta sandbox/test number. Compila
   `WHATSAPP_TEST_RECIPIENTS` e, se usato, `INSTAGRAM_TEST_RECIPIENTS`.
5. Copia `.env.production.example` in `.env.production` solo sulla VM, genera
   una nuova chiave Fernet e inserisci i segreti. Non commettere il file.
6. Esegui il controllo read-only:

   ```powershell
   python scripts/release_preflight.py --env-file .env.production
   ```

7. Crea il file runtime del frontend. Contiene solo i sei valori legali già
   approvati (nessun segreto API/DB) ed è scritto con permessi owner-only:

   ```powershell
   python scripts/write_legal_runtime_env.py --env-file .env.production --output .runtime/legal.env
   ```

8. Copia dal GitHub Actions summary i due riferimenti digest completi in
   `MELPIS_API_IMAGE_REF` e `MELPIS_WEB_IMAGE_REF`. Imposta inoltre
   `CADDY_SITE_MODE=temporary` e `PUBLIC_HOST` sul DNS temporaneo. Il compose
   carica solo `Caddyfile.temporary`, quindi non richiede certificati per
   `melpis.it` o `app.melpis.it` prima del DNS finale. Poi valida e avvia:

   ```powershell
   docker compose -f compose.production.yml config
   docker compose -f compose.production.yml up -d
   ```

## Go/no-go obbligatorio

- Health live/ready 200 via HTTPS; database con TLS e RLS attiva.
- Registrazione, login, MFA e isolamento tra due organizzazioni sandbox.
- Webhook Meta firmato: ACK rapido, riga inbox durabile, worker completato.
- Solo un destinatario in allowlist riceve il messaggio di prova.
- STOP persiste il consenso, blocca invii e produce audit event.
- Stripe `sk_test_`: checkout, duplicati, eventi fuori ordine, cancellazione e
  deposito con carta fittizia.
- Fallimento escalation visibile in Inbox e intervento umano disponibile.
- Riavvio durante webhook/retry senza doppio effetto osservabile.
- Prima di clienti reali: `pg_dump` cifrato verso storage separato gratuito e
  restore drill su un database di verifica. Non presumere backup nel tier Free.

## Rollback

Mantieni i due riferimenti digest precedenti: ripristina
`MELPIS_API_IMAGE_REF` e `MELPIS_WEB_IMAGE_REF` e rilancia il compose.
Le migrazioni 052/053/054 sono additive e non vanno eliminate nel rollback. Se una
migrazione fallisce, ferma il traffico e ripristina un dump verificato.

## Evidenze ancora esterne

Codice e manifest non provano disponibilità Oracle, quote Supabase/Groq, DNS,
consegna Meta, webhook Stripe o backup separato. Non segnare queste voci complete
senza gli account sandbox e l'host effettivo.
