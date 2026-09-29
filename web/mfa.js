/* Minimal Supabase TOTP enrollment and step-up UI for the BFF session. */
(function (global) {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const state = {
    aal: "aal1",
    factors: [],
    pendingFactorId: null,
    activeFactorId: null,
    challengeId: null,
    stepUpRequested: false,
    loadPromise: null,
  };

  function tr(key, fallback) {
    const value = typeof global.t === "function" ? global.t(`settings:mfa.${key}`) : null;
    return value && value !== `settings:mfa.${key}` ? value : fallback;
  }

  function status(id, message, kind = "info") {
    const el = byId(id);
    if (!el) return;
    el.textContent = message;
    el.classList.toggle("err", kind === "error");
    el.classList.toggle("ok", kind === "success");
  }

  function show(id, visible) {
    const el = byId(id);
    if (el) el.hidden = !visible;
  }

  function clearEnrollmentSecrets() {
    state.pendingFactorId = null;
    const qr = byId("security-mfa-qr");
    const secret = byId("security-mfa-secret");
    const code = byId("security-mfa-enrollment-code");
    if (qr) {
      qr.removeAttribute("src");
      qr.hidden = true;
    }
    if (secret) secret.textContent = "";
    if (code) code.value = "";
    show("security-mfa-enrollment", false);
  }

  function clearChallenge() {
    state.activeFactorId = null;
    state.challengeId = null;
    const code = byId("security-mfa-challenge-code");
    if (code) code.value = "";
    show("security-mfa-challenge", false);
  }

  function errorMessage(statusCode) {
    if (statusCode === 401) return tr("session_expired", "La sessione è scaduta. Accedi di nuovo.");
    if (statusCode === 409) return tr("conflict", "Controlla lo stato della configurazione MFA e riprova.");
    if (statusCode === 422) return tr("code_invalid", "Codice errato o scaduto. Controlla l'app e riprova.");
    if (statusCode === 429) return tr("rate_limited", "Troppe richieste. Attendi qualche minuto e riprova.");
    if (statusCode === 403) return tr("not_allowed", "La sessione non può completare questa operazione.");
    if (statusCode === 428) return tr("recent_auth_required", "Per configurare l'autenticatore, esci e accedi di nuovo; completa la configurazione entro 5 minuti.");
    return tr("request_error", "Non è stato possibile completare l'operazione MFA. Riprova.");
  }

  async function request(path, options = {}) {
    if (!global.MelpisAPI || typeof global.MelpisAPI.fetch !== "function") {
      throw new Error(tr("request_error", "Non è stato possibile completare l'operazione MFA. Riprova."));
    }
    let response;
    try {
      response = await global.MelpisAPI.fetch(`${global.MelpisAPI.base || ""}/api/auth/mfa${path}`, options);
    } catch (_) {
      throw new Error(tr("request_error", "Non è stato possibile completare l'operazione MFA. Riprova."));
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(errorMessage(response.status));
    return data;
  }

  function renderFactors() {
    const list = byId("security-mfa-factors");
    if (!list) return;
    list.replaceChildren();
    const verified = state.factors.filter((factor) => factor.status === "verified");
    const pending = state.factors.filter((factor) => factor.status === "unverified");

    for (const factor of verified) {
      const row = document.createElement("div");
      row.className = "security-mfa-factor";
      const label = document.createElement("span");
      label.textContent = factor.friendly_name || tr("authenticator", "App authenticator");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn-link-action";
      button.textContent = tr("challenge_start", "Verifica per operazioni sensibili");
      button.addEventListener("click", () => startChallenge(factor.id));
      row.append(label, button);
      list.appendChild(row);
    }

    for (const factor of pending) {
      const row = document.createElement("div");
      row.className = "security-mfa-factor";
      const label = document.createElement("span");
      label.textContent = tr("pending_factor", "Configurazione non completata");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "btn-link-action";
      button.textContent = tr("cancel_restart", "Annulla e ricomincia");
      button.addEventListener("click", () => cancelPending(factor.id));
      row.append(label, button);
      list.appendChild(row);
    }

    const canEnroll = verified.length === 0 && pending.length === 0;
    show("security-mfa-enroll-start", canEnroll);
    if (verified.length) {
      status("security-mfa-status", state.aal === "aal2"
        ? tr("active_aal2", "App authenticator attiva; sessione verificata.")
        : tr("active_aal1", "App authenticator attiva. Verifica il codice per autorizzare le operazioni sensibili."), state.aal === "aal2" ? "success" : "info");
    } else if (pending.length) {
      status("security-mfa-status", tr("pending_status", "Completa o annulla la configurazione MFA in sospeso."));
    } else {
      status("security-mfa-status", tr("inactive", "Verifica in due passaggi non ancora configurata."));
    }
  }

  async function loadStatus() {
    if (state.loadPromise) return state.loadPromise;
    state.loadPromise = (async () => {
      status("security-mfa-status", tr("loading", "Controllo dello stato MFA…"));
      try {
        const result = await request("");
        state.aal = result.aal === "aal2" ? "aal2" : "aal1";
        state.factors = Array.isArray(result.factors) ? result.factors : [];
        renderFactors();
        const stepUp = state.stepUpRequested;
        state.stepUpRequested = false;
        if (stepUp) {
          const factor = state.factors.find((item) => item.status === "verified");
          if (factor) await startChallenge(factor.id);
          else if (!state.factors.some((item) => item.status === "unverified")) {
            status("security-mfa-status", tr("enroll_to_continue", "Configura un'app authenticator per proseguire con l'operazione sensibile."));
          }
        }
      } catch (err) {
        status("security-mfa-status", err.message, "error");
      }
    })().finally(() => { state.loadPromise = null; });
    return state.loadPromise;
  }

  async function startEnrollment() {
    const button = byId("security-mfa-enroll-start");
    if (button) button.disabled = true;
    status("security-mfa-enrollment-status", tr("enroll_loading", "Avvio configurazione…"));
    try {
      const result = await request("/enroll", { method: "POST", headers: { "Content-Type": "application/json" } });
      if (!result.factor_id || !/^data:image\/svg\+xml(?:;utf-8,|;base64,)/.test(result.qr_code || "") || !result.secret) {
        throw new Error(tr("request_error", "Non è stato possibile completare l'operazione MFA. Riprova."));
      }
      state.pendingFactorId = result.factor_id;
      const qr = byId("security-mfa-qr");
      qr.src = result.qr_code;
      qr.alt = tr("qr_alt", "Codice QR per configurare l'app authenticator");
      qr.hidden = false;
      byId("security-mfa-secret").textContent = result.secret;
      show("security-mfa-enrollment", true);
      status("security-mfa-enrollment-status", "");
      byId("security-mfa-enrollment-code")?.focus();
    } catch (err) {
      await loadStatus();
      status("security-mfa-status", err.message, "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function createChallenge(factorId) {
    const result = await request("/challenge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ factor_id: factorId }),
    });
    if (!result.challenge_id) throw new Error(tr("request_error", "Non è stato possibile completare l'operazione MFA. Riprova."));
    return result.challenge_id;
  }

  async function startChallenge(factorId) {
    status("security-mfa-challenge-status", tr("challenge_loading", "Preparo la verifica…"));
    try {
      state.activeFactorId = factorId;
      state.challengeId = await createChallenge(factorId);
      show("security-mfa-challenge", true);
      status("security-mfa-challenge-status", "");
      byId("security-mfa-challenge-code")?.focus();
    } catch (err) {
      status("security-mfa-status", err.message, "error");
      show("security-mfa-challenge", false);
    }
  }

  async function verifyCode(event, purpose) {
    event.preventDefault();
    const enrollment = purpose === "enroll";
    const codeInput = byId(enrollment ? "security-mfa-enrollment-code" : "security-mfa-challenge-code");
    const form = byId(enrollment ? "security-mfa-enrollment-form" : "security-mfa-challenge-form");
    const statusId = enrollment ? "security-mfa-enrollment-status" : "security-mfa-challenge-status";
    const factorId = enrollment ? state.pendingFactorId : state.activeFactorId;
    const code = (codeInput?.value || "").replace(/\s/g, "");
    const submit = form?.querySelector('button[type="submit"]');
    if (!factorId || !/^\d{6}$/.test(code)) {
      status(statusId, tr("code_invalid", "Codice errato o scaduto. Controlla l'app e riprova."), "error");
      return;
    }
    if (submit) submit.disabled = true;
    status(statusId, tr("verify_loading", "Verifica in corso…"));
    try {
      const challengeId = enrollment ? await createChallenge(factorId) : state.challengeId;
      if (!challengeId) throw new Error(tr("request_error", "Non è stato possibile completare l'operazione MFA. Riprova."));
      await request("/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ factor_id: factorId, challenge_id: challengeId, code }),
      });
      clearEnrollmentSecrets();
      clearChallenge();
      state.aal = "aal2";
      await loadStatus();
      status("security-mfa-status", enrollment
        ? tr("verified_success", "Verifica completata. La sessione è aggiornata.")
        : tr("retry_action", "Verifica completata. Riprova l'operazione che ha richiesto il codice."), "success");
    } catch (err) {
      status(statusId, err.message, "error");
      if (err.message === tr("code_invalid", "Codice errato o scaduto. Controlla l'app e riprova.")) {
        try {
          if (!enrollment && state.activeFactorId) state.challengeId = await createChallenge(state.activeFactorId);
        } catch (_) {
          clearChallenge();
        }
      }
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function cancelPending(factorId) {
    try {
      await request(`/factors/${encodeURIComponent(factorId)}`, { method: "DELETE" });
      if (state.pendingFactorId === factorId) clearEnrollmentSecrets();
      status("security-mfa-status", tr("cancelled", "Configurazione annullata."), "success");
      await loadStatus();
    } catch (err) {
      status("security-mfa-status", err.message, "error");
    }
  }

  function openForStepUp() {
    state.stepUpRequested = true;
    if (typeof global.apriVistaImpostazioni === "function") {
      global.apriVistaImpostazioni("sicurezza");
    } else {
      show("security-mfa-card", true);
    }
    loadStatus();
  }

  byId("security-mfa-enroll-start")?.addEventListener("click", startEnrollment);
  byId("security-mfa-enrollment-form")?.addEventListener("submit", (event) => verifyCode(event, "enroll"));
  byId("security-mfa-challenge-form")?.addEventListener("submit", (event) => verifyCode(event, "challenge"));
  byId("security-mfa-enrollment-cancel")?.addEventListener("click", async () => {
    const factorId = state.pendingFactorId;
    if (factorId) await cancelPending(factorId);
    clearEnrollmentSecrets();
    status("security-mfa-enrollment-status", "");
  });
  byId("security-mfa-challenge-cancel")?.addEventListener("click", () => {
    clearChallenge();
    status("security-mfa-challenge-status", "");
  });
  global.addEventListener("pagehide", () => {
    clearEnrollmentSecrets();
    clearChallenge();
  });

  global.MelpisMfa = { loadStatus, openForStepUp };
})(window);
