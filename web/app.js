const API_BASE = window.MELPIS_API_BASE ?? "http://localhost:8000";
const PROFILO_ID = "trattoria_da_mario";

/* ============================================================
   AUTENTICAZIONE — BFF (task18)
   ============================================================
   Il frontend NON gestisce token: invia email+password a
   /api/auth/login, il backend (BFF) scambia le credenziali con
   Supabase Auth e salva la sessione in cookie HttpOnly+Secure+
   SameSite=Strict. Il JS manda solo fetch con credentials: i
   cookie viaggiano da soli, mai token in localStorage o header.
   Su 401 si tenta un refresh (/api/auth/refresh) e si riprova
   una volta; se anche il refresh fallisce si torna al login.
   ============================================================ */

let sessione = null; // { email, organization_id, ruolo } | null

function _sanitize(v) {
  if (typeof DOMPurify !== "undefined") {
    return DOMPurify.sanitize(v == null ? "" : String(v));
  }
  return String(v == null ? "" : v);
}

function leggiCookie(nome) {
  return document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${nome}=`))
    ?.slice(nome.length + 1) || "";
}

function csrfToken() {
  return decodeURIComponent(leggiCookie("__Host-wa_csrf") || leggiCookie("wa_csrf"));
}

async function apiFetch(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  let res = await fetch(url, { ...options, headers, credentials: "include" });
  if (res.status === 401 && !url.includes("/api/auth/")) {
    const refreshRes = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: csrfToken() ? { "X-CSRF-Token": csrfToken() } : {},
      credentials: "include",
    });
    if (refreshRes.ok) {
      res = await fetch(url, { ...options, headers, credentials: "include" });
    } else {
      sessione = null;
      aggiornaBottoneAccesso();
      apriConfigAccesso();
    }
  }
  return res;
}

function aggiornaBottoneAccesso() {
  const btn = document.getElementById("accesso-btn");
  if (!btn) return;
  if (sessione) {
    btn.textContent = sessione.email || "Esci";
    btn.title = "Esci";
  } else {
    btn.textContent = "Accedi";
    btn.title = "Accedi";
  }
}

async function caricaSessione() {
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
    if (!res.ok) {
      sessione = null;
      aggiornaBottoneAccesso();
      return false;
    }
    sessione = await res.json();
    aggiornaBottoneAccesso();
    return true;
  } catch {
    sessione = null;
    aggiornaBottoneAccesso();
    return false;
  }
}

function apriConfigAccesso() {
  document.getElementById("accesso-modal").hidden = false;
  document.getElementById("accesso-error").textContent = "";
}

function chiudiConfigAccesso() {
  document.getElementById("accesso-modal").hidden = true;
}

async function faiLogin(email, password) {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || "Credenziali non valide.");
  }
  await caricaSessione();
}

async function faiLogout() {
  try {
    await apiFetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
    });
  } catch { /* best effort */ }
  sessione = null;
  aggiornaBottoneAccesso();
}

document.getElementById("accesso-btn")?.addEventListener("click", () => {
  if (sessione) {
    faiLogout().then(() => {
      window.location.reload();
    });
  } else {
    apriConfigAccesso();
  }
});

document.getElementById("accesso-save")?.addEventListener("click", async () => {
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
    await faiLogin(email, password);
    chiudiConfigAccesso();
    window.location.reload();
  } catch (err) {
    errEl.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

document.querySelectorAll("[data-accesso-close]").forEach((el) => {
  el.addEventListener("click", () => chiudiConfigAccesso());
});

/* ============================================================
   SIDEBAR / NAVIGATION
   ============================================================ */

const navItems = document.querySelectorAll(".nav-item");
const topbarTitle = document.getElementById("topbar-title");
const topbarDate = document.getElementById("topbar-date");
const views = document.querySelectorAll(".view");
const NOTIFICATION_STORAGE_KEY = "restaurant-dashboard-notifications-v1";
const notificationBadges = document.querySelectorAll("[data-notification-badge]");
let notificationItems = {
  panoramica: 0,
  assistente: 0,
  recensioni: 0,
  prenotazioni: 0,
  documenti: 0,
  report: 0,
  inbox: 0,
};

function leggiStatoNotifiche() {
  try {
    return JSON.parse(localStorage.getItem(NOTIFICATION_STORAGE_KEY) || "null") || { inizializzato: false, viste: {} };
  } catch {
    return { inizializzato: false, viste: {} };
  }
}

function salvaStatoNotifiche(stato) {
  try { localStorage.setItem(NOTIFICATION_STORAGE_KEY, JSON.stringify(stato)); } catch { /* storage non disponibile */ }
}

function aggiornaBadgeNotifiche(stato) {
  notificationBadges.forEach((badge) => {
    const key = badge.dataset.notificationBadge;
    const totale = Number(notificationItems[key] || 0);
    const viste = Number(stato.viste?.[key] || 0);
    const nonViste = Math.max(0, totale - viste);
    badge.textContent = nonViste > 99 ? "99+" : String(nonViste);
    badge.hidden = nonViste === 0;
  });
}

function segnaNotificheViste(viewName) {
  const stato = leggiStatoNotifiche();
  stato.viste = stato.viste || {};
  stato.viste[viewName] = notificationItems[viewName] || 0;
  salvaStatoNotifiche(stato);
  aggiornaBadgeNotifiche(stato);
}

async function aggiornaNotifiche() {
  try {
    const [summaryResponse, reportResponse] = await Promise.all([
      apiFetch(`${API_BASE}/api/ui/summary`),
      apiFetch(`${API_BASE}/api/report/stato`),
    ]);
    const summary = summaryResponse.ok ? await summaryResponse.json() : {};
    const report = reportResponse.ok ? await reportResponse.json() : { disponibile: false };
    notificationItems = {
      panoramica: Number(summary.inbox_attivi || 0) + Number(summary.recensioni_da_approvare || 0),
      assistente: 0,
      recensioni: summary.recensioni_da_approvare || 0,
      prenotazioni: summary.prenotazioni || 0,
      documenti: summary.documenti || 0,
      report: report.disponibile ? 1 : 0,
      inbox: summary.inbox_attivi || 0,
    };
    const stato = leggiStatoNotifiche();
    if (!stato.inizializzato) {
      stato.inizializzato = true;
      stato.viste = { ...notificationItems };
      salvaStatoNotifiche(stato);
    }
    aggiornaBadgeNotifiche(stato);
  } catch (err) {
    console.error("Impossibile aggiornare le notifiche:", err);
  }
}

topbarDate.textContent = new Date().toLocaleDateString("it-IT", {
  day: "numeric",
  month: "long",
  year: "numeric",
});

navItems.forEach((btn) => {
  btn.addEventListener("click", async () => {
    const viewName = btn.dataset.view;
    segnaNotificheViste(viewName);

    navItems.forEach((n) => n.classList.remove("active"));
    btn.classList.add("active");

    views.forEach((v) => {
      v.classList.toggle("view-hidden", v.dataset.viewPanel !== viewName);
    });

    const titles = {
      panoramica: "Panoramica",
      onboarding: "Onboarding",
      assistente: "Assistente",
      recensioni: "Recensioni",
      prenotazioni: "Prenotazioni",
      report: "Report",
      documenti: "Documenti",
      inbox: "Inbox",
    };
    topbarTitle.textContent = titles[viewName] || viewName;

    if (viewName === "panoramica") {
      aggiornaRiepilogo();
      aggiornaPrioritari();
    }
    if (viewName === "onboarding") {
      inizializzaOnboarding();
    }
    if (viewName === "recensioni") {
      aggiornaTrends();
    }
    if (viewName === "prenotazioni") {
      await aggiornaImpostazioniPrenotazioni();
      inizializzaCalendarioPrenotazioni();
      aggiornaPrenotazioni();
      aggiornaSemaforo();
    }
    if (viewName === "documenti") {
      aggiornaConteggio();
      aggiornaDocumenti();
    }
    if (viewName === "inbox") {
      avviaInboxPolling();
      caricaInbox();
    } else {
      fermaInboxPolling();
    }
  });
});

/* ============================================================
   ONBOARDING
   ============================================================ */

const onboardingState = {
  loaded: false,
  step: 0,
  verticals: [],
  selectedVertical: "ristorante",
  extraRules: [],
  lingue: ["it"],
  linguaDefault: "it",
  lingueDisponibili: ["it", "en", "fr", "de", "es"],
  profileLoaded: false,
};

const LINGUE_DEFAULT_PER_VERTICALE = {
  hotel_bnb: ["it", "en", "fr", "de", "es"],
  ristorante: ["it", "en", "fr", "de", "es"],
  centro_estetico: ["it", "en", "fr", "de"],
  parrucchiere: ["it", "en", "fr"],
  studio_medico_dentista: ["it", "en"],
};

const onboardingEls = {
  steps: document.querySelectorAll("[data-onboarding-step]"),
  pages: document.querySelectorAll("[data-onboarding-page]"),
  progress: document.getElementById("onboarding-progress-bar"),
  verticalGrid: document.getElementById("vertical-grid"),
  name: document.getElementById("onboarding-name"),
  hours: document.getElementById("onboarding-hours"),
  tone: document.getElementById("onboarding-tone"),
  services: document.getElementById("onboarding-services"),
  lingueGrid: document.getElementById("lingue-grid"),
  linguaDefault: document.getElementById("lingua-default"),
  escalationList: document.getElementById("escalation-list"),
  extraRule: document.getElementById("onboarding-extra-rule"),
  addRule: document.getElementById("onboarding-add-rule"),
  previewBtn: document.getElementById("onboarding-preview-btn"),
  previewText: document.getElementById("onboarding-preview-text"),
  whatsapp: document.getElementById("onboarding-whatsapp"),
  docs: document.getElementById("onboarding-docs"),
  docFile: document.getElementById("onboarding-doc-file"),
  uploadDoc: document.getElementById("onboarding-doc-upload"),
  docStatus: document.getElementById("onboarding-doc-status"),
  openDocs: document.getElementById("onboarding-open-docs"),
  testMessage: document.getElementById("onboarding-test-message"),
  testBtn: document.getElementById("onboarding-test-btn"),
  testOutput: document.getElementById("onboarding-test-output"),
  status: document.getElementById("onboarding-status"),
  prev: document.getElementById("onboarding-prev"),
  next: document.getElementById("onboarding-next"),
};

function verticaleCorrente() {
  return onboardingState.verticals.find((v) => v.id === onboardingState.selectedVertical) || onboardingState.verticals[0];
}

function righeDaTextarea(value) {
  return value.split("\n").map((r) => r.trim()).filter(Boolean);
}

function lingueSelezionate() {
  const inputs = [...document.querySelectorAll(".onboarding-lang:checked")];
  return inputs.length ? inputs.map((i) => i.value) : onboardingState.lingue;
}

function renderLingue() {
  if (!onboardingEls.lingueGrid) return;
  onboardingEls.lingueGrid.innerHTML = "";
  onboardingState.lingueDisponibili.forEach((lang) => {
    const label = document.createElement("label");
    label.className = "wizard-check";
    const checked = onboardingState.lingue.includes(lang);
    const locked = lang === "it";
    label.innerHTML = `<input class="onboarding-lang" type="checkbox" value="${_sanitize(lang)}" ${checked ? "checked" : ""} ${locked ? "disabled" : ""}> ${_sanitize(lang.toUpperCase())}`;
    label.querySelector("input").addEventListener("change", () => {
      onboardingState.lingue = lingueSelezionate();
      aggiornaDefaultLingua();
    });
    onboardingEls.lingueGrid.appendChild(label);
  });
  aggiornaDefaultLingua();
}

function aggiornaDefaultLingua() {
  if (!onboardingEls.linguaDefault) return;
  const selezionate = lingueSelezionate();
  onboardingEls.linguaDefault.innerHTML = "";
  selezionate.forEach((lang) => {
    const opt = document.createElement("option");
    opt.value = lang;
    opt.textContent = lang.toUpperCase();
    opt.selected = lang === onboardingState.linguaDefault;
    onboardingEls.linguaDefault.appendChild(opt);
  });
  if (!selezionate.includes(onboardingState.linguaDefault)) {
    onboardingState.linguaDefault = "it";
    [...onboardingEls.linguaDefault.options].forEach((o) => {
      o.selected = o.value === "it";
    });
  }
}

function profiloOnboarding() {
  const vertical = verticaleCorrente();
  return {
    verticale: onboardingState.selectedVertical,
    nome_attivita: onboardingEls.name.value.trim() || "Nuova attivita",
    orari: onboardingEls.hours.value.trim() || "Orari da configurare",
    tono: onboardingEls.tone.value.trim() || vertical?.tono || "",
    servizi: righeDaTextarea(onboardingEls.services.value),
    regole_escalation: [...document.querySelectorAll(".onboarding-rule:checked")].map((input) => input.value),
    whatsapp_collegato: Boolean(onboardingEls.whatsapp?.checked),
    documenti_importati: Boolean(onboardingEls.docs?.checked),
    lingue_supportate: lingueSelezionate(),
    lingua_default: onboardingEls.linguaDefault?.value || onboardingState.linguaDefault,
  };
}

function renderOnboardingStep() {
  onboardingEls.steps.forEach((step) => {
    step.classList.toggle("active", Number(step.dataset.onboardingStep) === onboardingState.step);
  });
  onboardingEls.pages.forEach((page) => {
    page.hidden = Number(page.dataset.onboardingPage) !== onboardingState.step;
  });
  if (onboardingEls.progress) {
    onboardingEls.progress.style.width = `${((onboardingState.step + 1) / 7) * 100}%`;
  }
  onboardingEls.prev.disabled = onboardingState.step === 0;
  onboardingEls.next.textContent = onboardingState.step === 6 ? "Completa" : "Avanti";
}

function renderVerticals() {
  onboardingEls.verticalGrid.innerHTML = "";
  onboardingState.verticals.forEach((vertical) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "vertical-card";
    card.classList.toggle("active", vertical.id === onboardingState.selectedVertical);
    card.innerHTML = `<strong>${_sanitize(vertical.label)}</strong><span>${_sanitize(vertical.servizi.slice(0, 3).join(", "))}</span>`;
    card.addEventListener("click", () => {
      onboardingState.selectedVertical = vertical.id;
      onboardingEls.tone.value = vertical.tono;
      onboardingEls.services.value = vertical.servizi.join("\n");
      onboardingEls.testMessage.value = vertical.esempio;
      onboardingState.extraRules = [];
      if (!onboardingState.profileLoaded) {
        onboardingState.lingue = LINGUE_DEFAULT_PER_VERTICALE[vertical.id] || ["it"];
        renderLingue();
      }
      renderVerticals();
      renderEscalationRules();
    });
    onboardingEls.verticalGrid.appendChild(card);
  });
}

function renderEscalationRules() {
  const vertical = verticaleCorrente();
  const rules = [...(vertical?.escalation || []), ...onboardingState.extraRules];
  onboardingEls.escalationList.innerHTML = "";
  rules.forEach((rule) => {
    const label = document.createElement("label");
    label.className = "wizard-check";
    label.innerHTML = `<input class="onboarding-rule" type="checkbox" value="${_sanitize(rule.replaceAll('"', "&quot;"))}" checked> ${_sanitize(rule)}`;
    onboardingEls.escalationList.appendChild(label);
  });
}

