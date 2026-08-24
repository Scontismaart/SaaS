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

/* ============================================================
   RECUPERO PASSWORD — recover (richiesta link) + reset
   ============================================================
   Due stati aggiuntivi della pagina /accedi/:
   - recover: l'utente chiede il link via email (POST /api/auth/recover);
   - reset: arriva dal link email di Supabase con #access_token=...&
     type=recovery nell'hash → nuova password (POST /api/auth/reset).
   Il token recovery viaggia solo in questa richiesta POST e non viene
   mai salvato: dopo la lettura l'hash viene rimosso dall'URL.
   ============================================================ */

function leggiCookie(nome) {
  const m = document.cookie.match(new RegExp(`(?:^|;\\s*)${nome}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : "";
}

async function postAuth(path, body) {
  // Se per qualche motivo esiste ancora una sessione/cookie CSRF, il
  // middleware richiede anche l'header X-CSRF-Token sui POST.
  const headers = { "Content-Type": "application/json" };
  const csrf = leggiCookie("wa_csrf");
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return fetch(`${AUTH_API_BASE}${path}`, {
    method: "POST",
    headers,
    credentials: "include",
    body: JSON.stringify(body),
  });
}

const HASH_PARAMS = new URLSearchParams(window.location.hash.replace(/^#/, ""));
const RECOVERY_TOKEN =
  HASH_PARAMS.get("type") === "recovery" ? HASH_PARAMS.get("access_token") : null;

if (RECOVERY_TOKEN) {
  /* Stato RESET: il link email rimanda qui con il token recovery. */
  history.replaceState(null, "", window.location.pathname + window.location.search);
  document.getElementById("form-login").hidden = true;
  document.getElementById("forgot-link-row").hidden = true;
  document.getElementById("google-btn").hidden = true;
  document.querySelector(".accedi-divider").hidden = true;
  document.getElementById("accesso-title").textContent = "Nuova password";
  document.getElementById("accesso-help").textContent =
    "Scegli una nuova password per il tuo account.";
  document.getElementById("form-reset").hidden = false;

  document.getElementById("form-reset").addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = document.getElementById("reset-status");
    const pwd = document.getElementById("reset-password").value;
    if (!pwd) {
      status.textContent = "Inserisci la nuova password.";
      return;
    }
    const btn = document.getElementById("reset-save");
    btn.disabled = true;
    try {
      const res = await postAuth("/api/auth/reset", {
        access_token: RECOVERY_TOKEN,
        password: pwd,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Aggiornamento non riuscito.");
      }
      status.textContent =
        "Password aggiornata. Ora puoi accedere con la nuova password.";
      document.getElementById("form-reset").hidden = true;
      document.getElementById("form-login").hidden = false;
      document.getElementById("forgot-link-row").hidden = false;
      document.getElementById("accesso-title").textContent = "Accedi a Melpis";
      document.getElementById("accesso-help").textContent =
        "Gestisci assistente, prenotazioni e documenti da un unico pannello.";
      document.getElementById("accesso-password").focus();
    } catch (err) {
      status.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });
} else {
  /* Stati LOGIN ↔ RECOVER (solo se non siamo in modalità reset). */
  const formLogin = document.getElementById("form-login");
  const formRecover = document.getElementById("form-recover");

  document.getElementById("forgot-link").addEventListener("click", (e) => {
    e.preventDefault();
    formLogin.hidden = true;
    document.querySelector(".accedi-divider").hidden = true;
    document.getElementById("google-btn").hidden = true;
    document.getElementById("forgot-link-row").hidden = true;
    document.getElementById("accesso-title").textContent = "Recupera password";
    document.getElementById("accesso-help").textContent =
      "Ti invieremo un link per impostare una nuova password.";
    formRecover.hidden = false;
    document.getElementById("recover-email").focus();
  });

  document.getElementById("recover-back").addEventListener("click", (e) => {
    e.preventDefault();
    window.location.reload();
  });

  formRecover.addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = document.getElementById("recover-status");
    const email = document.getElementById("recover-email").value.trim();
    if (!email) {
      status.textContent = "Inserisci la tua email.";
      return;
    }
    const btn = document.getElementById("recover-save");
    btn.disabled = true;
    try {
      const res = await postAuth("/api/auth/recover", { email });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Richiesta non riuscita.");
      }
      const body = await res.json().catch(() => ({}));
      // Messaggio neutro: non rivela se l'email è registrata o meno.
      status.textContent =
        body.message ||
        "Se l'email e' registrata riceverai un link di recupero.";
      formRecover.querySelector(".onboarding-actions").hidden = true;
    } catch (err) {
      status.textContent = err.message;
    } finally {
      btn.disabled = false;
    }
  });
}
