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

// In produzione e con reverse proxy Nginx same-origin, MELPIS_API_BASE è vuota:
// tutte le richieste API usano path relativi /api/...
window.MELPIS_API_BASE = "";