async function caricaProfiloOnboarding() {
  try {
    const res = await apiFetch(`${API_BASE}/api/onboarding/profilo`);
    if (res.status === 401) {
      onboardingEls.status.textContent = "Serve la config di accesso: clicca \"Configura accesso\" in alto.";
      onboardingEls.status.style.color = "var(--red)";
      return;
    }
    if (!res.ok) return;
    const data = await res.json();
    const record = data.profilo;
    if (!record) return;
    onboardingState.selectedVertical = record.verticale;
    onboardingEls.name.value = record.nome_attivita || "";
    onboardingEls.hours.value = record.orari || "";
    onboardingEls.tone.value = record.tono || "";
    onboardingEls.services.value = (record.servizi || []).join("\n");
    onboardingEls.whatsapp.checked = Boolean(record.whatsapp_collegato);
    onboardingEls.docs.checked = Boolean(record.documenti_importati);
    onboardingState.profileLoaded = true;
    onboardingState.lingue = record.lingue_supportate?.length ? record.lingue_supportate : ["it"];
    onboardingState.linguaDefault = record.lingua_default || "it";
    document.getElementById("business-name").textContent = record.nome_attivita;
    document.getElementById("chat-business-name").textContent = record.nome_attivita;
  } catch {
    /* profilo assente: wizard parte da template */
  }
}

async function inizializzaOnboarding() {
  if (onboardingState.loaded) {
    renderOnboardingStep();
    return;
  }
  if (!sessione) {
    apriConfigAccesso();
    return;
  }
  try {
    const res = await apiFetch(`${API_BASE}/api/onboarding/verticali`);
    if (res.status === 401) {
      onboardingEls.status.textContent = "Sessione scaduta: effettua di nuovo il login.";
      onboardingEls.status.style.color = "var(--red)";
      return;
    }
    if (!res.ok) throw new Error("Template verticali non disponibili");
    const data = await res.json();
    onboardingState.verticals = data.verticali || [];
    onboardingState.lingueDisponibili = data.lingue_disponibili || ["it", "en", "fr", "de", "es"];
    const first = onboardingState.verticals[0];
    if (first) {
      onboardingState.selectedVertical = first.id;
      onboardingEls.tone.value = first.tono;
      onboardingEls.services.value = first.servizi.join("\n");
      onboardingEls.testMessage.value = first.esempio;
    }
    await caricaProfiloOnboarding();
    renderVerticals();
    renderEscalationRules();
    renderLingue();
    renderOnboardingStep();
    onboardingState.loaded = true;
  } catch (err) {
    onboardingEls.status.textContent = err.message || "Errore caricamento onboarding.";
    onboardingEls.status.style.color = "var(--red)";
  }
}

async function salvaProfiloOnboarding() {
  const payload = profiloOnboarding();
  const res = await apiFetch(`${API_BASE}/api/onboarding/profilo`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail || "Errore salvataggio profilo");
  }
  const data = await res.json();
  const record = data.profilo;
  document.getElementById("business-name").textContent = record.nome_attivita;
  document.getElementById("chat-business-name").textContent = record.nome_attivita;
  return record;
}

