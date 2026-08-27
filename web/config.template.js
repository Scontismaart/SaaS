/* =============================================================================
   ATTENZIONE — FILE PUBBLICO SERVITO SENZA AUTENTICAZIONE
   =============================================================================
   Questo file è accessibile a CHIUNQUE da Internet (/config.js).
   NON inserire MAI qui dentro:
   - Token segreti, API Key private, Service Role Key (Supabase/Stripe/Meta)
   - Password, certificati o chiavi di crittografia (Fernet)
   - Qualsiasi dato sensibile o credenziale di backend

   Questo file deve contenere ESCLUSIVAMENTE parametri di runtime pubblici
   necessari al browser (es. window.MELPIS_API_BASE).
   ============================================================================= */

// Generato a build-time dall'entrypoint nginx (envsubst). In produzione
// same-origin il valore è vuoto: le chiamate API vanno a "/api/*" sullo
// stesso dominio (via Traefik), quindi niente CORS e cookie same-site.
window.MELPIS_API_BASE = "${MELPIS_API_BASE}";