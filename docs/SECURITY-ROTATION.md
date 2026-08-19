# Rotazione dei segreti

Procedura per ruotare i segreti dell'ambiente, in ordine di rischio.
Segue le raccomandazioni dell'audit di sicurezza: nessuna chiave reale è mai
committata nel repo; la rotazione serve quando una chiave viene esposta o
semplicemente come igiene periodica.

> **Regola d'oro:** prima di ruotare, verificare che nessun segreto sia
> presente in git. `git ls-files | grep -iE "key|secret|token|credential"`.
> Nel caso di `Supabase-credentials.txt` è stato **eliminato** (vedi sotto).

---

## 0. Verifica rapida di esposizione

```bash
# Segreti mai committati? Deve essere vuoto:
git ls-files | findstr /i "key secret token credential env"
# Cronologia? Nessun file di segreti deve comparire:
git log --all --oneline -- .env  Supabase-credentials.txt
```

Se qualcosa compare, il segreto è **compromesso** e va ruotato subito
(qualunque sia il punto della checklist).

---

## 1. ENCRYPTION_KEY (chiave Fernet)

Protegge le credenziali a riposo: `whatsapp_accounts.access_token`,
`instagram_accounts.access_token`,
`google_calendar_credentials.{access,refresh}_token`,
`google_business_credentials.{access,refresh}_token`.

Lo script `scripts/rotate_encryption_key.py` ri-cifra in-place, con backup e
transazione unica (rollback se una riga non si decifra).

```bash
# 1. Genera la nuova chiave
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Prove generali: dry-run (non scrive nulla)
$env:ENCRYPTION_KEY="<vecchia-chiave>"
python scripts/rotate_encryption_key.py --new-key "<nuova-chiave>" --dry-run

# 3. Rotazione reale (scrive backup in backups/ + UPDATE in transazione)
python scripts/rotate_encryption_key.py --new-key "<nuova-chiave>"

# 4. Aggiorna ENCRYPTION_KEY nel .env / secrets manager con la NUOVA chiave
#    e fai il deploy. (Tra il punto 3 e il 4 c'è un piccolo maintenance
#    window: le istanze ferme decifrano solo con la vecchia chiave.)

# 5. Verifica che tutto si decifri con la nuova chiave
python scripts/rotate_encryption_key.py --verify "<nuova-chiave>"
```

Per evitare del tutto la finestra di manutenzione: aggiungere un'istanza
dell'app con la NUOVA `ENCRYPTION_KEY`, far girare lo script sul DB condiviso
e poi spegnere la vecchia istanza.

---

## 2. API key dei provider LLM (OpenRouter, Groq, Cerebras, Mistral)

Nel `.env`: `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `CEREBRAS_API_KEY`,
`MISTRAL_API_KEY`.

1. Accedi alla dashboard del provider (o richiedi una nuova key);
2. revoca la vecchia key, genera la nuova;
3. aggiorna il valore nel `.env` e nel secrets manager di produzione;
4. fai il deploy e verifica con una richiesta di test (`/api/health` + una
   risposta reale del responder).

---

## 3. DATABASE_URL / SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY

Per Supabase:
1. Impostazioni → Database → *Reset database password* (rigenera la password
   del ruolo `postgres`) e aggiorna `DATABASE_URL`;
2. Per la service role key: Settings → API → *Roll service_role key*;
3. Aggiorna `SUPABASE_URL` solo se cambia anche il progetto (altrimenti resta).

Il backend usa `SUPABASE_JWT_AUD`/`SUPABASE_URL` per la verifica dei JWT
(iss/aud) e `API_KEY_SERVICE` per l'auth service-to-service. Dopo la rotazione
della service role key, nessun deploy deve contenere la vecchia.

---

## 4. API_KEY_SERVICE

Chiave usata dagli agent esterni (dashboard) verso l'API.

1. Genera una nuova: `python -c "import secrets; print(secrets.token_urlsafe(32))"`;
2. aggiorna `API_KEY_SERVICE` nel `.env` e nel secrets manager;
3. deploy; 4. i client che usavano la vecchia key vanno aggiornati
(il confronto è `hmac.compare_digest`, quindi la vecchia cessa di valere
all'istante).

---

## 5. META_APP_SECRET / META_VERIFY_TOKEN / secret Stripe

- Meta: dashboard dell'app Meta → *App secret* → reset, e *Webhook verify
  token* rigenerato; aggiornare entrambi in `.env` (se il webhook cambia
  endpoint, va ri-registrato su Meta).
- Stripe: Dashboard → Developers → API keys → *Roll key*; aggiornare
  `STRIPE_SECRET_KEY` e il webhook secret `STRIPE_WEBHOOK_SECRET` (il webhook
  va ri-verificato).

---

## Post-rotazione obbligatorio

1. `git status` pulito da file di segreti; nessun commit con chiavi.
2. Verifica funzionale: login dashboard, una risposta WhatsApp, un export GDPR,
   una prenotazione.
3. Se era la `ENCRYPTION_KEY`: `--verify` con la nuova chiave (punto 1).