async function generaPreviewOnboarding(targetEl, message) {
  const res = await apiFetch(`${API_BASE}/api/onboarding/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profilo: profiloOnboarding(), messaggio: message }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail || "Errore preview");
  }
  const data = await res.json();
  targetEl.textContent = data.risposta;
  return data;
}

onboardingEls.steps.forEach((step) => {
  step.addEventListener("click", () => {
    onboardingState.step = Number(step.dataset.onboardingStep);
    renderOnboardingStep();
  });
});

onboardingEls.prev?.addEventListener("click", () => {
  onboardingState.step = Math.max(0, onboardingState.step - 1);
  renderOnboardingStep();
});

onboardingEls.next?.addEventListener("click", async () => {
  if (onboardingState.step < 6) {
    onboardingState.step += 1;
    renderOnboardingStep();
    return;
  }
  onboardingEls.next.disabled = true;
  onboardingEls.status.textContent = "Salvataggio profilo...";
  try {
    await salvaProfiloOnboarding();
    onboardingEls.status.textContent = "Profilo salvato. La chat ora usa questo assistente.";
    onboardingEls.status.style.color = "var(--sage)";
  } catch (err) {
    onboardingEls.status.textContent = err.message;
    onboardingEls.status.style.color = "var(--red)";
  } finally {
    onboardingEls.next.disabled = false;
  }
});

onboardingEls.addRule?.addEventListener("click", () => {
  const rule = onboardingEls.extraRule.value.trim();
  if (!rule) return;
  onboardingState.extraRules.push(rule);
  onboardingEls.extraRule.value = "";
  renderEscalationRules();
});

onboardingEls.previewBtn?.addEventListener("click", async () => {
  onboardingEls.previewBtn.disabled = true;
  onboardingEls.previewText.textContent = "Genero anteprima...";
  try {
    await generaPreviewOnboarding(onboardingEls.previewText, verticaleCorrente()?.esempio || "Siete aperti domani?");
  } catch (err) {
    onboardingEls.previewText.textContent = err.message;
  } finally {
    onboardingEls.previewBtn.disabled = false;
  }
});

onboardingEls.testBtn?.addEventListener("click", async () => {
  onboardingEls.testBtn.disabled = true;
  onboardingEls.testOutput.textContent = "Salvo profilo e provo risposta...";
  try {
    await salvaProfiloOnboarding();
    await generaPreviewOnboarding(
      onboardingEls.testOutput,
      onboardingEls.testMessage.value.trim() || verticaleCorrente()?.esempio || "Siete aperti?"
    );
    onboardingEls.status.textContent = "Wizard completato end-to-end.";
    onboardingEls.status.style.color = "var(--sage)";
  } catch (err) {
    onboardingEls.testOutput.textContent = err.message;
  } finally {
    onboardingEls.testBtn.disabled = false;
  }
});

onboardingEls.openDocs?.addEventListener("click", () => {
  document.querySelector('[data-view="documenti"]')?.click();
});

onboardingEls.uploadDoc?.addEventListener("click", async () => {
  const file = onboardingEls.docFile.files[0];
  if (!file) {
    onboardingEls.docStatus.textContent = "Scegli un file prima di caricare.";
    onboardingEls.docStatus.style.color = "var(--red)";
    return;
  }
  onboardingEls.uploadDoc.disabled = true;
  onboardingEls.docStatus.textContent = "Caricamento e indicizzazione...";
  onboardingEls.docStatus.style.color = "";
  try {
    const form = new FormData();
    form.append("file", file);
    const res = await apiFetch(`${API_BASE}/api/documenti/carica-file`, { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Errore caricamento");
    }
    const data = await res.json();
    onboardingEls.docStatus.textContent = `Indicizzati ${data.indicizzati} chunk da '${data.nome}'.`;
    onboardingEls.docStatus.style.color = "var(--sage)";
    onboardingEls.docs.checked = true;
  } catch (err) {
    onboardingEls.docStatus.textContent = err.message;
    onboardingEls.docStatus.style.color = "var(--red)";
  } finally {
    onboardingEls.uploadDoc.disabled = false;
  }
});

inizializzaOnboarding();

/* ============================================================
   CHAT
   ============================================================ */

const chatBody = document.getElementById("chat-body");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const chatSuggestions = document.getElementById("chat-suggestions");
const chatStatus = document.getElementById("chat-status");

function aggiungiBollaChat({ testo, mittente, escalation = false, categoria = null }) {
  const bubble = document.createElement("div");
  bubble.classList.add("bubble");
  if (mittente === "cliente") bubble.classList.add("bubble-out");
  else {
    bubble.classList.add("bubble-ai");
    if (escalation) bubble.classList.add("escalated");
  }
  const p = document.createElement("p");
  p.textContent = testo;
  bubble.appendChild(p);
  if (mittente === "ai") {
    const tag = document.createElement("span");
    tag.classList.add("bubble-tag");
    tag.textContent = escalation
      ? "Segnalato a un umano"
      : `Gestito dall'assistente${categoria ? " \u00b7 " + categoria : ""}`;
    bubble.appendChild(tag);
  }
  chatBody.appendChild(bubble);
  chatBody.scrollTop = chatBody.scrollHeight;
}

function mostraTyping() {
  const typing = document.createElement("div");
  typing.classList.add("bubble-typing");
  typing.id = "typing-indicator";
  typing.innerHTML = "<span></span><span></span><span></span>";
  chatBody.appendChild(typing);
  chatBody.scrollTop = chatBody.scrollHeight;
}

function rimuoviTyping() {
  document.getElementById("typing-indicator")?.remove();
}

async function inviaMessaggio(testo) {
  aggiungiBollaChat({ testo, mittente: "cliente" });
  chatStatus.textContent = "sta scrivendo\u2026";
  mostraTyping();
  try {
    const res = await apiFetch(`${API_BASE}/api/messaggio?profilo_id=${PROFILO_ID}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ testo }),
    });
    rimuoviTyping();
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }
    const data = await res.json();
    aggiungiBollaChat({
      testo: data.risposta,
      mittente: "ai",
      escalation: data.richiede_umano,
      categoria: data.categoria,
    });
    await aggiornaRiepilogo();
    await aggiornaPrioritari();
    await aggiornaReport();
    await aggiornaPrenotazioni();
    await aggiornaSemaforo();
    await aggiornaNotifiche();
  } catch (err) {
    rimuoviTyping();
    aggiungiBollaChat({
      testo: "Non riesco a contattare il server dell'assistente.",
      mittente: "ai",
      escalation: true,
      categoria: "errore tecnico",
    });
  } finally {
    chatStatus.textContent = "online";
  }
}

chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const testo = chatInput.value.trim();
  if (!testo) return;
  chatInput.value = "";
  inviaMessaggio(testo);
});

chatSuggestions.addEventListener("click", (e) => {
  const chip = e.target.closest(".suggestion-chip");
  if (!chip) return;
  inviaMessaggio(chip.textContent);
});

/* ============================================================
   PRENOTAZIONI
   ============================================================ */

const bookingCalendarEl = document.getElementById("booking-calendar");
const bookingCount = document.getElementById("booking-count");
const bookingDayList = document.getElementById("booking-day-list");
const bookingDayLabel = document.getElementById("booking-day-label");
const availabilityList = document.getElementById("availability-list");
const availabilityDate = document.getElementById("availability-date");
const bookingForm = document.getElementById("booking-form");
const bookingStatusText = document.getElementById("booking-status-text");
const bookingSettingsGrid = document.getElementById("booking-settings-grid");
const capacitySave = document.getElementById("capacity-save");
const capacityStatus = document.getElementById("capacity-status");
let bookingCalendar = null;
let bookingOpenHours = {};
const bookingModal = document.getElementById("booking-modal");
const bookingDetail = {
  title: document.getElementById("booking-modal-title"),
  date: document.getElementById("booking-detail-date"),
  time: document.getElementById("booking-detail-time"),
  seats: document.getElementById("booking-detail-seats"),
  status: document.getElementById("booking-detail-status"),
  phone: document.getElementById("booking-detail-phone"),
  origin: document.getElementById("booking-detail-origin"),
  note: document.getElementById("booking-detail-note"),
};

function oggiIso() {
  return new Date().toISOString().slice(0, 10);
}

function colorePrenotazione(stato) {
  const normalized = (stato || "").toLowerCase();
  if (normalized.includes("intervento")) return "#C63F52";
  if (normalized.includes("attesa")) return "#C68A2E";
  return "#1F9D74";
}

function apriDettaglioPrenotazione(prenotazione) {
  if (!bookingModal || !prenotazione) return;
  const valore = (dato, fallback = "Non indicato") => dato || fallback;
  const data = prenotazione.data
    ? new Date(`${prenotazione.data}T12:00:00`).toLocaleDateString("it-IT", {
      weekday: "long", day: "2-digit", month: "long", year: "numeric",
    })
    : "Non indicata";
  bookingDetail.title.textContent = valore(prenotazione.nome_cliente, "Cliente");
  bookingDetail.date.textContent = data;
  bookingDetail.time.textContent = valore(prenotazione.ora);
  bookingDetail.seats.textContent = prenotazione.coperti ? `${prenotazione.coperti} coperti` : "Non indicati";
  bookingDetail.status.textContent = valore(prenotazione.stato);
  bookingDetail.phone.textContent = valore(prenotazione.telefono);
  bookingDetail.origin.textContent = valore(prenotazione.origine);
  bookingDetail.note.textContent = valore(prenotazione.note, "Nessuna nota");
  bookingModal.hidden = false;
  document.body.classList.add("booking-modal-open");
}

function chiudiDettaglioPrenotazione() {
  if (!bookingModal) return;
  bookingModal.hidden = true;
  document.body.classList.remove("booking-modal-open");
}

document.querySelectorAll("[data-booking-close]").forEach((element) => {
  element.addEventListener("click", chiudiDettaglioPrenotazione);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") chiudiDettaglioPrenotazione();
});

function inizializzaCalendarioPrenotazioni() {
  if (!bookingCalendarEl || bookingCalendar || !window.FullCalendar) return;
  bookingCalendar = new FullCalendar.Calendar(bookingCalendarEl, {
    initialView: "timeGridWeek",
    locale: "it",
    height: "auto",
    allDaySlot: false,
    nowIndicator: true,
    slotDuration: "00:15:00",
    slotLabelInterval: "01:00:00",
    slotMinTime: "00:00:00",
    slotMaxTime: "24:00:00",
    slotLaneClassNames(info) {
      const hour = `${String(info.date.getHours()).padStart(2, "0")}:00`;
      return bookingOpenHours[hour] === 0 ? ["booking-closed-slot"] : [];
    },
    slotLaneDidMount(info) {
      const hour = `${String(info.date.getHours()).padStart(2, "0")}:00`;
      if (bookingOpenHours[hour] === 0) {
        info.el.style.display = "none";
        const row = info.el.closest("tr");
        if (row) {
          row.classList.add("booking-closed-slot");
          row.style.display = "none";
        }
      }
    },
    slotLabelDidMount(info) {
      const hour = `${String(info.date.getHours()).padStart(2, "0")}:00`;
      if (bookingOpenHours[hour] === 0) {
        info.el.style.display = "none";
        const row = info.el.closest("tr");
        if (row) {
          row.classList.add("booking-closed-slot");
          row.style.display = "none";
        }
      }
    },
    eventDidMount(info) {
      info.el.title = "Doppio click per vedere tutti i dettagli";
      info.el.addEventListener("dblclick", () => {
        apriDettaglioPrenotazione(info.event.extendedProps);
      });
    },
    selectable: true,
    headerToolbar: {
      left: "prev,next today",
      center: "title",
      right: "dayGridMonth,timeGridWeek,timeGridDay",
    },
    select(info) {
      document.getElementById("booking-date").value = info.startStr.slice(0, 10);
      document.getElementById("booking-time").value = info.startStr.slice(11, 16) || "20:00";
      aggiornaSemaforo(info.startStr.slice(0, 10));
      aggiornaListaGiorno(info.startStr.slice(0, 10));
    },
    datesSet(info) {
      aggiornaSemaforo(info.startStr.slice(0, 10));
      aggiornaListaGiorno(info.startStr.slice(0, 10));
    },
  });
  bookingCalendar.render();
}

async function aggiornaPrenotazioni() {
  if (!bookingCalendarEl) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings`);
    if (!res.ok) return;
    const prenotazioni = await res.json();
    bookingCount.textContent = `${prenotazioni.length} prenotazioni`;
    if (!bookingCalendar) inizializzaCalendarioPrenotazioni();
    if (!bookingCalendar) return;
    bookingCalendar.removeAllEvents();
    prenotazioni.forEach((p) => {
      if (!p.data || !p.ora) return;
      const ora = String(p.ora).slice(0, 5);
      bookingCalendar.addEvent({
        id: p.id,
        title: `${ora} Â· ${p.nome_cliente || "Cliente"} Â· ${p.coperti || "?"} coperti`,
        start: `${p.data}T${ora}:00`,
        end: `${p.data}T${ora}:00`,
        backgroundColor: colorePrenotazione(p.stato),
        borderColor: colorePrenotazione(p.stato),
        extendedProps: p,
      });
    });
    aggiornaListaGiorno(document.getElementById("booking-date")?.value || oggiIso(), prenotazioni);
  } catch (err) {
    console.error("Impossibile caricare le prenotazioni:", err);
  }
}

