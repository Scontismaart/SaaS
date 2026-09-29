/* ============================================================
   PAGINA /REGISTRATI/ — registrazione account (BFF)
   ============================================================
   Validazione client specchiata da quella server (register.py):
   email sintattica, password >= 10 caratteri con almeno un
   simbolo. Lo strength meter è feedback visivo in tempo reale,
   la regola vincolante resta quella server-side.
   ============================================================ */

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PASSWORD_MIN = 10;

/* ── Link incrociati e Google, preservando ?next= ────────── */
const loginLink = document.getElementById("link-accedi");
const loginBase = loginLink ? (loginLink.getAttribute("href") || "/accedi/").split("?")[0] : "/accedi/";
loginLink?.setAttribute("href", urlConNext(loginBase));

const successLoginLink = document.getElementById("success-login-link");
const successLoginBase = successLoginLink ? (successLoginLink.getAttribute("href") || "/accedi/").split("?")[0] : "/accedi/";
successLoginLink?.setAttribute("href", urlConNext(successLoginBase));
collegaGoogle();

/* ── Strength meter: feedback live, niente librerie esterne ─ */
const pwInput = document.getElementById("reg-password");
const pwBar = document.getElementById("pw-bar");
const pwChecks = {
  len: document.querySelector('[data-check="len"]'),
  special: document.querySelector('[data-check="special"]'),
  upper: document.querySelector('[data-check="upper"]'),
  num: document.querySelector('[data-check="num"]'),
};

function aggiornaMeter() {
  const v = pwInput.value;
  const stato = {
    len: v.length >= PASSWORD_MIN,
    special: /[^A-Za-z0-9]/.test(v),
    upper: /[A-Z]/.test(v),
    num: /[0-9]/.test(v),
  };
  let punteggio = 0;
  for (const [k, ok] of Object.entries(stato)) {
    pwChecks[k]?.classList.toggle("done", ok);
    if (ok) punteggio += 1;
  }
  // I requisiti obbligatori pesano di più: senza di loro la barra non supera il giallo.
  const livello = Math.max(1, Math.min(4, punteggio));
  pwBar.className = "pw-meter-bar" + (punteggio > 0 ? ` pw-${livello}` : "");
  pwBar.style.width = `${(punteggio / 4) * 100}%`;
}
pwInput?.addEventListener("input", aggiornaMeter);

/* ── Submit registrazione ────────────────────────────────── */
document.getElementById("form-register")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const errEl = document.getElementById("register-error");
  const okEl = document.getElementById("register-success");
  clearAuthFieldError(e.currentTarget, errEl);
  okEl.hidden = true;

  const nomeAttivita = document.getElementById("reg-nome").value.trim();
  const email = document.getElementById("reg-email").value.trim();
  const password = document.getElementById("reg-password").value;
  const termini = document.getElementById("reg-termini").checked;

  // Stesse regole del server (register.py): messaggi chiari ma che non
  // rivelano nulla sugli account esistenti.
  if (!nomeAttivita) return showAuthFieldError(errEl, getAuthMessage("enter_business_name"), document.getElementById("reg-nome"));
  if (!EMAIL_RE.test(email)) return showAuthFieldError(errEl, getAuthMessage("invalid_email"), document.getElementById("reg-email"));
  if (password.length < PASSWORD_MIN) return showAuthFieldError(errEl, getAuthMessage("password_too_short"), document.getElementById("reg-password"));
  if (!/[^A-Za-z0-9]/.test(password)) return showAuthFieldError(errEl, getAuthMessage("password_special"), document.getElementById("reg-password"));
  if (!termini) return showAuthFieldError(errEl, getAuthMessage("accept_terms"), document.getElementById("reg-termini"));

  const btn = document.getElementById("register-save");
  btn.disabled = true;
  try {
    const res = await fetch(`${AUTH_API_BASE}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password, nome_attivita: nomeAttivita }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || getAuthMessage("register_failed"));
    }
    if (data.email_verified) {
      // Sessione attiva (auto-confirm): le cookie sono già impostate.
      sessionStorage.setItem("melpis_benvenuto", "1");
      vaiADestinazione();
      return;
    }
    // Verifica email obbligatoria: nessuna sessione finché non conferma.
    okEl.hidden = false;
    okEl.focus();
  } catch (err) {
    showAuthFieldError(errEl, err.message);
  } finally {
    btn.disabled = false;
  }
});
document.getElementById("form-register")?.addEventListener("input", (e) => {
  if (e.target.matches("input")) clearAuthFieldError(e.currentTarget, document.getElementById("register-error"));
});
