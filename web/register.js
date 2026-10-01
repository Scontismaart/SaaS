/* ============================================================
   PAGINA /REGISTRATI/ — avvio registrazione account (BFF)
   ============================================================
   La password scelta viene inviata solo al BFF e custodita in un capsule
   cifrato fino alla conferma della casella email.
   L'endpoint restituisce la stessa conferma generica per evitare di
   rivelare se un indirizzo è già registrato.
   ============================================================ */

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const PASSWORD_MIN = 10;
const PASSWORD_MAX = 256;

function checkPassword(value) {
  return {
    len: value.length >= PASSWORD_MIN && value.length <= PASSWORD_MAX,
    special: /[^A-Za-z0-9]/.test(value),
    upper: /[A-Z]/.test(value),
    num: /[0-9]/.test(value),
  };
}

function updatePasswordMeter(value) {
  const checks = checkPassword(value);
  let score = 0;
  for (const [name, valid] of Object.entries(checks)) {
    const item = document.querySelector(`#password-rules [data-check="${name}"]`);
    item?.classList.toggle("done", valid);
    if (valid) score += 1;
  }
  const bar = document.getElementById("pw-bar");
  if (bar) bar.className = `pw-meter-bar${score ? ` pw-${score}` : ""}`;
  return Object.values(checks).every(Boolean);
}

function signupNext() {
  const matches = new URLSearchParams(window.location.search).getAll("next");
  if (matches.length !== 1) return undefined;
  return matches[0];
}

/* ── Link incrociati e Google, preservando ?next= ────────── */
const loginLink = document.getElementById("link-accedi");
const loginBase = loginLink ? (loginLink.getAttribute("href") || "/accedi/").split("?")[0] : "/accedi/";
loginLink?.setAttribute("href", urlConNext(loginBase));

const successLoginLink = document.getElementById("success-login-link");
const successLoginBase = successLoginLink ? (successLoginLink.getAttribute("href") || "/accedi/").split("?")[0] : "/accedi/";
successLoginLink?.setAttribute("href", urlConNext(successLoginBase));
collegaGoogle();

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

  if (!nomeAttivita) return showAuthFieldError(errEl, getAuthMessage("enter_business_name"), document.getElementById("reg-nome"));
  if (!EMAIL_RE.test(email)) return showAuthFieldError(errEl, getAuthMessage("invalid_email"), document.getElementById("reg-email"));
  if (!updatePasswordMeter(password)) {
    const missingRules = [...document.querySelectorAll("#password-rules li:not(.done)")]
      .map((item) => item.textContent.trim())
      .join(" · ");
    return showAuthFieldError(errEl, missingRules, document.getElementById("reg-password"));
  }
  if (!termini) return showAuthFieldError(errEl, getAuthMessage("accept_terms"), document.getElementById("reg-termini"));

  const btn = document.getElementById("register-save");
  btn.disabled = true;
  try {
    const requestBody = { email, nome_attivita: nomeAttivita, password };
    const requestedNext = signupNext();
    if (requestedNext !== undefined) requestBody.next = requestedNext;
    const res = await fetch(`${AUTH_API_BASE}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(requestBody),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || getAuthMessage("register_failed"));
    }
    okEl.hidden = false;
    okEl.focus();
  } catch (err) {
    showAuthFieldError(errEl, err.message);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById("form-register")?.addEventListener("input", (e) => {
  if (e.target.matches("#reg-password")) updatePasswordMeter(e.target.value);
  if (e.target.matches("input")) clearAuthFieldError(e.currentTarget, document.getElementById("register-error"));
});