function aggiornaListaGiorno(data, prenotazioni = null) {
  if (!bookingDayList) return;
  const giorno = prenotazioni || [];
  const render = (items) => {
    bookingDayLabel.textContent = new Date(`${data}T12:00:00`).toLocaleDateString("it-IT", {
      weekday: "short", day: "2-digit", month: "2-digit",
    });
    bookingDayList.innerHTML = "";
    if (!items.length) {
      bookingDayList.innerHTML = '<p class="booking-empty">Nessuna prenotazione per questo giorno.</p>';
      return;
    }
    items.sort((a, b) => `${a.ora}${a.nome_cliente}`.localeCompare(`${b.ora}${b.nome_cliente}`));
    items.forEach((p) => {
      const item = document.createElement("article");
      item.className = "booking-row";
      const ora = String(p.ora || "").slice(0, 5);
      item.innerHTML = `
        <time class="booking-row-time">${_sanitize(ora) || "--:--"}</time>
        <div class="booking-row-main"><strong>${_sanitize(p.nome_cliente) || "Cliente"}</strong><span>${_sanitize(p.coperti) || "?"} coperti${p.telefono ? ` Â· ${_sanitize(p.telefono)}` : ""}</span></div>
        <span class="booking-row-status" style="--booking-color:${_sanitize(colorePrenotazione(p.stato))}">${_sanitize(p.stato) || "In attesa"}</span>`;
      bookingDayList.appendChild(item);
    });
  };
  if (prenotazioni) {
    render(prenotazioni.filter((p) => p.data === data));
  } else {
    apiFetch(`${API_BASE}/api/bookings`).then((res) => res.json()).then((all) => render(all.filter((p) => p.data === data))).catch(() => render([]));
  }
}

async function aggiornaSemaforo(data = null) {
  if (!availabilityList) return;
  const targetDate = data || document.getElementById("booking-date")?.value || oggiIso();
  availabilityDate.textContent = new Date(`${targetDate}T12:00:00`).toLocaleDateString("it-IT", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  });
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings/semaforo?data=${targetDate}`);
    if (!res.ok) return;
    const slots = await res.json();
    availabilityList.innerHTML = "";
    slots.forEach((slot) => {
      const item = document.createElement("div");
      item.classList.add("availability-item", `availability-${slot.stato}`);
      item.innerHTML = `
        <span class="availability-dot"></span>
        <span class="availability-hour">${_sanitize(slot.ora)}</span>
        <span class="availability-seats">${_sanitize(slot.coperti_liberi)}/${_sanitize(slot.coperti_massimi)} liberi</span>
      `;
      availabilityList.appendChild(item);
    });
  } catch (err) {
    console.error("Impossibile caricare il semaforo:", err);
  }
}

async function aggiornaImpostazioniPrenotazioni() {
  if (!bookingSettingsGrid || bookingSettingsGrid.children.length) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings/settings`);
    if (!res.ok) return;
    const data = await res.json();
    const capienze = data.capienze_orarie || {};
    bookingOpenHours = capienze;
    bookingSettingsGrid.innerHTML = (data.fasce_orarie || []).map((ora) => `
      <label class="booking-setting"><span>${_sanitize(ora)}</span><input type="number" min="0" max="500" data-capacity-hour="${_sanitize(ora)}" value="${_sanitize(capienze[ora] ?? 40)}"></label>
    `).join("");
  } catch (err) {
    console.error("Impossibile caricare le impostazioni prenotazioni:", err);
  }
}

bookingForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  bookingStatusText.textContent = "";
  const payload = {
    nome_cliente: document.getElementById("booking-name").value.trim(),
    telefono: document.getElementById("booking-phone").value.trim(),
    data: document.getElementById("booking-date").value,
    ora: document.getElementById("booking-time").value,
    coperti: parseInt(document.getElementById("booking-seats").value, 10),
    note: document.getElementById("booking-note").value.trim(),
  };
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail?.messaggio || err?.detail || "Errore salvataggio");
    }
    bookingForm.reset();
    document.getElementById("booking-date").value = payload.data;
    bookingStatusText.textContent = "Prenotazione aggiunta.";
    bookingStatusText.style.color = "var(--sage)";
    await aggiornaPrenotazioni();
    await aggiornaSemaforo(payload.data);
  } catch (err) {
    bookingStatusText.textContent = err.message;
    bookingStatusText.style.color = "var(--red)";
  }
});

capacitySave?.addEventListener("click", async () => {
  capacityStatus.textContent = "";
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        capienze_orarie: Object.fromEntries([...document.querySelectorAll("[data-capacity-hour]")].map((input) => [input.dataset.capacityHour, parseInt(input.value, 10) || 0])),
      }),
    });
    if (!res.ok) throw new Error("Errore salvataggio capienza");
    const savedSettings = await res.json();
    bookingOpenHours = savedSettings.capienze_orarie || {};
    if (bookingCalendar) {
      bookingCalendar.destroy();
      bookingCalendar = null;
      inizializzaCalendarioPrenotazioni();
    }
    capacityStatus.textContent = "Capienza aggiornata.";
    capacityStatus.style.color = "var(--sage)";
    await aggiornaSemaforo();
    capacityStatus.textContent += " Le modifiche sono attive subito.";
  } catch (err) {
    capacityStatus.textContent = err.message;
    capacityStatus.style.color = "var(--red)";
  }
});

document.getElementById("booking-date")?.addEventListener("change", (event) => {
  aggiornaSemaforo(event.target.value);
  aggiornaListaGiorno(event.target.value);
});

/* ============================================================
   RECENSIONI
   ============================================================ */

const reviewText = document.getElementById("review-text");
const reviewAuthor = document.getElementById("review-author");
const reviewStars = document.getElementById("review-stars");
const reviewSource = document.getElementById("review-source");
const reviewAnalyze = document.getElementById("review-analyze");
const reviewDraft = document.getElementById("review-draft");
const reviewDraftText = document.getElementById("review-draft-text");
const reviewDraftSentiment = document.getElementById("review-draft-sentiment");
const reviewDraftCat = document.getElementById("review-draft-cat");
const reviewCopy = document.getElementById("review-copy");
const reviewApprove = document.getElementById("review-approve");

