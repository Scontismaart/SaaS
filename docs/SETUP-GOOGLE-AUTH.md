# Setup login con Google (OAuth via Supabase)

Il login Google usa il flusso **OAuth 2.0 + PKCE gestito interamente dal
backend** (stesso modello BFF del login email/password): i token non passano
mai dal JavaScript del browser.

```
Browser                 Backend (BFF)                Supabase Auth        Google
   │  GET /api/auth/google/start
   │───────────────────────►│  genera verifier+state      │                 │
   │  ◄── 302 authorize URL ┘                             │                 │
   │  GET /auth/v1/authorize?provider=google …            │                 │
   │─────────────────────────────────────────────────────►│  dialog OAuth   │
   │◄──────────────────────────────────────────────────────────────────────┤
   │  GET /api/auth/google/callback?code=…&state=…                          │
   │───────────────────────►│  scambia code↔token (PKCE) │                  │
   │  ◄── 302 /app/ + cookie HttpOnly sessione ────────────│                  │
```

## 1. Google Cloud Console

1. Apri [Google Cloud Console → API e servizi → Credenziali](https://console.cloud.google.com/apis/credentials) (usa lo stesso progetto già usato per Calendar/Reviews, se presente).
2. **Crea credenziali → ID client OAuth → Applicazione web**.
3. In **URI di reindirizzamento autorizzati** aggiungi l'URL di callback Supabase:
   ```
   https://<PROJECT-REF>.supabase.co/auth/v1/callback
   ```
   (`<PROJECT-REF>` = sottodominio del tuo progetto Supabase).
4. Salva: ti servono **Client ID** e **Client secret** al passo 3.

> Se l'app OAuth è in modalità "Testing", solo gli utenti aggiunti come Test
> User possono accedere. Per il lancio pubblica l'app (Publishing status →
> In production).

## 2. Supabase Dashboard

1. Apri il tuo progetto su [supabase.com](https://supabase.com) → **Authentication → Providers → Google**.
2. Abilita il provider e inserisci **Client ID** e **Client Secret** del passo 1.
3. Salva.
4. In **Authentication → URL Configuration → Redirect URLs** aggiungi:
   ```
   https://<TUO-DOMINIO>/api/auth/google/callback
   ```
   Questo è l'URL che Supabase richiama alla fine dell'OAuth; deve corrispondere
   esattamente a `PUBLIC_APP_URL` + `/api/auth/google/callback`.

## 3. Variabili d'ambiente backend

Nel `.env` di produzione:

```env
# URL pubblico dell'app (senza slash finale): base del redirect_to OAuth
PUBLIC_APP_URL=https://tuodominio
```

`SUPABASE_URL` e `SUPABASE_ANON_KEY` sono già richiesti dal BFF esistente.

## 4. Verifica end-to-end

1. Vai a `https://tuodominio/accedi/`.
2. Clicca **Accedi con Google** → completi il dialog Google.
3. Vieni riportato su `/app/` con la sessione attiva (cookie HttpOnly, come
   per il login email/password).

Errori comuni:

| Sintomo | Causa |
|---|---|
| Redirect a `/accedi/?errore=google` subito dopo il dialog | `redirect_to` non presente tra le Redirect URLs Supabase, o provider Google non abilitato |
| Errore Google "redirect_uri_mismatch" | Callback Supabase (`…supabase.co/auth/v1/callback`) mancante in Google Cloud Console |
| `500 PUBLIC_APP_URL non configurato` | variabile `PUBLIC_APP_URL` assente nell'ambiente backend |
| `bad_oauth_state` con redirect al Site URL | uno `state` custom è stato passato all'authorize URL: Supabase Auth genera e valida lo state internamente, passarne uno custom rompe il flusso |

## Note di sicurezza

- Il PKCE `code_verifier` viaggia solo in cookie **HttpOnly**
  (`wa_oauth_verifier`, max-age 10 minuti, SameSite=Lax):
  il JS non può leggerlo né alterarlo.
- Lo `state` OAuth è generato e validato internamente da Supabase Auth
  (uuid della flow_state): l'integrità del flusso è garantita da PKCE —
  senza il verifier nel cookie HttpOnly lo scambio del codice fallisce
  (fail-closed) con redirect alla pagina di accesso.
- I token di sessione sono impostati con gli stessi identici cookie del login
  email/password (`__Host-wa_at`, `__Host-wa_rt`) — nessuna differenza di superficie.
