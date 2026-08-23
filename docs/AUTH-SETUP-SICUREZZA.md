# Setup sicurezza autenticazione — configurazioni esterne

Il codice applica già tutte le policy descritta qui; alcuni interruttori
vivono però su servizi esterni e vanno configurati a mano.

## Supabase Dashboard (obbligatorio)

1. **Verifica email obbligatoria** — Authentication → Providers → Email:
   attiva **"Confirm email"**. Senza di essa gli account si attivano subito
   dopo la registrazione senza email verificata (il backend, in ogni caso,
   non apre sessioni finché Supabase non restituisce una sessione).
2. **Lunghezza minima password = 10** — Authentication → Policies:
   allinea il minimo Supabase alla policy applicativa (10 caratteri con
   almeno un simbolo, validata anche server-side in `register.py`).
3. **Email di verifica**: inviate da Supabase con il loro sender di default;
   personalizzabile in Authentication → Emails (template/sender proprio).

## Produzione (deploy)

| Voce | Valore | Dove |
|---|---|---|
| `AUTH_COOKIE_SECURE` | `true` | env backend |
| `PUBLIC_APP_URL` | `https://tuodominio` | env backend (OAuth Google) |
| `RATE_LIMIT_BACKEND` | `redis` | env backend — throttle login/signup distribuito su Valkey |
| `REDIS_URL` | raggiungibile | env backend |
| TLS + HSTS | terminazione su Traefik | infra (già presente) |

## Cosa fa già il codice (nessuna configurazione richiesta)

- Sessioni in cookie `__Host-` HttpOnly+Secure+SameSite=Strict, mai token a JS
- JWT RS256 verificati con JWKS + `aud` + `iss`
- Refresh con rotazione e single-flight; logout con revoca su Supabase
- CSRF double-submit + controllo Origin/Referer
- Throttle login 5 fallimenti/15 min per IP con lockout, distribuito
- Throttle signup 5/ora per IP, distribuito
- Anti-enumerazione: messaggi generici + latenza uniformata sul 409
- CSP restrittiva, nessun token/password in log o console
- OAuth Google con PKCE interamente server-side