let reviewAttualeId = null;

async function inviaRecensione() {
  const testo = reviewText.value.trim();
  if (!testo) return;
  reviewAnalyze.disabled = true;
  reviewAnalyze.textContent = "Analisi in corso\u2026";
  try {
    const res = await apiFetch(`${API_BASE}/api/recensione`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        testo,
        valutazione_stelle: reviewStars.value ? parseInt(reviewStars.value) : null,
        autore: reviewAuthor.value.trim(),
        fonte: reviewSource.value || "manuale",
      }),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }
    const data = await res.json();
    reviewAttualeId = data.id;
    reviewApprove.disabled = false;
    reviewDraft.hidden = false;
    reviewDraftText.textContent = data.bozza_risposta;
    reviewDraftSentiment.textContent = data.sentiment;
    reviewDraftCat.textContent = data.categoria;
    reviewDraftSentiment.className = "review-draft-sentiment";
    reviewDraftSentiment.classList.add(`sentiment-${data.sentiment}`);
    await aggiornaRiepilogo();
    await aggiornaPrioritari();
    await aggiornaTrends();
    await aggiornaNotifiche();
  } catch (err) {
    alert("Errore: " + err.message);
  } finally {
    reviewAnalyze.disabled = false;
    reviewAnalyze.textContent = "Analizza e genera bozza";
  }
}

async function approvaRecensione() {
  if (!reviewAttualeId) return;
  reviewApprove.disabled = true;
  reviewApprove.textContent = "Approvazione\u2026";
  try {
    const res = await apiFetch(`${API_BASE}/api/recensioni/${reviewAttualeId}/approva`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }
    const data = await res.json();
    reviewApprove.textContent = "Approvata";
    reviewDraftSentiment.textContent = data.stato;
    reviewDraftSentiment.className = "review-draft-sentiment sentiment-approvata";
    await aggiornaRiepilogo();
    await aggiornaPrioritari();
  } catch (err) {
    alert("Errore: " + err.message);
    reviewApprove.disabled = false;
    reviewApprove.textContent = "Approva risposta";
  }
}

const trendList = document.getElementById("trend-list");

function _paroleChiave(testi, max = 3) {
  const stop = ["di", "il", "la", "le", "gli", "un", "una", "che", "per", "con", "non", "ho", "ha", "Ã¨", "e", "a", "o", "si", "in", "da", "lo", "sono", "mi", "ma", "ci", "ti", "al", "del", "della", "dei", "delle", "allo", "alla", "ai", "agli", "alle", "dal", "dalla", "dai", "dagli", "dalle", "nel", "nella", "nei", "negli", "nelle", "sul", "sulla", "sui", "sugli", "sulle", "molto", "tanto", "piÃ¹", "meno", "era", "stato", "stata", "stati", "state", "essere", "questo", "quella", "quello", "conto", "fare", "fatto"];
  const words = testi.join(" ").toLowerCase().replace(/[^a-zÃ Ã¨Ã©Ã¬Ã²Ã¹\s]/g, "").split(/\s+/).filter(w => w.length > 3 && !stop.includes(w));
  const freq = {};
  words.forEach(w => { freq[w] = (freq[w] || 0) + 1; });
  return Object.entries(freq).sort((a,b) => b[1] - a[1]).slice(0, max).map(e => e[0]);
}

async function aggiornaTrends() {
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard`);
    if (!res.ok) return;
    const eventi = await res.json();
    const recensioni = eventi.filter(e => e.tipo_evento === "recensione");
    const totale = recensioni.length;

    if (totale === 0) {
      trendList.innerHTML = `<li class="trend-item"><div class="trend-body"><span class="trend-label" style="color:var(--sidebar-text)">Nessuna recensione ancora â€” incollane una qui sopra.</span></div></li>`;
      return;
    }

    const pos = recensioni.filter(e => e.dettagli.sentiment === "positiva").length;
    const neg = recensioni.filter(e => e.dettagli.sentiment === "negativa").length;
    const neut = recensioni.filter(e => e.dettagli.sentiment === "neutra").length;
    const pctPos = Math.round(pos / totale * 100);
    const pctNeg = Math.round(neg / totale * 100);
    const pctNeut = Math.round(neut / totale * 100);

    const catCount = {};
    recensioni.forEach(e => {
      const c = e.dettagli.categoria || "generico";
      catCount[c] = (catCount[c] || 0) + 1;
    });
    const topCat = Object.entries(catCount).sort((a, b) => b[1] - a[1]).slice(0, 2);

    const testi = recensioni.map(e => e.testo_originale);
    const keywords = _paroleChiave(testi, 2);

    const items = [];

    if (pos > 0) items.push(`
      <li class="trend-item">
        <span class="trend-icon trend-pos">â–²</span>
        <div class="trend-body">
          <span class="trend-label">Positivo (${pctPos}%)</span>
          <div class="trend-bar-track"><div class="trend-bar-fill fill-pos" style="width:${pctPos}%"></div></div>
        </div>
      </li>`);

    if (neg > 0) items.push(`
      <li class="trend-item">
        <span class="trend-icon trend-neg">â–¼</span>
        <div class="trend-body">
          <span class="trend-label">Negativo (${pctNeg}%)</span>
          <div class="trend-bar-track"><div class="trend-bar-fill fill-neg" style="width:${pctNeg}%"></div></div>
        </div>
      </li>`);

    if (neut > 0) items.push(`
      <li class="trend-item">
        <span class="trend-icon trend-neutral">â€”</span>
        <div class="trend-body"><span class="trend-label">Neutro (${pctNeut}%)</span></div>
      </li>`);

    topCat.forEach(([cat]) => {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-topic">â†—</span>
          <div class="trend-body"><span class="trend-label">Argomento ricorrente: ${_sanitize(cat.replace(/_/g, " "))}</span></div>
        </li>`);
    });

    keywords.forEach(kw => {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-new">âœ¦</span>
          <div class="trend-body"><span class="trend-label">Parola chiave: "${_sanitize(kw)}"</span></div>
        </li>`);
    });

    trendList.innerHTML = items.join("");
  } catch (err) {
    console.error("Impossibile aggiornare i trend:", err);
  }
}

reviewCopy.addEventListener("click", () => {
  navigator.clipboard.writeText(reviewDraftText.textContent).catch(() => {});
});
reviewApprove.addEventListener("click", approvaRecensione);
reviewAnalyze.addEventListener("click", inviaRecensione);

/* ============================================================
   REPORT
   ============================================================ */

const reportSection = document.getElementById("report-section");
const reportDate = document.getElementById("report-date");
const reportTotale = document.getElementById("report-totale");
const reportAi = document.getElementById("report-ai");
const reportUmano = document.getElementById("report-umano");
const reportAnalisi = document.getElementById("report-analisi");
const reportSuggestions = document.getElementById("report-suggestions");
const reportSuggestionsList = document.getElementById("report-suggestions-list");
const reportTimestamp = document.getElementById("report-timestamp");
const reportRefresh = document.getElementById("report-refresh");
const reportEmptyHint = document.getElementById("report-empty-hint");

async function aggiornaReport(forza = false) {
  try {
    const url = `${API_BASE}/api/report${forza ? "?forza=true" : ""}`;
    const res = await apiFetch(url);
    if (!res.ok) return;
    const report = await res.json();
    reportSection.hidden = false;
    if (reportEmptyHint) reportEmptyHint.hidden = true;
    reportDate.textContent = report.statistiche.periodo;
    reportTotale.textContent = report.statistiche.totale_messaggi;
    reportAi.textContent = report.statistiche.gestiti_da_ai;
    reportUmano.textContent = report.statistiche.girati_a_umano;
    reportAnalisi.textContent = report.analisi_testuale;
    reportTimestamp.textContent = "Generato: " + new Date(report.generato_il).toLocaleTimeString("it-IT", {
      hour: "2-digit", minute: "2-digit",
    });
    if (report.suggerimenti && report.suggerimenti.length > 0) {
      reportSuggestions.hidden = false;
      reportSuggestionsList.innerHTML = "";
      report.suggerimenti.forEach((s) => {
        const li = document.createElement("li");
        li.classList.add("report-suggestions-item");
        li.textContent = s;
        reportSuggestionsList.appendChild(li);
      });
    } else {
      reportSuggestions.hidden = true;
    }
  } catch (err) {
    console.error("Impossibile caricare il report:", err);
  }
}

reportRefresh.addEventListener("click", () => aggiornaReport(true));

/* ============================================================
   PANORAMICA â€” KPI + prioritÃ  + attivitÃ 
   ============================================================ */

const prioritySection = document.getElementById("priority-section");
const priorityList = document.getElementById("priority-list");
const ticketList = document.getElementById("ticket-list");
const ticketEmpty = document.getElementById("ticket-empty");
const statTotale = document.getElementById("stat-totale");
const statAi = document.getElementById("stat-ai");
const statUmano = document.getElementById("stat-umano");

async function aggiornaPrioritari() {
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard/prioritari`);
    if (!res.ok) return;
    const eventi = await res.json();
    priorityList.innerHTML = "";
    if (eventi.length === 0) {
      priorityList.innerHTML = `<li class="priority-empty">Niente da gestire â€” tutto sotto controllo.</li>`;
      return;
    }
    eventi.forEach((e) => {
      const li = document.createElement("li");
      li.classList.add("priority-item", `prio-${e.priorita}`);
      const badge = document.createElement("span");
      badge.classList.add("priority-item-badge", `badge-${e.tipo_evento}`);
      badge.textContent = e.tipo_evento === "recensione" ? "REC" : "MSG";
      const msg = document.createElement("span");
      msg.classList.add("priority-item-msg");
      msg.textContent = e.testo_originale;
      const cat = document.createElement("span");
      cat.classList.add("priority-item-cat");
      cat.textContent = (e.dettagli.categoria || e.dettagli.sentiment || "generico");
      li.appendChild(badge);
      li.appendChild(msg);
      li.appendChild(cat);
      priorityList.appendChild(li);
    });
  } catch (err) {
    console.error("Impossibile aggiornare gli eventi prioritari:", err);
  }
}

