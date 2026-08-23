/* ============================================================
   PAGINA /ACCEDI/ — login email/password e Google (BFF)
   ============================================================
   Il JS invia email+password a /api/auth/login: il backend
   scambia le credenziali con Supabase Auth e imposta i cookie
   HttpOnly. Nessun token tocca il browser.
   ============================================================ */

/* ── Messaggi d'errore da query string (?errore=google) ──── */
if (AUTH_PARAMS.get("errore") === "google") {
  mostraErrorePagina(
    "Accesso con Google non riuscito o annullato. Riprova oppure usa email e password."
  );
}

/* ── Link incrociati e pulsante Google, preservando ?next= ─ */
document.getElementById("link-registrati")?.setAttribute("href", urlConNext("/registrati/"));
collegaGoogle();

/* ── Login email/password ────────────────────────────────── */
document.getElementById("form-login")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("accesso-email").value.trim();
  const password = document.getElementById("accesso-password").value;
  const errEl = document.getElementById("accesso-error");
  if (!email || !password) {
    errEl.textContent = "Compila entrambi i campi.";
    return;
  }
  const btn = document.getElementById("accesso-save");
  btn.disabled = true;
  try {
    const res = await fetch(`${AUTH_API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Credenziali non valide.");
    }
    vaiADestinazione();
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});