async function aggiornaRiepilogo() {
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard`);
    if (!res.ok) return;
    const storico = await res.json();
    const totale = storico.length;
    const gestitiAi = storico.filter((e) => e.gestito_da_ai).length;
    const girati = totale - gestitiAi;
    statTotale.textContent = totale;
    statAi.textContent = gestitiAi;
    statUmano.textContent = girati;
    ticketList.innerHTML = "";
    if (totale === 0) {
      ticketList.appendChild(ticketEmpty);
      return;
    }
    storico.slice().reverse().forEach((e) => {
      const li = document.createElement("li");
      li.classList.add("ticket-item", `prio-${e.priorita}`);
      const testoWrap = document.createElement("div");
      testoWrap.classList.add("ticket-item-text");
      const msg = document.createElement("p");
      msg.classList.add("ticket-item-msg");
      msg.textContent = e.testo_originale;
      const time = document.createElement("span");
      time.classList.add("ticket-item-time");
      time.textContent = new Date(e.timestamp).toLocaleTimeString("it-IT", {
        hour: "2-digit", minute: "2-digit",
      });
      testoWrap.appendChild(msg);
      testoWrap.appendChild(time);
      const tags = document.createElement("div");
      tags.classList.add("ticket-item-tags");
      const tipoBadge = document.createElement("span");
      tipoBadge.classList.add("ticket-tag", `ticket-tag-${e.tipo_evento}`);
      tipoBadge.textContent = e.tipo_evento === "recensione" ? "Recensione" : "Messaggio";
      tags.appendChild(tipoBadge);
      if (e.tipo_evento === "recensione" && e.dettagli.stelle) {
        const stelleTag = document.createElement("span");
        stelleTag.classList.add("ticket-tag", "ticket-tag-stelle");
        stelleTag.textContent = "\u2605".repeat(e.dettagli.stelle) + "\u2606".repeat(5 - e.dettagli.stelle);
        tags.appendChild(stelleTag);
      }
      if (e.tipo_evento === "recensione") {
        const copyBtn = document.createElement("button");
        copyBtn.classList.add("ticket-copy-btn");
        copyBtn.textContent = "Copia bozza";
        copyBtn.addEventListener("click", () => {
          navigator.clipboard.writeText(e.risposta_ai).catch(() => {});
        });
        tags.appendChild(copyBtn);
      } else {
        const statusTag = document.createElement("span");
        statusTag.classList.add("ticket-tag");
        statusTag.classList.add(e.gestito_da_ai ? "ticket-tag-ai" : "ticket-tag-umano");
        statusTag.textContent = e.gestito_da_ai ? "Assistente" : "Umano";
        tags.appendChild(statusTag);
      }
      li.appendChild(testoWrap);
      li.appendChild(tags);
      ticketList.appendChild(li);
    });
  } catch (err) {
    console.error("Impossibile aggiornare il riepilogo:", err);
  }
}

/* ============================================================
   DOCUMENTI
   ============================================================ */

const docConteggio = document.getElementById("doc-conteggio");
const docLibrary = document.getElementById("doc-library");
const docQuery = document.getElementById("doc-query");
const docChiediBtn = document.getElementById("doc-chiedi-btn");
const docRisposta = document.getElementById("doc-risposta");
const docRispostaText = document.getElementById("doc-risposta-text");
const docFonti = document.getElementById("doc-fonti");
const docFontiList = document.getElementById("doc-fonti-list");

async function aggiornaConteggio() {
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/conteggio`);
    if (!res.ok) { docConteggio.textContent = "Non disponibile."; return; }
    const data = await res.json();
    docConteggio.textContent = `${data.chunk_indicizzati} parti indicizzate.`;
  } catch {
    docConteggio.textContent = "Errore di connessione.";
  }
}

async function aggiornaDocumenti() {
  if (!docLibrary) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/elenco`);
    if (!res.ok) return;
    const data = await res.json();
    docLibrary.innerHTML = "";
    if (!data.documenti?.length) {
      docLibrary.innerHTML = '<p class="doc-library-empty">Nessun documento caricato.</p>';
      return;
    }
    data.documenti.forEach((documento) => {
      const item = document.createElement("div");
      item.className = "doc-library-item";
      const name = document.createElement("span");
      name.className = "doc-library-name";
      name.title = documento.nome;
      name.textContent = documento.nome;
      const meta = document.createElement("span");
      meta.className = "doc-library-count";
      meta.textContent = `${documento.chunk} parti`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "doc-library-remove";
      remove.textContent = "Rimuovi";
      remove.title = `Rimuovi ${documento.nome}`;
      remove.addEventListener("click", async () => {
        if (!window.confirm(`Rimuovere ${documento.nome} dalla knowledge base?`)) return;
        remove.disabled = true;
        try {
          const response = await apiFetch(`${API_BASE}/api/documenti/${encodeURIComponent(documento.id)}`, { method: "DELETE" });
          if (!response.ok) throw new Error("Impossibile rimuovere il documento.");
          await aggiornaConteggio();
          await aggiornaDocumenti();
        } catch (err) {
          remove.disabled = false;
          docCaricaStatus.textContent = err.message;
          docCaricaStatus.style.color = "var(--red)";
        }
      });
      item.append(name, meta, remove);
      docLibrary.appendChild(item);
    });
  } catch (err) {
    console.error("Impossibile caricare l'elenco documenti:", err);
  }
}

const docReindicizzaBtn = document.getElementById("doc-reindicizza-btn");
const docReindicizzaProgress = document.getElementById("doc-reindicizza-progress");
const docReindicizzaBar = document.getElementById("doc-reindicizza-bar");
const docReindicizzaStatus = document.getElementById("doc-reindicizza-status-text");

docReindicizzaBtn?.addEventListener("click", async () => {
  docReindicizzaBtn.disabled = true;
  docReindicizzaBtn.textContent = "Avvio\u2026";
  docReindicizzaProgress.hidden = false;
  docReindicizzaBar.style.width = "0%";
  docReindicizzaStatus.textContent = "Avvio re-indicizzazione...";
  docReindicizzaStatus.style.color = "";

  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/reindicizza`, { method: "POST" });
    if (!res.ok) throw new Error("Errore avvio");
    const { task_id } = await res.json();

    const poll = setInterval(async () => {
      try {
        const res2 = await apiFetch(`${API_BASE}/api/documenti/reindicizza/stato/${task_id}`);
        if (!res2.ok) { clearInterval(poll); throw new Error("Errore polling"); }
        const stato = await res2.json();

        docReindicizzaStatus.textContent = stato.progress || "";

        if (stato.status === "processing") {
          docReindicizzaBtn.textContent = "Re-indicizzazione\u2026";
        } else if (stato.status === "done") {
          clearInterval(poll);
          docReindicizzaBar.style.width = "100%";
          docReindicizzaStatus.textContent = stato.progress;
          docReindicizzaStatus.style.color = "var(--sage)";
          docReindicizzaBtn.textContent = "Re-indicizza tutte";
          docReindicizzaBtn.disabled = false;
          await aggiornaConteggio();
        } else if (stato.status === "error") {
          clearInterval(poll);
          docReindicizzaStatus.textContent = "Errore: " + (stato.errore || "sconosciuto");
          docReindicizzaStatus.style.color = "var(--red)";
          docReindicizzaBtn.textContent = "Re-indicizza tutte";
          docReindicizzaBtn.disabled = false;
        }
      } catch (e) {
        clearInterval(poll);
        docReindicizzaStatus.textContent = "Errore: " + e.message;
        docReindicizzaStatus.style.color = "var(--red)";
        docReindicizzaBtn.textContent = "Re-indicizza tutte";
        docReindicizzaBtn.disabled = false;
      }
    }, 1500);
  } catch (e) {
    docReindicizzaStatus.textContent = "Errore: " + e.message;
    docReindicizzaStatus.style.color = "var(--red)";
    docReindicizzaBtn.textContent = "Re-indicizza tutte";
    docReindicizzaBtn.disabled = false;
  }
});

const docCaricaTesto = document.getElementById("doc-carica-testo");
const docFile = document.getElementById("doc-file");
const docCaricaNome = document.getElementById("doc-carica-nome");
const docCaricaBtn = document.getElementById("doc-carica-btn");
const docCaricaStatus = document.getElementById("doc-carica-status");
docCaricaBtn.addEventListener("click", async () => {
  const testo = docCaricaTesto.value.trim();
  const file = docFile?.files?.[0];
  const nome = docCaricaNome.value.trim() || "documento.txt";
  if (!file && !testo) { docCaricaStatus.textContent = "Scegli un file oppure incolla il testo del documento."; return; }
  docCaricaBtn.disabled = true;
  docCaricaBtn.textContent = "Indicizzazione\u2026";
  try {
    let res;
    if (file) {
      const form = new FormData();
      form.append("file", file);
      res = await apiFetch(`${API_BASE}/api/documenti/carica-file`, { method: "POST", body: form });
    } else {
      res = await apiFetch(`${API_BASE}/api/documenti/carica`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ testo, nome }),
      });
    }
    if (!res.ok) {
      const error = await res.json().catch(() => null);
      throw new Error(error?.detail || "Errore durante l'indicizzazione");
    }
    const data = await res.json();
    docCaricaStatus.textContent = data.detail;
    docCaricaStatus.style.color = "var(--sage)";
    docCaricaTesto.value = "";
    if (docFile) docFile.value = "";
    await aggiornaConteggio();
    await aggiornaDocumenti();
    await aggiornaNotifiche();
  } catch (err) {
    docCaricaStatus.textContent = err.message || "Errore durante il caricamento.";
    docCaricaStatus.style.color = "var(--red)";
  } finally {
    docCaricaBtn.disabled = false;
    docCaricaBtn.textContent = "Salva documento";
  }
});

docChiediBtn.addEventListener("click", async () => {
  const domanda = docQuery.value.trim();
  if (!domanda) return;
  docChiediBtn.disabled = true;
  docChiediBtn.textContent = "Cerco\u2026";
  docRisposta.hidden = true;
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/chiedi`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domanda, k: 5 }),
    });
    if (!res.ok) throw new Error("Errore");
    const data = await res.json();
    docRispostaText.textContent = data.risposta;
    docRisposta.hidden = false;

    if (data.fonti && data.fonti.length > 0) {
      docFonti.hidden = false;
      docFontiList.innerHTML = "";
      data.fonti.forEach((f) => {
        const li = document.createElement("li");
        li.classList.add("doc-fonti-item");
        li.innerHTML = `<strong>${_sanitize(f.documento)}</strong> <span class="doc-fonti-score">(score: ${_sanitize(f.score)})</span><br><span class="doc-fonti-estratto">${_sanitize(f.estratto)}</span>`;
        docFontiList.appendChild(li);
      });
    } else {
      docFonti.hidden = true;
    }
  } catch {
    docRispostaText.textContent = "Errore durante la ricerca.";
    docRisposta.hidden = false;
    docFonti.hidden = true;
  } finally {
    docChiediBtn.disabled = false;
    docChiediBtn.textContent = "Chiedi";
  }
});

/* ============================================================
   INBOX (HITL) â€” ticket escalati all'operatore umano
   ============================================================ */

const inboxList = document.getElementById("inbox-list");
const inboxEmpty = document.getElementById("inbox-empty");
const inboxCount = document.getElementById("inbox-count");
let inboxState = {
  status: "ALL",
  priorita: "",
};

const TICKET_STATUS_LABEL = {
  AI_ACTIVE: "Automazione",
  PENDING_STAFF: "In attesa",
  CLAIMED: "Preso in carico",
  RESOLVED: "Risolto",
};

function formatInboxDate(value) {
  if (!value) return "";
  const d = new Date(value);
  return d.toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatSla(sla_due_at, is_overdue) {
  if (!sla_due_at) return null;
  const due = new Date(sla_due_at);
  const now = new Date();
  const minutes = Math.max(0, Math.round((due - now) / 60000));
  if (is_overdue) return { text: "SLA superato", overdue: true };
  if (minutes <= 0) return { text: "SLA scaduto", overdue: true };
  return { text: `SLA ${minutes} min`, overdue: false };
}

async function caricaInbox() {
  if (!inboxList) return;
  try {
    const params = new URLSearchParams();
    if (inboxState.status !== "ALL") params.set("status", inboxState.status);
    if (inboxState.priorita) params.set("priorita", inboxState.priorita);
    const res = await apiFetch(`${API_BASE}/api/inbox/tickets?${params.toString()}`);
    if (!res.ok) return;
    const data = await res.json();
    const tickets = data.tickets || [];

    let team = [];
    try {
      const teamRes = await apiFetch(`${API_BASE}/api/inbox/team`);
      if (teamRes.ok) team = (await teamRes.json()).members || [];
    } catch (e) {
      console.error("Impossibile caricare il team:", e);
    }

    inboxCount.textContent = `${tickets.length} ticket`;
    inboxList.innerHTML = "";
    if (!tickets.length) {
      inboxList.appendChild(inboxEmpty);
      inboxEmpty.textContent = "Nessun ticket.";
      return;
    }
    tickets.forEach((t) => renderInboxCard(inboxList, t, team));
  } catch (err) {
    console.error("Impossibile caricare l'inbox:", err);
  }
}

function renderInboxCard(container, t, team) {
  team = team || [];
  const card = document.createElement("div");
  card.className = "inbox-card";
  card.classList.add(`prio-${t.priorita}`);
  if (t.is_overdue) card.classList.add("overdue");

  const top = document.createElement("div");
  top.className = "inbox-card-top";

  const left = document.createElement("div");
  left.style.flex = "1";
  left.style.minWidth = "0";

  const title = document.createElement("h3");
  title.className = "inbox-card-title";
  title.textContent = t.phone_number || "Cliente";

  const isInstagram = t.canale === "instagram";
  if (isInstagram) {
    const igBadge = document.createElement("span");
    igBadge.className = "ticket-tag";
    igBadge.textContent = "Instagram";
    title.appendChild(document.createTextNode(" "));
    title.appendChild(igBadge);
  }

  const meta = document.createElement("div");
  meta.className = "inbox-card-meta";
  const assigned = t.assigned_nome ? ` Â· ${t.assigned_nome}` : "";
  meta.textContent = `${TICKET_STATUS_LABEL[t.ticket_status] || t.ticket_status}${assigned}`;
  left.appendChild(title);
  left.appendChild(meta);

  const tags = document.createElement("div");
  tags.className = "inbox-tags";

  const prioTag = document.createElement("span");
  prioTag.className = "ticket-tag";
  prioTag.textContent = t.priorita;
  tags.appendChild(prioTag);

  const sla = formatSla(t.sla_due_at, t.is_overdue);
  if (sla) {
    const slaEl = document.createElement("span");
    slaEl.className = "inbox-sla";
    if (sla.overdue) slaEl.classList.add("overdue");
    slaEl.textContent = sla.text;
    slaEl.title = t.sla_due_at ? `Scadenza: ${formatInboxDate(t.sla_due_at)}` : "";
    tags.appendChild(slaEl);
  }

  if (t.pending_staff_at) {
    const pend = document.createElement("span");
    pend.className = "inbox-card-meta";
    pend.textContent = ` Â· attesa da ${formatInboxDate(t.pending_staff_at)}`;
    meta.textContent += pend.textContent;
  }

  top.appendChild(left);
  top.appendChild(tags);
  card.appendChild(top);

  if (t.last_message_preview) {
    const msg = document.createElement("p");
    msg.className = "inbox-card-msg";
    msg.textContent = t.last_message_preview;
    card.appendChild(msg);
  }

  const actions = document.createElement("div");
  actions.className = "inbox-actions";

  const threadBtn = document.createElement("button");
  threadBtn.type = "button";
  threadBtn.className = "inbox-btn";
  threadBtn.textContent = "Conversazione";
  threadBtn.title = "Apri lo storico completo dei messaggi";
  threadBtn.addEventListener("click", () => apriThreadConversazione(t));
  actions.appendChild(threadBtn);

  if ((t.ticket_status === "PENDING_STAFF" || t.ticket_status === "CLAIMED") && team.length) {
    const assignWrap = document.createElement("div");
    assignWrap.className = "inbox-assign";
    const assignSel = document.createElement("select");
    assignSel.className = "inbox-assign-select";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Assegna a…";
    placeholder.disabled = true;
    placeholder.selected = true;
    assignSel.appendChild(placeholder);
    team.forEach((m) => {
      const opt = document.createElement("option");
      opt.value = m.user_id;
      opt.textContent = `${m.nome || m.email}${m.user_id === t.assigned_to ? " (assegnato)" : ""}`;
      assignSel.appendChild(opt);
    });
    assignSel.addEventListener("change", async () => {
      if (!assignSel.value) return;
      assignSel.disabled = true;
      try {
        const res = await apiFetch(`${API_BASE}/api/inbox/assign/${encodeURIComponent(t.id)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ assigned_to: assignSel.value, expected_version: t.version }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || "Impossibile assegnare.");
        }
        await caricaInbox();
      } catch (err) {
        assignSel.disabled = false;
        alert(err.message);
      }
    });
    assignWrap.appendChild(assignSel);
    actions.appendChild(assignWrap);
  }

  if (t.ticket_status === "PENDING_STAFF") {
    const claim = document.createElement("button");
    claim.type = "button";
    claim.className = "inbox-btn primary";
    claim.textContent = "Claim";
    claim.title = "Prendi in carico";
    claim.addEventListener("click", async () => {
      try {
        const res = await apiFetch(`${API_BASE}/api/inbox/claim/${encodeURIComponent(t.id)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_version: t.version }),
        });
        if (!res.ok) throw new Error("Impossibile fare il claim.");
        await caricaInbox();
      } catch (err) {
        alert(err.message);
      }
    });
    actions.appendChild(claim);
  }

  if (t.ticket_status === "CLAIMED") {
    const release = document.createElement("button");
    release.type = "button";
    release.className = "inbox-btn";
    release.textContent = "Rilascia";
    release.addEventListener("click", async () => {
      try {
        const res = await apiFetch(`${API_BASE}/api/inbox/release/${encodeURIComponent(t.id)}`, { method: "POST" });
        if (!res.ok) throw new Error("Impossibile rilasciare.");
        await caricaInbox();
      } catch (err) {
        alert(err.message);
      }
    });
    actions.appendChild(release);

    const risolvi = document.createElement("button");
    risolvi.type = "button";
    risolvi.className = "inbox-btn";
    risolvi.textContent = "Risolvi";
    risolvi.addEventListener("click", async () => {
      try {
        const res = await apiFetch(`${API_BASE}/api/inbox/resolve/${encodeURIComponent(t.id)}`, { method: "POST" });
        if (!res.ok) throw new Error("Impossibile risolvere.");
        await caricaInbox();
      } catch (err) {
        alert(err.message);
      }
    });
    actions.appendChild(risolvi);

    const replyToggle = document.createElement("button");
    replyToggle.type = "button";
    replyToggle.className = "inbox-btn";
    replyToggle.textContent = "Rispondi";
    replyToggle.addEventListener("click", () => {
      replyArea.classList.toggle("open");
      replyToggle.textContent = replyArea.classList.contains("open") ? "Chiudi" : "Rispondi";
    });
    actions.appendChild(replyToggle);
  }

  card.appendChild(actions);

  const replyArea = document.createElement("div");
  replyArea.className = "inbox-reply";
  const canaleLabel = isInstagram ? "Instagram" : "WhatsApp";
  const replyInput = document.createElement("textarea");
  replyInput.className = "inbox-reply-input";
  replyInput.rows = 2;
  replyInput.placeholder = `Scrivi la risposta da inviare su ${canaleLabel}...`;
  const replyRow = document.createElement("div");
  replyRow.className = "inbox-reply-row";
  const invia = document.createElement("button");
  invia.type = "button";
  invia.className = "inbox-btn primary";
  invia.textContent = `Invia su ${canaleLabel}`;
  const replyStatus = document.createElement("p");
  replyStatus.className = "inbox-status";
  invia.addEventListener("click", async () => {
    const content = replyInput.value.trim();
    if (!content) return;
    invia.disabled = true;
    replyStatus.textContent = "Invio...";
    try {
      const res = await apiFetch(`${API_BASE}/api/inbox/reply/${encodeURIComponent(t.id)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content,
          message_type: "text",
          idempotency_key: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
        }),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Impossibile inviare.");
      }
      replyStatus.textContent = `Inviato su ${canaleLabel}.`;
      replyInput.value = "";
    } catch (err) {
      replyStatus.classList.add("error");
      replyStatus.textContent = err.message;
    } finally {
      invia.disabled = false;
    }
  });
  replyRow.appendChild(invia);
  replyArea.appendChild(replyInput);
  replyArea.appendChild(replyRow);
  replyArea.appendChild(replyStatus);
  card.appendChild(replyArea);

  container.appendChild(card);
}

document.querySelectorAll("[data-inbox-status]").forEach((btn) => {
  btn.addEventListener("click", () => {
    inboxState.status = btn.dataset.inboxStatus;
    document.querySelectorAll("[data-inbox-status]").forEach((b) => b.classList.toggle("active", b === btn));
    caricaInbox();
  });
});

document.querySelectorAll("[data-priorita]").forEach((btn) => {
  btn.addEventListener("click", () => {
    inboxState.priorita = btn.dataset.priorita;
    document.querySelectorAll("[data-priorita]").forEach((b) => b.classList.toggle("active", b === btn));
    caricaInbox();
  });
});

/* ---------- Thread conversazione (storico messaggi) ---------- */

const threadModal = document.getElementById("thread-modal");
const threadModalTitle = document.getElementById("thread-modal-title");
const threadMsgs = document.getElementById("thread-msgs");
const threadFoot = document.getElementById("thread-foot");

const MESSAGE_STATUS_LABEL = {
  received_pending_ai: "ricevuto",
  processing: "in lavorazione",
  handled: "gestito",
  queued: "in coda",
  sending_ambiguous: "invio incerto",
  sent: "inviato",
  delivered: "consegnato",
  read: "letto",
  failed: "non inviato",
};

function chiudiThreadConversazione() {
  if (threadModal) threadModal.hidden = true;
}

/* ---------- Feedback 👍/👎 sulle risposte AI (task 12) ---------- */

function creaControlliFeedback(messaggio) {
  const wrap = document.createElement("div");
  wrap.className = "thread-feedback";

  const btnUp = document.createElement("button");
  btnUp.type = "button";
  btnUp.className = "thread-feedback-btn";
  btnUp.textContent = "👍";
  btnUp.title = "Risposta utile";

  const btnDown = document.createElement("button");
  btnDown.type = "button";
  btnDown.className = "thread-feedback-btn";
  btnDown.textContent = "👎";
  btnDown.title = "Risposta da migliorare";

  // Stato corrente: feedback del cliente (emoji) + voti staff.
  const cliente = messaggio.feedback_customer;
  const upStaff = messaggio.feedback_staff_up || 0;
  const downStaff = messaggio.feedback_staff_down || 0;
  if (cliente === "up") btnUp.classList.add("customer");
  if (cliente === "down") btnDown.classList.add("customer");

  const count = document.createElement("span");
  count.className = "thread-feedback-count";
  count.textContent = `${upStaff}/${downStaff}`;

  const invia = async (value, premuto) => {
    btnUp.disabled = true;
    btnDown.disabled = true;
    try {
      const res = await apiFetch(
        `${API_BASE}/api/inbox/messages/${encodeURIComponent(messaggio.id)}/feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ value }),
        },
      );
      if (!res.ok) throw new Error(`Errore ${res.status}`);
      premuto.classList.add("selected");
      if (value === "up") count.textContent = `${upStaff + 1}/${downStaff}`;
      else count.textContent = `${upStaff}/${downStaff + 1}`;
    } catch (err) {
      console.error("Feedback non inviato:", err);
      btnUp.disabled = false;
      btnDown.disabled = false;
    }
  };
  btnUp.addEventListener("click", () => invia("up", btnUp));
  btnDown.addEventListener("click", () => invia("down", btnDown));

  wrap.appendChild(btnUp);
  wrap.appendChild(btnDown);
  wrap.appendChild(count);
  return wrap;
}

async function apriThreadConversazione(ticket) {
  if (!threadModal || !threadMsgs) return;
  threadModalTitle.textContent = `Conversazione — ${ticket.phone_number || "cliente"}`;
  threadMsgs.innerHTML = "";
  threadFoot.textContent = "Caricamento messaggi...";
  threadModal.hidden = false;
  try {
    const res = await apiFetch(`${API_BASE}/api/inbox/tickets/${encodeURIComponent(ticket.id)}/messages?limit=200`);
    if (!res.ok) throw new Error(`Errore ${res.status}`);
    const data = await res.json();
    const messages = data.messages || [];
    if (!messages.length) {
      threadFoot.textContent = "Nessun messaggio nello storico.";
      return;
    }
    messages.forEach((m) => {
      const bubble = document.createElement("div");
      bubble.className = `thread-bubble ${m.direction === "outbound" ? "out" : "in"}`;
      const text = document.createElement("p");
      text.className = "thread-bubble-text";
      text.textContent = m.content_text || `(messaggio ${m.message_type} senza testo)`;
      const meta = document.createElement("span");
      meta.className = "thread-bubble-meta";
      const status = MESSAGE_STATUS_LABEL[m.status] || m.status;
      const quando = formatInboxDate(m.created_at);
      meta.textContent = m.direction === "outbound" ? `${quando} · ${status}` : quando;
      bubble.appendChild(text);
      bubble.appendChild(meta);
      // Feedback 👍/👎 sulle risposte generate dall'AI (task 12 guardrails):
      // aiuta a capire quali prompt funzionano meglio.
      if (m.direction === "outbound" && m.handling_type === "ai_handled") {
        bubble.appendChild(creaControlliFeedback(m));
      }
      threadMsgs.appendChild(bubble);
    });
    threadFoot.textContent = `${data.total} messaggi nello storico`;
    threadMsgs.scrollTop = threadMsgs.scrollHeight;
  } catch (err) {
    console.error("Impossibile caricare la conversazione:", err);
    threadFoot.textContent = "Impossibile caricare la conversazione.";
  }
}

if (document.getElementById("thread-modal-close")) {
  document.getElementById("thread-modal-close").addEventListener("click", chiudiThreadConversazione);
}
if (threadModal) {
  threadModal.addEventListener("click", (e) => {
    if (e.target === threadModal) chiudiThreadConversazione();
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && threadModal && !threadModal.hidden) chiudiThreadConversazione();
});

/* ---------- Auto-refresh inbox + polling ---------- */

const INBOX_POLL_MS = 15000;
let inboxPollTimer = null;

function avviaInboxPolling() {
  if (inboxPollTimer) return;
  inboxPollTimer = setInterval(() => {
    if (document.visibilityState !== "visible") return;
    caricaInbox();
  }, INBOX_POLL_MS);
}

function fermaInboxPolling() {
  if (inboxPollTimer) {
    clearInterval(inboxPollTimer);
    inboxPollTimer = null;
  }
}

/* ============================================================
   AVVIO
   ============================================================ */

(async function avvia() {
  const loggato = await caricaSessione();
  if (!loggato) {
    apriConfigAccesso();
    return;
  }
  aggiornaRiepilogo();
  aggiornaPrioritari();
  aggiornaReport();
  aggiornaConteggio();
  aggiornaNotifiche();
  setInterval(aggiornaNotifiche, 30000);
  if (document.getElementById("booking-date")) {
    document.getElementById("booking-date").value = oggiIso();
  }
})();
