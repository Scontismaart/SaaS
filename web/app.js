const API_BASE = window.MELPIS_API_BASE ?? "http://localhost:8000";
const PROFILO_ID = "trattoria_da_mario";

/* ============================================================
   AUTENTICAZIONE â€” BFF (task18)
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

/* ============================================================
   TOAST â€” notifiche non bloccanti al posto di alert()
   ============================================================ */

function toast(messaggio, tipo = "info", durata = 4200) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.setAttribute("role", "status");
    container.setAttribute("aria-live", "polite");
    document.body.appendChild(container);
  }
  const el = document.createElement("div");
  el.className = `toast toast-${tipo}`;
  el.textContent = messaggio;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add("toast-in"));
  setTimeout(() => {
    el.classList.remove("toast-in");
    setTimeout(() => el.remove(), 320);
  }, durata);
}

/* ============================================================
   CONFERMA AZIONI DISTRUTTIVE â€” modal riusabile al posto di confirm()
   ============================================================ */

function confermaDestructiva({ titolo = "Conferma azione", descrizione = "", label = "Conferma" } = {}) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirm-modal");
    const titleEl = document.getElementById("confirm-title");
    const descEl = document.getElementById("confirm-desc");
    const okBtn = document.getElementById("confirm-ok-btn");
    const cancelBtn = document.getElementById("confirm-cancel-btn");
    if (!modal || !okBtn || !cancelBtn) {
      resolve(window.confirm(descrizione || titolo));
      return;
    }
    titleEl.textContent = titolo;
    descEl.textContent = descrizione;
    okBtn.textContent = label;
    modal.hidden = false;
    okBtn.focus();

    const chiudi = (esito) => {
      modal.hidden = true;
      okBtn.removeEventListener("click", onOk);
      cancelBtn.removeEventListener("click", onCancel);
      modal.removeEventListener("keydown", onKey);
      resolve(esito);
    };
    function onOk() { chiudi(true); }
    function onCancel() { chiudi(false); }
    function onKey(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        chiudi(false);
      } else if (e.key === "Tab") {
        e.preventDefault();
        (document.activeElement === okBtn ? cancelBtn : okBtn).focus();
      }
    }
    okBtn.addEventListener("click", onOk);
    cancelBtn.addEventListener("click", onCancel);
    modal.addEventListener("keydown", onKey);
  });
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

/* ============================================================
   STATO RETE â€” banner "connessione persa / ripristinata"
   ============================================================ */

let reteInErrore = false;

function mostraBannerRete(testo, online = false, autoHideMs = 0) {
  const netBanner = document.getElementById("net-banner");
  if (!netBanner) return;
  netBanner.textContent = testo;
  netBanner.classList.toggle("online", Boolean(online));
  netBanner.hidden = false;
  if (mostraBannerRete._timer) {
    clearTimeout(mostraBannerRete._timer);
    mostraBannerRete._timer = null;
  }
  if (autoHideMs) {
    mostraBannerRete._timer = setTimeout(() => {
      netBanner.hidden = true;
      mostraBannerRete._timer = null;
    }, autoHideMs);
  }
}

function segnalaErroreRete() {
  reteInErrore = true;
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    mostraBannerRete("Connessione persa â€” i dati non si aggiornano. Controlla la rete.");
  } else {
    mostraBannerRete("Server irraggiungibile â€” riprova tra poco.");
  }
}

function segnaReteOk() {
  if (!reteInErrore) return;
  reteInErrore = false;
  mostraBannerRete("Connessione ripristinata.", true, 3000);
}

window.addEventListener("offline", () => {
  mostraBannerRete("Connessione persa â€” i dati non si aggiornano. Controlla la rete.");
});

window.addEventListener("online", () => {
  if (reteInErrore) segnaReteOk();
  else mostraBannerRete("Connessione ripristinata.", true, 3000);
});

async function tentaRefresh() {
  try {
    return await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: csrfToken() ? { "X-CSRF-Token": csrfToken() } : {},
      credentials: "include",
    });
  } catch (err) {
    segnalaErroreRete();
    throw err;
  }
}

async function apiFetch(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = { ...(options.headers || {}) };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers["X-CSRF-Token"] = token;
  }
  async function tenta() {
    try {
      return await fetch(url, { ...options, headers, credentials: "include" });
    } catch (err) {
      segnalaErroreRete();
      throw err;
    }
  }
  let res = await tenta();
  if (res.status === 401 && !url.includes("/api/auth/")) {
    const refreshRes = await tentaRefresh();
    if (refreshRes.ok) {
      res = await tenta();
    } else {
      sessione = null;
      aggiornaBottoneAccesso();
      vaiAdAccesso();
    }
  }
  segnaReteOk();
  return res;
}

const RUOLO_LABEL = {
  owner: "Proprietario",
  manager: "Manager",
  staff: "Staff",
};

function aggiornaBottoneAccesso() {
  const btn = document.getElementById("accesso-btn");
  const userMenu = document.getElementById("user-menu");
  if (btn) btn.hidden = Boolean(sessione);
  if (userMenu) userMenu.hidden = !sessione;
/* Il billing non Ã¨ piÃ¹ una CTA in topbar: vive nella vista "Piano e
   abbonamento" della sidebar (gruppo Account). */
  if (!sessione) {
    chiudiMenuUtente();
    return;
  }
  const email = sessione.email || "utente";
  const iniziale = (email[0] || "U").toUpperCase();
  const avatarInitial = document.getElementById("avatar-initial");
  const dropdownInitial = document.getElementById("dropdown-initial");
  if (avatarInitial) avatarInitial.textContent = iniziale;
  if (dropdownInitial) dropdownInitial.textContent = iniziale;
  const menuEmail = document.getElementById("user-menu-email");
  const dropdownEmail = document.getElementById("dropdown-email");
  if (menuEmail) menuEmail.textContent = email;
  if (dropdownEmail) dropdownEmail.textContent = email;
  const ruoloEl = document.getElementById("dropdown-ruolo");
  if (ruoloEl) {
    ruoloEl.textContent = RUOLO_LABEL[sessione.ruolo] || sessione.ruolo || "Ospite";
    ruoloEl.className = `ruolo-chip ruolo-${sessione.ruolo || "staff"}`;
  }
}

function toggleMenuUtente(force) {
  const dropdown = document.getElementById("user-dropdown");
  const menuBtn = document.getElementById("user-menu-btn");
  if (!dropdown || !menuBtn) return;
  const apri = typeof force === "boolean" ? force : dropdown.hidden;
  dropdown.hidden = !apri;
  menuBtn.setAttribute("aria-expanded", String(apri));
}

function chiudiMenuUtente() {
  toggleMenuUtente(false);
}

document.getElementById("user-menu-btn")?.addEventListener("click", () => {
  chiudiPannelloNotifiche();
  toggleMenuUtente();
});

document.getElementById("logout-btn")?.addEventListener("click", async () => {
  await faiLogout();
  window.location.href = "/accedi/";
});

/* Login su pagina dedicata /accedi/, registrazione su /registrati/
   (pagine standalone). Il modal Ã¨ stato rimosso. */
function vaiAdAccesso() {
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/accedi/?next=${next}`;
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
  vaiAdAccesso();
});

/* ============================================================
   ACCOUNT â€” Piano e abbonamento (vista dedicata, ex CTA topbar)
   ============================================================ */

const ACCOUNT_PLANS = [
  { slug: "starter", nome: "Essenziale", prezzo: "â‚¬29/mese", limite: "300 conversazioni/mese" },
  { slug: "pro", nome: "Crescita", prezzo: "â‚¬69/mese", limite: "1.200 conversazioni/mese" },
  { slug: "business", nome: "Scala", prezzo: "â‚¬149/mese", limite: "5.000 conversazioni/mese" },
];

function accountStatoPill(stato) {
  const pill = document.getElementById("account-stato");
  if (stato === "active") { pill.textContent = "Attivo"; pill.className = "account-stato-pill"; }
  else if (stato === "trialing") { pill.textContent = "Prova gratuita"; pill.className = "account-stato-pill stato-trial"; }
  else if (stato === "canceled" || stato === "past_due") { pill.textContent = "In pausa"; pill.className = "account-stato-pill stato-pausa"; }
  else { pill.textContent = "Nessun abbonamento"; pill.className = "account-stato-pill stato-pausa"; }
}

async function caricaAccount() {
  const status = document.getElementById("account-status");
  try {
    const res = await apiFetch(`${API_BASE}/api/billing/subscription`);
    if (!res.ok) throw new Error("stato non disponibile");
    const sub = await res.json();
    const stato = sub.subscription_status || "none";
    accountStatoPill(stato);

    const corrente = ACCOUNT_PLANS.find((p) => p.slug === sub.plan);
    document.getElementById("account-plan-nome").textContent = corrente ? corrente.nome : "â€”";
    document.getElementById("account-plan-prezzo").textContent = corrente ? corrente.prezzo : "";

    const rinnovo = document.getElementById("account-rinnovo");
    const dataIt = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString("it-IT"); };
    if (sub.trial_end) rinnovo.textContent = `Prova gratuita fino al ${dataIt(sub.trial_end)}.`;
    else if (stato === "canceled") rinnovo.textContent = "Abbonamento cancellato: il servizio resta attivo fino a fine periodo.";
    else if (sub.current_period_end) rinnovo.textContent = `Prossimo rinnovo: ${dataIt(sub.current_period_end)}.`;
    else rinnovo.textContent = "Nessun rinnovo programmato.";

    // Card cambio piano: quella attiva Ã¨ evidenziata e non cliccabile.
    const wrap = document.getElementById("account-plans");
    wrap.innerHTML = "";
    ACCOUNT_PLANS.forEach((p) => {
      const attuale = p.slug === sub.plan;
      const card = document.createElement("div");
      card.className = "dash-card account-plan-card" + (attuale ? " account-plan-attuale" : "");
      card.innerHTML =
        '<div class="dash-card-header"><span class="dash-card-title">' + p.nome + "</span>" +
        (attuale ? '<span class="account-stato-pill">Attivo</span>' : "") +
        "</div>" +
        '<span class="account-plan-prezzo">' + p.prezzo + "</span>" +
        '<p class="settings-help">' + p.limite + "</p>";
      const actions = document.createElement("div");
      actions.className = "settings-actions";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = attuale ? "report-refresh" : "review-analyze";
      btn.textContent = attuale ? "Piano attivo" : (stato === "canceled" ? "Riattiva " + p.nome : "Passa a " + p.nome);
      if (!attuale) btn.addEventListener("click", () => cambiaPiano(p.slug));
      else btn.disabled = true;
      actions.appendChild(btn);
      card.appendChild(actions);
      wrap.appendChild(card);
    });
    status.hidden = true;
  } catch (err) {
    console.error("Impossibile caricare l'abbonamento:", err);
    status.hidden = false;
    status.textContent = "Impossibile caricare lo stato dell'abbonamento: torna su questa sezione per riprovare.";
    status.style.color = "var(--red)";
  }
}

async function cambiaPiano(slug) {
  const status = document.getElementById("account-status");
  try {
    const res = await apiFetch(`${API_BASE}/api/billing/create-checkout-session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plan: slug,
        interval: "monthly",
        success_url: window.location.origin + "/app/",
        cancel_url: window.location.origin + "/app/",
      }),
    });
    if (!res.ok) throw new Error("checkout non disponibile");
    const data = await res.json();
    if (data.url) window.location.href = data.url;
  } catch (e) {
    console.error("Errore cambio piano:", e);
    status.hidden = false;
    status.textContent = "Impossibile avviare il cambio piano. Riprova piÃ¹ tardi.";
    status.style.color = "var(--red)";
  }
}

async function apriPortaleBilling() {
  const status = document.getElementById("account-status");
  try {
    const res = await apiFetch(`${API_BASE}/api/billing/create-portal-session`, { method: "POST" });
    if (!res.ok) throw new Error("portale non disponibile");
    const data = await res.json();
    if (data.url) window.location.href = data.url;
  } catch (e) {
    console.error("Errore apertura portale billing:", e);
    status.hidden = false;
    status.textContent = "Impossibile aprire il portale Stripe. Riprova piÃ¹ tardi.";
    status.style.color = "var(--red)";
  }
}

document.getElementById("account-portal-btn")?.addEventListener("click", apriPortaleBilling);
document.getElementById("account-cancel-btn")?.addEventListener("click", apriPortaleBilling);

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
  inbox: 0,
  prenotazioni: 0,
  recensioni: 0,
  conoscenza: 0,
};

/* Chiavi delle notifiche nate prima della riorganizzazione della sidebar:
   la migrazione preserva lo stato "giÃ  letto" (timestamp) di chi le aveva
   viste, altrimenti le notifiche ricomparirebbero come nuove. */
const NOTIF_KEY_MIGRATION = {
  documenti: "conoscenza",
  report: null, // badge rimosso: la voce non esiste piÃ¹
  panoramica: null, // badge aggregato rimosso (ora Inbox e Recensioni hanno i propri)
  assistente: null,
};

function migraStatoNotifiche(stato) {
  if (!stato || !stato.viste) return stato;
  let migrato = false;
  for (const [vecchia, nuova] of Object.entries(NOTIF_KEY_MIGRATION)) {
    if (!(vecchia in stato.viste)) continue;
    migrato = true;
    if (nuova && !(nuova in stato.viste)) {
      stato.viste[nuova] = stato.viste[vecchia];
    }
    delete stato.viste[vecchia];
  }
  if (migrato) salvaStatoNotifiche(stato);
  return stato;
}

function leggiStatoNotifiche() {
  try {
    const stato = JSON.parse(localStorage.getItem(NOTIFICATION_STORAGE_KEY) || "null") || { inizializzato: false, viste: {} };
    return migraStatoNotifiche(stato);
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
  aggiornaCampana();
}

/* Destinazioni di fallback per chiavi di viste non piÃ¹ presenti nella nav
   (notifiche salvate prima della riorganizzazione, link memorizzati):
   apre la vista contenitore e, se prevista, il tab giusto dentro
   Impostazioni â€” mai un no-op silenzioso. */
const VIEW_FALLBACK = {
  audit: { view: "impostazioni", tab: "audit" },
  integrazioni: { view: "impostazioni", tab: "integrazioni" },
  documenti: { view: "conoscenza" },
  report: { view: "panoramica" },
  onboarding: { view: "assistente" },
};

function apriView(key) {
  const btn = document.querySelector(`.nav-item[data-view="${key}"]`);
  if (btn) {
    btn.click();
    return true;
  }
  const dest = VIEW_FALLBACK[key];
  if (!dest) return false;
  const container = document.querySelector(`.nav-item[data-view="${dest.view}"]`);
  if (container) container.click();
  if (dest.tab) attivaTabImpostazioni(dest.tab);
  return true;
}

/* --- Tab Impostazioni: Generale / Integrazioni / Audit --- */

function attivaTabImpostazioni(tab) {
  document.querySelectorAll("[data-settings-tab-btn]").forEach((b) => {
    const on = b.dataset.settingsTabBtn === tab;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });
  document.querySelectorAll("[data-settings-pane]").forEach((p) => {
    p.hidden = p.dataset.settingsPane !== tab;
  });
  if (tab === "integrazioni") caricaIntegrazioni();
  if (tab === "audit") caricaAudit();
}

document.querySelectorAll("[data-settings-tab-btn]").forEach((btn) => {
  btn.addEventListener("click", () => attivaTabImpostazioni(btn.dataset.settingsTabBtn));
});

async function aggiornaNotifiche() {
  try {
    const summaryResponse = await apiFetch(`${API_BASE}/api/ui/summary`);
    const summary = summaryResponse.ok ? await summaryResponse.json() : {};
    notificationItems = {
      inbox: summary.inbox_attivi || 0,
      prenotazioni: summary.prenotazioni || 0,
      recensioni: summary.recensioni_da_approvare || 0,
      conoscenza: summary.documenti || 0,
    };
    const stato = leggiStatoNotifiche();
    if (!stato.inizializzato) {
      stato.inizializzato = true;
      stato.viste = { ...notificationItems };
      salvaStatoNotifiche(stato);
    }
    aggiornaBadgeNotifiche(stato);
    aggiornaCampana();
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

    // Su mobile il drawer resta aperto dopo la navigazione: chiudilo sempre
    // (no-op su desktop dove il drawer non Ã¨ mai "aperto").
    chiudiMenuMobile();

    navItems.forEach((n) => n.classList.remove("active"));
    btn.classList.add("active");

    views.forEach((v) => {
      v.classList.toggle("view-hidden", v.dataset.viewPanel !== viewName);
    });

    const titles = {
      panoramica: "Panoramica",
      inbox: "Inbox",
      prenotazioni: "Prenotazioni",
      recensioni: "Recensioni",
      assistente: "Assistente",
      conoscenza: "Conoscenza",
      impostazioni: "Impostazioni",
      account: "Piano e abbonamento",
      onboarding: "Configurazione assistente",
    };
    topbarTitle.textContent = titles[viewName] || viewName;
    if (viewName === "impostazioni") {
      // Hub a tab: precarico i dati di tutti i pane (lazy per tab sarebbe
      // over-engineering: sono tre chiamate leggere). Il fuso orario si
      // gestisce da solo (IIFE inizializzaTimezone con flag "caricato").
      caricaIntegrazioni();
      caricaAudit();
    }
    if (viewName === "account") caricaAccount();

    if (viewName === "panoramica") {
      aggiornaRiepilogo();
      aggiornaPrioritari();
    }
    if (viewName === "assistente") {
      // Il wizard salva solo owner/manager (gate lato API): per lo staff
      // la card "Configura" non ha senso, la rimuoviamo dal DOM.
      if (sessione?.ruolo === "staff") document.getElementById("onboarding-banner")?.remove();
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
    if (viewName === "documenti" || viewName === "conoscenza") {
      aggiornaConteggio();
      aggiornaDocumenti();
    }
    if (viewName === "inbox") {
      avviaInboxPolling();
      caricaInbox();
    } else {
      fermaInboxPolling();
    }
    chiudiMenuMobile();
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
    nome_attivita: onboardingEls.name.value.trim() || "Nuova attivitÃ ",
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
  salvaBozzaOnboarding();
}

function salvaBozzaOnboarding() {
  /* Bozza in localStorage: il wizard resta riprendibile anche se il
     browser si chiude a metÃ . I dati sono non-sensibili (profilo attivitÃ ). */
  try {
    const bozza = { step: onboardingState.step, salvata_at: new Date().toISOString(), profilo: profiloOnboarding() };
    localStorage.setItem("melpis_onboarding_bozza", JSON.stringify(bozza));
    const badge = document.getElementById("onboarding-autosave");
    if (badge) {
      const ora = new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
      badge.textContent = `Bozza salvata Â· ${ora}`;
      badge.hidden = false;
    }
  } catch { /* localStorage pieno/bloccato: non blocca il wizard */ }
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
    vaiAdAccesso();
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

/* ============================================================
   ONBOARDING â€” accesso dal banner in "Assistente" (voce nav rimossa)
   ============================================================ */

function apriOnboarding() {
  chiudiMenuMobile();
  navItems.forEach((n) => n.classList.remove("active"));
  views.forEach((v) => {
    v.classList.toggle("view-hidden", v.dataset.viewPanel !== "onboarding");
  });
  topbarTitle.textContent = "Configurazione assistente";
  // Pre-compila il wizard dal profilo salvato: il wizard Ã¨ l'unico editor
  // della configurazione assistente (le card duplicate in Impostazioni sono
  // state rimosse).
  inizializzaOnboarding();
}

function chiudiOnboarding() {
  document.querySelector('.nav-item[data-view="assistente"]')?.click();
}

document.getElementById("onboarding-banner-cta")?.addEventListener("click", apriOnboarding);
document.getElementById("onboarding-chiudi")?.addEventListener("click", chiudiOnboarding);


/* â”€â”€ Sicurezza account: cambio password/email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */

const SECURITY_PASSWORD_MIN = 10;

function securityStatus(el, testo, errore = false) {
  if (!el) return;
  el.textContent = testo;
  el.style.color = errore ? "var(--red)" : "var(--green-deep)";
}

document.getElementById("security-password-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pwd = document.getElementById("security-password")?.value || "";
  const conferma = document.getElementById("security-password-confirm")?.value || "";
  const status = document.getElementById("security-password-status");
  const submit = e.target.querySelector(".security-submit");
  if (pwd.length < SECURITY_PASSWORD_MIN || !/[^A-Za-z0-9]/.test(pwd)) {
    securityStatus(status, `Min ${SECURITY_PASSWORD_MIN} caratteri e almeno un simbolo (es. ! @ #)`, true);
    return;
  }
  if (pwd !== conferma) {
    securityStatus(status, "Le due password non coincidono", true);
    return;
  }
  submit.disabled = true;
  securityStatus(status, "Aggiornoâ€¦");
  try {
    const res = await apiFetch(`${API_BASE}/api/auth/password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pwd }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      securityStatus(status, data.detail || "Aggiornamento non riuscito", true);
      return;
    }
    securityStatus(status, data.message || "Password aggiornata");
    document.getElementById("security-password").value = "";
    document.getElementById("security-password-confirm").value = "";
  } catch {
    securityStatus(status, "Errore di connessione", true);
  } finally {
    submit.disabled = false;
  }
});

document.getElementById("security-email-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("security-email")?.value.trim() || "";
  const status = document.getElementById("security-email-status");
  const submit = e.target.querySelector(".security-submit");
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    securityStatus(status, "Inserisci un indirizzo email valido", true);
    return;
  }
  submit.disabled = true;
  securityStatus(status, "Aggiornoâ€¦");
  try {
    const res = await apiFetch(`${API_BASE}/api/auth/email`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      securityStatus(status, data.detail || "Aggiornamento non riuscito", true);
      return;
    }
    securityStatus(status, data.message || "Email aggiornata");
    document.getElementById("security-email").value = "";
  } catch {
    securityStatus(status, "Errore di connessione", true);
  } finally {
    submit.disabled = false;
  }
});

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
  document.querySelector('[data-view="conoscenza"]')?.click();
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

const STATI_FINALI_PRENOTAZIONE = ["cancellata", "cancellato", "rifiutata", "no_show", "completata"];
let prenotazioneCorrente = null;

function statoNormalizzatoPrenotazione(p) {
  return String(p?.stato || "").toLowerCase().trim().replace(/\s+/g, "_");
}

function aggiornaAzioniPrenotazione(p) {
  const wrap = document.getElementById("booking-detail-actions");
  if (!wrap || !p) {
    if (wrap) wrap.hidden = true;
    return;
  }
  const staff = Boolean(sessione && sessione.ruolo === "staff");
  const confermaBtn = document.getElementById("booking-confirm-btn");
  const rifiutaBtn = document.getElementById("booking-reject-btn");
  const annullaBtn = document.getElementById("booking-cancel-btn");
  if (!confermaBtn || !rifiutaBtn || !annullaBtn) return;
  const stato = statoNormalizzatoPrenotazione(p);
  const finale = STATI_FINALI_PRENOTAZIONE.includes(stato);
  confermaBtn.hidden = staff || finale || stato === "confermata";
  rifiutaBtn.hidden = staff || finale || stato === "rifiutata";
  annullaBtn.hidden = staff || finale;
  wrap.hidden = confermaBtn.hidden && rifiutaBtn.hidden && annullaBtn.hidden;
}

async function eseguiAzionePrenotazione(azione, { chiediConferma = false, titolo = "", descrizione = "", label = "Conferma" } = {}) {
  const p = prenotazioneCorrente;
  if (!p?.id) return;
  if (chiediConferma) {
    const ok = await confermaDestructiva({ titolo, descrizione, label });
    if (!ok) return;
  }
  const bottoni = ["booking-confirm-btn", "booking-reject-btn", "booking-cancel-btn"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  bottoni.forEach((b) => { b.disabled = true; });
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings/${encodeURIComponent(p.id)}/${azione}`, { method: "POST" });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Operazione non riuscita.");
    }
    chiudiDettaglioPrenotazione();
    toast(
      azione === "confirm" ? "Prenotazione confermata."
        : azione === "reject" ? "Prenotazione rifiutata."
          : "Prenotazione annullata.",
      azione === "confirm" ? "success" : "info",
    );
    await Promise.all([
      aggiornaPrenotazioni(),
      p.data ? aggiornaListaGiorno(p.data) : Promise.resolve(),
      p.data ? aggiornaSemaforo(p.data) : Promise.resolve(),
    ]);
  } catch (err) {
    toast(err.message || "Errore di connessione.", "error");
  } finally {
    bottoni.forEach((b) => { b.disabled = false; });
  }
}

document.getElementById("booking-confirm-btn")?.addEventListener("click", () => {
  eseguiAzionePrenotazione("confirm");
});

document.getElementById("booking-reject-btn")?.addEventListener("click", () => {
  eseguiAzionePrenotazione("reject", {
    chiediConferma: true,
    titolo: "Rifiutare la prenotazione?",
    descrizione: `La richiesta di ${prenotazioneCorrente?.nome_cliente || "questo cliente"} verrÃ  contrassegnata come rifiutata e il cliente non avrÃ  il tavolo riservato.`,
    label: "Rifiuta",
  });
});

document.getElementById("booking-cancel-btn")?.addEventListener("click", () => {
  eseguiAzionePrenotazione("cancel", {
    chiediConferma: true,
    titolo: "Annullare la prenotazione?",
    descrizione: `La prenotazione di ${prenotazioneCorrente?.nome_cliente || "questo cliente"} verrÃ  annullata e i posti torneranno disponibili.`,
    label: "Annulla prenotazione",
  });
});

function apriDettaglioPrenotazione(prenotazione) {
  if (!bookingModal || !prenotazione) return;
  const valore = (dato, fallback = "Non indicato") => dato || fallback;
  const data = prenotazione.data
    ? new Date(`${prenotazione.data}T12:00:00`).toLocaleDateString("it-IT", {
      weekday: "long", day: "2-digit", month: "long", year: "numeric",
    })
    : "Non indicata";
  prenotazioneCorrente = prenotazione;
  bookingDetail.title.textContent = valore(prenotazione.nome_cliente, "Cliente");
  bookingDetail.date.textContent = data;
  bookingDetail.time.textContent = valore(prenotazione.ora);
  bookingDetail.seats.textContent = prenotazione.coperti ? `${prenotazione.coperti} coperti` : "Non indicati";
  bookingDetail.status.textContent = valore(prenotazione.stato);
  bookingDetail.phone.textContent = valore(prenotazione.telefono);
  bookingDetail.origin.textContent = valore(prenotazione.origine);
  bookingDetail.note.textContent = valore(prenotazione.note, "Nessuna nota");
  aggiornaAzioniPrenotazione(prenotazione);
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
    const visibili = items.slice(0, 8);
    visibili.forEach((p) => {
      const item = document.createElement("article");
      item.className = "booking-row";
      const ora = String(p.ora || "").slice(0, 5);
      item.innerHTML = `
        <time class="booking-row-time">${_sanitize(ora) || "--:--"}</time>
        <div class="booking-row-main"><strong>${_sanitize(p.nome_cliente) || "Cliente"}</strong><span>${_sanitize(p.coperti) || "?"} coperti${p.telefono ? ` Â· ${_sanitize(p.telefono)}` : ""}</span></div>
        <span class="booking-row-status" style="--booking-color:${_sanitize(colorePrenotazione(p.stato))}">${_sanitize(p.stato) || "In attesa"}</span>`;
      bookingDayList.appendChild(item);
    });
    if (items.length > visibili.length) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "inbox-load-more";
      more.textContent = `Mostra tutte (${items.length})`;
      more.addEventListener("click", () => {
        more.remove();
        items.slice(visibili.length).forEach((p) => {
          const item = document.createElement("article");
          item.className = "booking-row";
          const ora = String(p.ora || "").slice(0, 5);
          item.innerHTML = `
            <time class="booking-row-time">${_sanitize(ora) || "--:--"}</time>
            <div class="booking-row-main"><strong>${_sanitize(p.nome_cliente) || "Cliente"}</strong><span>${_sanitize(p.coperti) || "?"} coperti${p.telefono ? ` Â· ${_sanitize(p.telefono)}` : ""}</span></div>
            <span class="booking-row-status" style="--booking-color:${_sanitize(colorePrenotazione(p.stato))}">${_sanitize(p.stato) || "In attesa"}</span>`;
          bookingDayList.appendChild(item);
        });
      }, { once: true });
      bookingDayList.appendChild(more);
    }
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
    toast("Errore: " + err.message, "error");
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
    toast("Errore: " + err.message, "error");
    reviewApprove.disabled = false;
    reviewApprove.textContent = "Approva risposta";
  }
}

const trendList = document.getElementById("trend-list");
let trendPrimoCaricamento = true;

function _paroleChiave(testi, max = 3) {
  const stop = ["di", "il", "la", "le", "gli", "un", "una", "che", "per", "con", "non", "ho", "ha", "Ã¨", "e", "a", "o", "si", "in", "da", "lo", "sono", "mi", "ma", "ci", "ti", "al", "del", "della", "dei", "delle", "allo", "alla", "ai", "agli", "alle", "dal", "dalla", "dai", "dagli", "dalle", "nel", "nella", "nei", "negli", "nelle", "sul", "sulla", "sui", "sugli", "sulle", "molto", "tanto", "piÃ¹", "meno", "era", "stato", "stata", "stati", "state", "essere", "questo", "quella", "quello", "conto", "fare", "fatto"];
  const words = testi.join(" ").toLowerCase().replace(/[^a-zÃ Ã¨Ã©Ã¬Ã²Ã¹\s]/g, "").split(/\s+/).filter(w => w.length > 3 && !stop.includes(w));
  const freq = {};
  words.forEach(w => { freq[w] = (freq[w] || 0) + 1; });
  return Object.entries(freq).sort((a,b) => b[1] - a[1]).slice(0, max).map(e => e[0]);
}

async function aggiornaTrends() {
  try {
    if (trendPrimoCaricamento && trendList) {
      trendList.innerHTML = _skeletonList(3);
      trendPrimoCaricamento = false;
    }
    const res = await apiFetch(`${API_BASE}/api/dashboard`);
    if (!res.ok) {
      trendList.innerHTML = "";
      trendList.appendChild(_errorState("Impossibile caricare le statistiche.", aggiornaTrends));
      return;
    }
    const eventi = await res.json();
    const recensioni = eventi.filter(e => e.tipo_evento === "recensione");
    const totale = recensioni.length;

    if (totale === 0) {
      trendList.innerHTML = "";
      const li = document.createElement("li");
      li.appendChild(_emptyState(
        ICONS.trend,
        "Nessuna recensione ancora",
        "Incolla una recensione qui a fianco: l'assistente valuta il tono e individua i temi ricorrenti.",
        "Analizza una recensione",
        () => document.getElementById("review-text")?.focus()
      ));
      trendList.appendChild(li);
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
    if (trendList) {
      trendList.innerHTML = "";
      trendList.appendChild(_errorState("Impossibile caricare le statistiche.", aggiornaTrends));
    }
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

/* â”€â”€ Export CSV prenotazioni (endpoint /api/report/csv) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */

async function scaricaCsvPrenotazioni(da, a) {
  const params = new URLSearchParams();
  if (da) params.set("da", da);
  if (a) params.set("a", a);
  let res;
  try {
    res = await apiFetch(`${API_BASE}/api/report/csv?${params.toString()}`);
  } catch {
    toast("Errore di connessione durante l'export.", "error");
    return;
  }
  if (res.status === 403) {
    toast("Export disponibile per proprietario e manager.", "error");
    return;
  }
  if (!res.ok) {
    toast("Export non riuscito. Riprova.", "error");
    return;
  }
  const blob = await res.blob();
  const dispo = res.headers.get("Content-Disposition") || "";
  const match = dispo.match(/filename="?([^"]+)"?/);
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = match ? match[1] : "prenotazioni.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  toast("Export scaricato.", "success");
}

document.getElementById("report-export-csv")?.addEventListener("click", () => scaricaCsvPrenotazioni());

document.getElementById("booking-export-csv")?.addEventListener("click", () => {
  const da = document.getElementById("booking-export-da")?.value || "";
  const a = document.getElementById("booking-export-a")?.value || "";
  if (da && a && da > a) {
    toast("La data inizio Ã¨ dopo la data fine.", "error");
    return;
  }
  scaricaCsvPrenotazioni(da, a);
});

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
const statTotale = document.getElementById("stat-totale");
const statAi = document.getElementById("stat-ai");
const statUmano = document.getElementById("stat-umano");

function _skeletonList(n = 3) {
  return (
    '<div class="skeleton-list">' +
    '<div class="skeleton skeleton-line-lg"></div>'.repeat(n) +
    "</div>"
  );
}

const ICONS = {
  inbox: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 6.5h16v11H4v-11Z"/><path d="M4 8l8 6 8-6" stroke-linecap="round"/></svg>',
  doc: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M7 4h10v16H7V4Z"/><path d="M10 9h4M10 13h4" stroke-linecap="round"/></svg>',
  trend: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M5 20V10M12 20V4M19 20v-7"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5.5h16v10H9l-4 4v-4H4v-10Z"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4L2.5 20h19L12 4Z"/><path d="M12 10v4M12 17.5v.01"/></svg>',
};

function _emptyState(icon, titolo, sottotitolo, ctaLabel, ctaAction) {
  const wrap = document.createElement("div");
  wrap.className = "empty-state";
  wrap.innerHTML =
    '<div class="empty-state-icon" aria-hidden="true">' + icon + "</div>" +
    '<span class="empty-state-title">' + _sanitize(titolo) + "</span>" +
    '<span class="empty-state-sub">' + _sanitize(sottotitolo) + "</span>";
  if (ctaLabel) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "review-analyze";
    btn.textContent = ctaLabel;
    btn.addEventListener("click", ctaAction);
    wrap.appendChild(btn);
  }
  return wrap;
}

/* Stato errore con retry: usato al posto del skeleton infinito quando una
   chiamata API fallisce (l'utente deve capire che puÃ² riprovare, non che
   la sezione sia vuota). */
function _errorState(messaggio, retryFn) {
  const wrap = document.createElement("div");
  wrap.className = "error-state";
  wrap.setAttribute("role", "alert");
  wrap.innerHTML =
    '<div class="empty-state-icon error" aria-hidden="true">' + ICONS.alert + "</div>" +
    '<span class="empty-state-title">Qualcosa Ã¨ andato storto</span>' +
    '<span class="empty-state-sub">' + _sanitize(messaggio) + "</span>";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "review-analyze";
  btn.textContent = "Riprova";
  btn.addEventListener("click", retryFn);
  wrap.appendChild(btn);
  return wrap;
}

async function aggiornaPrioritari() {
  priorityList.innerHTML = _skeletonList(3);
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard/prioritari`);
    if (!res.ok) {
      priorityList.innerHTML = "";
      priorityList.appendChild(_errorState("Impossibile caricare le richieste urgenti.", aggiornaPrioritari));
      return;
    }
    const eventi = await res.json();
    priorityList.innerHTML = "";
    if (eventi.length === 0) {
      const li = document.createElement("li");
      li.appendChild(_emptyState(
        ICONS.check,
        "Tutto sotto controllo",
        "Nessuna richiesta urgente: l'assistente sta gestendo le conversazioni."
      ));
      priorityList.appendChild(li);
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
    priorityList.innerHTML = "";
    priorityList.appendChild(_errorState("Impossibile caricare le richieste urgenti.", aggiornaPrioritari));
  }
}

async function aggiornaRiepilogo() {
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard`);
    if (!res.ok) {
      ticketList.innerHTML = "";
      ticketList.appendChild(_errorState("Impossibile caricare l'attivitÃ  recente.", aggiornaRiepilogo));
      return;
    }
    const storico = await res.json();
    const totale = storico.length;
    const gestitiAi = storico.filter((e) => e.gestito_da_ai).length;
    const girati = totale - gestitiAi;
    statTotale.textContent = totale;
    statAi.textContent = gestitiAi;
    statUmano.textContent = girati;
    ticketList.innerHTML = "";
    if (totale === 0) {
      ticketList.appendChild(_emptyState(
        ICONS.chat,
        "Nessuna attivitÃ  ancora",
        "Parla con l'assistente dalla sezione Assistente: le conversazioni compaiono qui.",
        "Prova l'assistente",
        () => document.querySelector('[data-view="assistente"]')?.click()
      ));
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
    ticketList.innerHTML = "";
    ticketList.appendChild(_errorState("Impossibile caricare l'attivitÃ  recente.", aggiornaRiepilogo));
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
let docPrimoCaricamento = true;

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
    if (docPrimoCaricamento) {
      docLibrary.innerHTML = _skeletonList(3);
      docPrimoCaricamento = false;
    }
    const res = await apiFetch(`${API_BASE}/api/documenti/elenco`);
    if (!res.ok) {
      docLibrary.innerHTML = "";
      docLibrary.appendChild(_errorState("Impossibile caricare i documenti.", aggiornaDocumenti));
      return;
    }
    const data = await res.json();
    docLibrary.innerHTML = "";
    if (!data.documenti?.length) {
      docLibrary.appendChild(_emptyState(
        ICONS.doc,
        "Knowledge base vuota",
        "Carica menu, listini o lista allergeni: l'assistente li userÃ  per rispondere ai clienti.",
        "Carica il primo documento",
        () => {
          document.getElementById("doc-carica-testo")?.focus();
          document.getElementById("doc-carica-testo")?.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      ));
      return;
    }
    const DOC_PAGE = 15;
    const docRenderItem = (documento) => {
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
        const ok = await confermaDestructiva({
          titolo: "Rimuovere il documento?",
          descrizione: `${documento.nome} verrÃ  eliminato dalla knowledge base e l'assistente non potrÃ  piÃ¹ usarlo per rispondere.`,
          label: "Rimuovi",
        });
        if (!ok) return;
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
    };
    // Paginazione client-side: i primi DOC_PAGE, il resto dietro "Mostra tutti"
    data.documenti.slice(0, DOC_PAGE).forEach(docRenderItem);
    if (data.documenti.length > DOC_PAGE) {
      const more = document.createElement("button");
      more.type = "button";
      more.className = "inbox-load-more";
      more.textContent = `Mostra tutti (${data.documenti.length})`;
      more.addEventListener("click", () => {
        more.remove();
        data.documenti.slice(DOC_PAGE).forEach(docRenderItem);
      }, { once: true });
      docLibrary.appendChild(more);
    }
  } catch (err) {
    console.error("Impossibile caricare l'elenco documenti:", err);
    docLibrary.innerHTML = "";
    docLibrary.appendChild(_errorState("Impossibile caricare i documenti.", aggiornaDocumenti));
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
const inboxCount = document.getElementById("inbox-count");
let inboxState = {
  status: "ALL",
  priorita: "",
};

function filtersAttivi() {
  return inboxState.status !== "ALL" || Boolean(inboxState.priorita);
}

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

let inboxPrimoCaricamento = true;
let inboxOffset = 0;
let inboxHasMore = false;
const INBOX_PAGE_SIZE = 20;

async function caricaInbox({ append = false } = {}) {
  if (!inboxList) return;
  if (!append) {
    inboxOffset = 0;
    if (inboxPrimoCaricamento) {
      inboxList.innerHTML = _skeletonList(3);
      inboxPrimoCaricamento = false;
    }
  }
  try {
    const params = new URLSearchParams();
    if (inboxState.status !== "ALL") params.set("status", inboxState.status);
    if (inboxState.priorita) params.set("priorita", inboxState.priorita);
    params.set("limit", String(INBOX_PAGE_SIZE));
    params.set("offset", String(inboxOffset));
    const res = await apiFetch(`${API_BASE}/api/inbox/tickets?${params.toString()}`);
    if (!res.ok) {
      if (!append && inboxList) {
        inboxList.innerHTML = "";
        inboxList.appendChild(_errorState("Impossibile caricare l'inbox.", () => caricaInbox()));
      }
      return;
    }
    const data = await res.json();
    const tickets = data.tickets || [];
    inboxHasMore = Boolean(data.has_more);

    let team = [];
    try {
      const teamRes = await apiFetch(`${API_BASE}/api/inbox/team`);
      if (teamRes.ok) team = (await teamRes.json()).members || [];
    } catch (e) {
      console.error("Impossibile caricare il team:", e);
    }

    if (!append) {
      inboxList.innerHTML = "";
      if (!tickets.length) {
        inboxCount.textContent = "0 ticket";
        inboxList.appendChild(_emptyState(
          ICONS.inbox,
          filtersAttivi() ? "Nessun ticket con questi filtri" : "Nessun ticket aperto",
          "Quando l'assistente incontra una richiesta delicata, la conversazione finisce qui per la presa in carico."
        ));
        return;
      }
    } else {
      document.getElementById("inbox-load-more")?.remove();
    }

    tickets.forEach((t) => renderInboxCard(inboxList, t, team));
    inboxOffset += tickets.length;
    inboxCount.textContent = `${inboxOffset} ticket`;

    if (inboxHasMore) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = "inbox-load-more";
      btn.className = "inbox-load-more";
      btn.textContent = "Carica altri ticket";
      btn.addEventListener("click", () => {
        btn.disabled = true;
        btn.textContent = "Caricoâ€¦";
        caricaInbox({ append: true });
      });
      inboxList.appendChild(btn);
    }
  } catch (err) {
    console.error("Impossibile caricare l'inbox:", err);
    if (!append && inboxList) {
      inboxList.innerHTML = "";
      inboxList.appendChild(_errorState("Impossibile caricare l'inbox.", () => caricaInbox()));
    }
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
    placeholder.textContent = "Assegna aâ€¦";
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
        toast(err.message, "error");
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
        toast(err.message, "error");
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
        toast(err.message, "error");
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
        toast(err.message, "error");
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

/* ---------- Feedback ðŸ‘/ðŸ‘Ž sulle risposte AI (task 12) ---------- */

function creaControlliFeedback(messaggio) {
  const wrap = document.createElement("div");
  wrap.className = "thread-feedback";

  const btnUp = document.createElement("button");
  btnUp.type = "button";
  btnUp.className = "thread-feedback-btn";
  btnUp.textContent = "ðŸ‘";
  btnUp.title = "Risposta utile";

  const btnDown = document.createElement("button");
  btnDown.type = "button";
  btnDown.className = "thread-feedback-btn";
  btnDown.textContent = "ðŸ‘Ž";
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
  threadModalTitle.textContent = `Conversazione â€” ${ticket.phone_number || "cliente"}`;
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
      meta.textContent = m.direction === "outbound" ? `${quando} Â· ${status}` : quando;
      bubble.appendChild(text);
      bubble.appendChild(meta);
      // Feedback ðŸ‘/ðŸ‘Ž sulle risposte generate dall'AI (task 12 guardrails):
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
   MENU MOBILE â€” sidebar off-canvas sotto 1100px
   ============================================================ */

const navToggle = document.getElementById("nav-toggle");
const sidebarOverlay = document.getElementById("sidebar-overlay");

function chiudiMenuMobile() {
  const eraAperto = document.body.classList.contains("nav-open");
  document.body.classList.remove("nav-open");
  if (navToggle) navToggle.setAttribute("aria-expanded", "false");
  if (sidebarOverlay) sidebarOverlay.hidden = true;
  // Se il focus era dentro il drawer APERTO, torna al toggle (a11y: niente
  // focus perso su elemento invisibile). Su desktop (drawer mai aperto) il
  // focus non viene toccato.
  if (eraAperto && navToggle) {
    const sidebarAperta = document.querySelector(".sidebar");
    if (sidebarAperta && sidebarAperta.contains(document.activeElement)) {
      navToggle.focus();
    }
  }
}

function apriMenuMobile() {
  document.body.classList.add("nav-open");
  if (navToggle) navToggle.setAttribute("aria-expanded", "true");
  if (sidebarOverlay) sidebarOverlay.hidden = false;
  // Il focus parte dentro il drawer, sul primo elemento navigabile.
  const primo = document.querySelector(".sidebar .nav-item");
  if (primo) primo.focus();
}

navToggle?.addEventListener("click", () => {
  if (document.body.classList.contains("nav-open")) chiudiMenuMobile();
  else apriMenuMobile();
});

sidebarOverlay?.addEventListener("click", chiudiMenuMobile);

/* Focus-trap del drawer (a11y 2.4.3): con il menu mobile aperto il Tab cicla
   solo dentro la sidebar; Tab oltre l'ultimo elemento chiude il drawer e
   riporta il focus al toggle. */
document.addEventListener("keydown", (event) => {
  if (event.key !== "Tab" || !document.body.classList.contains("nav-open")) return;
  const sidebar = document.querySelector(".sidebar");
  if (!sidebar) return;
  const focusabili = sidebar.querySelectorAll(
    "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"
  );
  if (!focusabili.length) return;
  const primo = focusabili[0];
  const ultimo = focusabili[focusabili.length - 1];
  if (event.shiftKey && document.activeElement === primo) {
    event.preventDefault();
    ultimo.focus();
  } else if (!event.shiftKey && document.activeElement === ultimo) {
    event.preventDefault();
    chiudiMenuMobile();
  }
});

/* Chiusura dropdown su click fuori (menu utente + notifiche) */

document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  if (!event.target.closest("#user-menu")) chiudiMenuUtente();
  if (!event.target.closest(".notif-wrap")) chiudiPannelloNotifiche();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  chiudiMenuMobile();
  chiudiMenuUtente();
  chiudiPannelloNotifiche();
});

/* ============================================================
   CENTRO NOTIFICHE â€” campana in topbar
   Aggrega i conteggi giÃ  calcolati in notificationItems
   (aggiornati ogni 30s da aggiornaNotifiche).
   ============================================================ */

const NOTIF_LABELS = {
  panoramica: "Panoramica",
  assistente: "Assistente",
  recensioni: "Recensioni",
  prenotazioni: "Prenotazioni",
  documenti: "Documenti",
  report: "Report",
  inbox: "Inbox",
};

const notifBell = document.getElementById("notif-bell");
const notifPanel = document.getElementById("notif-panel");
const notifList = document.getElementById("notif-list");
const bellBadge = document.getElementById("bell-badge");

function conteggioNonViste() {
  const stato = leggiStatoNotifiche();
  return Object.keys(NOTIF_LABELS).map((key) => {
    const totale = Number(notificationItems[key] || 0);
    const viste = Number(stato.viste?.[key] || 0);
    return { key, nonViste: Math.max(0, totale - viste) };
  });
}

function aggiornaCampana() {
  if (!bellBadge) return;
  const totale = conteggioNonViste().reduce((somma, riga) => somma + riga.nonViste, 0);
  bellBadge.textContent = totale > 99 ? "99+" : String(totale);
  bellBadge.hidden = totale === 0;
}

function renderPannelloNotifiche() {
  if (!notifList) return;
  const righe = conteggioNonViste();
  notifList.innerHTML = "";
  if (!righe.some((riga) => riga.nonViste > 0)) {
    const p = document.createElement("p");
    p.className = "notif-empty";
    p.textContent = "Tutto aggiornato: nessuna novitÃ .";
    notifList.appendChild(p);
    return;
  }
  righe.forEach(({ key, nonViste }) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = `notif-row${nonViste > 0 ? " has-new" : ""}`;
    row.setAttribute("role", "menuitem");
    const label = document.createElement("span");
    label.className = "notif-row-label";
    label.textContent = NOTIF_LABELS[key] || key;
    const count = document.createElement("span");
    count.className = "notif-count";
    count.textContent = String(nonViste);
    row.append(label, count);
    row.addEventListener("click", () => {
      chiudiPannelloNotifiche();
      apriView(key);
    });
    notifList.appendChild(row);
  });
}

function togglePannelloNotifiche(force) {
  if (!notifPanel || !notifBell) return;
  const apri = typeof force === "boolean" ? force : notifPanel.hidden;
  if (apri) renderPannelloNotifiche();
  notifPanel.hidden = !apri;
  notifBell.setAttribute("aria-expanded", String(apri));
}

function chiudiPannelloNotifiche() {
  togglePannelloNotifiche(false);
}

notifBell?.addEventListener("click", () => {
  chiudiMenuUtente();
  togglePannelloNotifiche();
});

/* ============================================================
   AVVIO
   ============================================================ */

(async function avvia() {
  const loggato = await caricaSessione();
  if (!loggato) {
    vaiAdAccesso();
    return;
  }
  if (sessionStorage.getItem("melpis_benvenuto")) {
    sessionStorage.removeItem("melpis_benvenuto");
    toast("Benvenuto in Melpis: il tuo periodo di prova Ã¨ attivo.", "success");
  }
  aggiornaRiepilogo();
  aggiornaPrioritari();
  aggiornaReport();
  aggiornaConteggio();
  aggiornaNotifiche();
  aggiornaCampana();
  setInterval(aggiornaNotifiche, 30000);
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    mostraBannerRete("Connessione persa â€” i dati non si aggiornano. Controlla la rete.");
  }
  if (document.getElementById("booking-date")) {
    document.getElementById("booking-date").value = oggiIso();
  }
})();

/* ============================================================
   RICERCA GLOBALE (client-side su ticket, prenotazioni, documenti)
   ============================================================ */

(function inizializzaRicercaGlobale() {
  const wrap = document.getElementById("global-search");
  const input = document.getElementById("global-search-input");
  const results = document.getElementById("global-search-results");
  if (!wrap || !input || !results) return;

  let debounceTimer = null;
  let searchToken = 0;

  function chiudi() {
    results.hidden = true;
    results.innerHTML = "";
  }

  function apriCon(html) {
    results.innerHTML = html;
    results.hidden = false;
  }

  function riga(gruppo, titolo, sub, view, tab) {
    return `<button type="button" class="gs-row" data-view="${view}"${tab ? ` data-tab="${tab}"` : ""}>
      <span class="gs-gruppo">${gruppo}</span>
      <span class="gs-main"><strong>${_sanitize(titolo)}</strong><span>${_sanitize(sub || "")}</span></span>
    </button>`;
  }

  /* Navigazione statica "Vai a": la ricerca non indicizza solo dati, deve
     risolvere anche le destinazioni del menu (es. "audit" â†’ Impostazioni â€º
     Audit). DEBITO TECNICO NOTO: la lista Ã¨ statica â€” se aggiungi un tab o
     una vista, aggiorna questa mappa (nessun modo automatico per rilevarlo). */
  const VAI_A = [
    { q: ["audit", "log", "registro", "storico azioni"], gruppo: "Gestione", titolo: "Audit", sub: "Impostazioni â€º Audit", view: "impostazioni", tab: "audit" },
    { q: ["integrazioni", "whatsapp", "instagram", "webhook", "collega", "canali"], gruppo: "Gestione", titolo: "Integrazioni", sub: "Impostazioni â€º Integrazioni", view: "impostazioni", tab: "integrazioni" },
    { q: ["fuso", "timezone", "password", "email account"], gruppo: "Gestione", titolo: "Impostazioni generali", sub: "Gestione â€º Generale", view: "impostazioni", tab: "generale" },
    { q: ["fattur", "abbonament", "piano", "rinnovo", "pagament", "upgrade", "downgrade", "cancellazion", "prezz"], gruppo: "Account", titolo: "Piano e abbonamento", sub: "Account", view: "account" },
    { q: ["menu", "conoscenza", "allergeni", "carta dei vini", "documenti", "pdf", "knowledge"], gruppo: "Assistente", titolo: "Conoscenza", sub: "Assistente â€º Conoscenza", view: "conoscenza" },
  ];

  async function eseguiRicerca(q) {
    const token = ++searchToken;
    const ql = q.toLowerCase();

    const [tickRes, bookRes, docRes] = await Promise.allSettled([
      apiFetch(`${API_BASE}/api/inbox/tickets?limit=100`),
      apiFetch(`${API_BASE}/api/bookings`),
      apiFetch(`${API_BASE}/api/documenti/elenco`),
    ]);

    if (token !== searchToken) return; // richiesta superata

    const blocchi = [];

    if (tickRes.status === "fulfilled" && tickRes.value.ok) {
      const tickets = (await tickRes.value.json()).tickets || [];
      const hits = tickets.filter((t) =>
        [t.phone_number, t.last_message_preview, t.ticket_status]
          .some((v) => (v || "").toLowerCase().includes(ql))
      ).slice(0, 5);
      if (hits.length) {
        blocchi.push(`<span class="gs-gruppo-titolo">Ticket</span>` + hits.map((t) =>
          riga("Inbox", t.phone_number || "Cliente", t.last_message_preview || t.ticket_status, "inbox")
        ).join(""));
      }
    }

    if (bookRes.status === "fulfilled" && bookRes.value.ok) {
      const prens = await bookRes.value.json();
      const hits = (Array.isArray(prens) ? prens : []).filter((p) =>
        [p.nome_cliente, p.data, p.stato, p.telefono]
          .some((v) => (v || "").toLowerCase().includes(ql))
      ).slice(0, 5);
      if (hits.length) {
        blocchi.push(`<span class="gs-gruppo-titolo">Prenotazioni</span>` + hits.map((p) =>
          riga("Prenotazioni", p.nome_cliente || "Cliente", `${p.data || ""} ${String(p.ora || "").slice(0, 5)} Â· ${p.stato || ""}`, "prenotazioni")
        ).join(""));
      }
    }

    if (docRes.status === "fulfilled" && docRes.value.ok) {
      const docs = (await docRes.value.json()).documenti || [];
      const hits = docs.filter((d) => (d.nome || "").toLowerCase().includes(ql)).slice(0, 5);
      if (hits.length) {
        blocchi.push(`<span class="gs-gruppo-titolo">Documenti</span>` + hits.map((d) =>
          riga("Documenti", d.nome, `${d.chunk} parti`, "documenti")
        ).join(""));
      }
    }

    if (token !== searchToken) return;

    // Navigazione "Vai a": le viste si suggeriscono sempre (in fondo),
    // anche quando i risultati dati sono vuoti.
    const vaiHits = VAI_A.filter((v) => v.q.some((k) => ql.includes(k) || k.includes(ql)) || ql.length >= 3 && v.titolo.toLowerCase().includes(ql));
    if (vaiHits.length) {
      blocchi.push(
        `<span class="gs-gruppo-titolo">Vai a</span>` +
        vaiHits.slice(0, 4).map((v) => riga(v.gruppo, v.titolo, v.sub, v.view, v.tab)).join("")
      );
    }

    if (!blocchi.length) {
      apriCon(`<p class="gs-vuoto">Nessun risultato per "${_sanitize(q)}"</p>`);
      return;
    }
    apriCon(blocchi.join(""));
  }

  input.addEventListener("input", () => {
    const q = input.value.trim();
    clearTimeout(debounceTimer);
    if (q.length < 2) { chiudi(); return; }
    debounceTimer = setTimeout(() => eseguiRicerca(q), 250);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { chiudi(); input.blur(); }
  });

  results.addEventListener("click", (e) => {
    const row = e.target.closest(".gs-row");
    if (!row) return;
    const view = row.dataset.view;
    chiudi();
    input.value = "";
    const btn = document.querySelector(`[data-view="${view}"]`);
    if (btn) btn.click();
    if (row.dataset.tab) attivaTabImpostazioni(row.dataset.tab);
  });

  document.addEventListener("click", (e) => {
    if (!wrap.contains(e.target)) chiudi();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.defaultPrevented) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
    e.preventDefault();
    input.focus();
  });
})();

/* ============================================================
   TEMA CHIARO/SCURO (grigio antracite, mai nero puro)
   ============================================================ */

(function inizializzaTema() {
  const KEY = "melpis_theme";
  const label = document.getElementById("theme-toggle-label");

  function applica(tema) {
    document.documentElement.dataset.theme = tema;
    if (label) label.textContent = tema === "dark" ? "Tema chiaro" : "Tema scuro";
  }

  applica(localStorage.getItem(KEY) || "light");

  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const nuovo = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem(KEY, nuovo);
    applica(nuovo);
  });
})();

/* ============================================================
   IMPOSTAZIONI â€” fuso orario organizzazione
   ============================================================ */

(async function inizializzaTimezone() {
  const select = document.getElementById("settings-timezone");
  const saveBtn = document.getElementById("settings-timezone-save");
  const status = document.getElementById("settings-timezone-status");
  if (!select || !saveBtn) return;
  let caricato = false;

  async function carica() {
    try {
      const res = await apiFetch(`${API_BASE}/api/impostazioni/organizzazione`);
      if (!res.ok) return;
      const data = await res.json();
      if (caricato) return;
      caricato = true;
      select.innerHTML = "";
      (data.timezone_disponibili || []).forEach((tz) => {
        const opt = document.createElement("option");
        opt.value = tz;
        opt.textContent = tz;
        if (tz === data.timezone) opt.selected = true;
        select.appendChild(opt);
      });
      if (![...select.options].some((o) => o.value === data.timezone)) {
        const opt = document.createElement("option");
        opt.value = data.timezone;
        opt.textContent = data.timezone;
        opt.selected = true;
        select.appendChild(opt);
      }
    } catch { /* silenzioso: la vista riproverÃ  al prossimo switch */ }
  }

  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    if (status) { status.textContent = "Salvoâ€¦"; status.style.color = ""; }
    try {
      const res = await apiFetch(`${API_BASE}/api/impostazioni/organizzazione`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timezone: select.value }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (status) { status.textContent = data.detail || "Salvataggio non riuscito"; status.style.color = "var(--red)"; }
        return;
      }
      if (status) securityStatus(status, "Fuso orario aggiornato");
    } catch {
      if (status) { status.textContent = "Errore di connessione"; status.style.color = "var(--red)"; }
    } finally {
      saveBtn.disabled = false;
    }
  });

  await carica();
})();

/* ============================================================
   AUDIT â€” registro attivitÃ 
   ============================================================ */

const AUDIT_ACTION_LABEL = {
  "profilo.aggiornato": "Profilo aggiornato",
  "org.timezone_updated": "Fuso orario aggiornato",
  "prenotazione.confermata": "Prenotazione confermata",
  "prenotazione.rifiutata": "Prenotazione rifiutata",
  "prenotazione.annullata": "Prenotazione annullata",
  "documento_eliminato": "Documento eliminato",
};

let auditOffset = 0;
let auditHasMore = false;

async function caricaAudit({ append = false } = {}) {
  const list = document.getElementById("audit-list");
  const count = document.getElementById("audit-count");
  if (!list) return;
  if (!append) {
    auditOffset = 0;
    auditHasMore = false;
    list.innerHTML = '<div class="skeleton skeleton-line-lg"></div><div class="skeleton skeleton-line-lg"></div><div class="skeleton skeleton-line-lg"></div>';
  }
  try {
    const res = await apiFetch(`${API_BASE}/api/audit?limit=20&offset=${auditOffset}`);
    if (!res.ok) {
      list.innerHTML = '<p class="inbox-empty">Registro non disponibile.</p>';
      return;
    }
    const data = await res.json();
    const eventi = data.eventi || [];
    auditHasMore = Boolean(data.has_more);
    if (!append) {
      list.innerHTML = "";
      document.getElementById("inbox-load-more")?.remove();
    } else {
      document.getElementById("audit-load-more")?.remove();
    }
    if (!eventi.length && !append) {
      list.innerHTML = '<p class="inbox-empty">Nessuna azione registrata: le modifiche a impostazioni, prenotazioni e documenti compariranno qui.</p>';
      if (count) count.textContent = "";
      return;
    }
    eventi.forEach((ev) => {
      const item = document.createElement("div");
      item.className = "audit-item";
      const quando = new Date(ev.created_at).toLocaleString("it-IT", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
      });
      const dettagli = ev.details && Object.keys(ev.details).length
        ? Object.entries(ev.details).map(([k, v]) => `${k}: ${v}`).join(" Â· ")
        : "";
      item.innerHTML = `
        <div class="audit-main">
          <strong>${_sanitize(AUDIT_ACTION_LABEL[ev.action] || ev.action)}</strong>
          ${dettagli ? `<span class="audit-details">${_sanitize(dettagli)}</span>` : ""}
        </div>
        <div class="audit-meta">
          <span>${_sanitize(ev.user_email || "sistema")}</span>
          <time>${_sanitize(quando)}</time>
        </div>`;
      list.appendChild(item);
    });
    auditOffset += eventi.length;
    if (count) count.textContent = `${auditOffset} eventi`;
    if (auditHasMore) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.id = "audit-load-more";
      btn.className = "inbox-load-more";
      btn.textContent = "Carica altri eventi";
      btn.addEventListener("click", () => {
        btn.disabled = true;
        btn.textContent = "Caricoâ€¦";
        caricaAudit({ append: true });
      });
      list.appendChild(btn);
    }
  } catch {
    list.innerHTML = '<p class="inbox-empty">Registro non disponibile.</p>';
  }
}

/* ============================================================
   INTEGRAZIONI â€” stato canali e webhook
   ============================================================ */

async function caricaIntegrazioni() {
  const status = document.getElementById("integrazioni-status");
  try {
    const res = await apiFetch(`${API_BASE}/api/integrazioni/stato`);
    if (!res.ok) {
      if (status) { status.textContent = "Stato non disponibile."; status.style.color = "var(--red)"; }
      return;
    }
    const d = await res.json();

    const waStato = document.getElementById("integ-whatsapp-stato");
    const waSub = document.getElementById("integ-whatsapp-sub");
    if (waStato && waSub) {
      waStato.textContent = d.whatsapp.connesso ? "Connesso" : "Non connesso";
      waStato.classList.add(d.whatsapp.connesso ? "on" : "off");
      waSub.textContent = d.whatsapp.connesso
        ? `Numero ID ${d.whatsapp.phone_number_id || "configurato"}`
        : "Nessun numero collegato";
    }

    const igStato = document.getElementById("integ-instagram-stato");
    const igSub = document.getElementById("integ-instagram-sub");
    if (igStato && igSub) {
      igStato.textContent = d.instagram.connesso ? "Connesso" : "Non connesso";
      igStato.classList.add(d.instagram.connesso ? "on" : "off");
      igSub.textContent = d.instagram.connesso
        ? `Account ${d.instagram.ig_user_id || "collegato"}`
        : "Nessun account collegato";
    }

    const whStato = document.getElementById("integ-webhook-stato");
    const whSub = document.getElementById("integ-webhook-sub");
    if (whStato && whSub) {
      whStato.textContent = d.webhook_meta.configurato ? "Attivo" : "Da configurare";
      whStato.classList.add(d.webhook_meta.configurato ? "on" : "off");
      whSub.textContent = d.webhook_meta.configurato
        ? "Credenziali Meta presenti sul server"
        : "Serve META_APP_SECRET e META_VERIFY_TOKEN";
    }
  } catch {
    if (status) { status.textContent = "Errore di connessione."; status.style.color = "var(--red)"; }
  }
}

document.getElementById("integrazioni-config")?.addEventListener("click", () => {
  apriOnboarding();
});

/* ============================================================
   STAMPA REPORT + SCORCIATOIE TASTIERA
   ============================================================ */

document.getElementById("report-print")?.addEventListener("click", () => window.print());

(function inizializzaScorciatoie() {
  const ordineViste = [
    "panoramica", "onboarding", "assistente", "recensioni",
    "prenotazioni", "report", "documenti", "inbox",
    "impostazioni", "integrazioni", "audit",
  ];

  function pannelloScorciatoie() {
    let overlay = document.getElementById("shortcuts-overlay");
    if (overlay) { overlay.remove(); return; }
    overlay = document.createElement("div");
    overlay.id = "shortcuts-overlay";
    overlay.innerHTML = `
      <div class="shortcuts-panel" role="dialog" aria-modal="true" aria-label="Scorciatoie da tastiera">
        <h3>Scorciatoie da tastiera</h3>
        <dl>
          <dt>/</dt><dd>ricerca globale</dd>
          <dt>1 â€“ 9</dt><dd>vai alle viste in ordine di menu</dd>
          <dt>0</dt><dd>vista Audit</dd>
          <dt>?</dt><dd>questo pannello</dd>
          <dt>Esc</dt><dd>chiudi pannelli e ricerca</dd>
        </dl>
        <p>Premi Esc o clicca fuori per chiudere.</p>
      </div>`;
    overlay.addEventListener("click", (e) => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
  }

  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;

    if (e.key === "?") { e.preventDefault(); pannelloScorciatoie(); return; }
    if (e.key === "Escape") { document.getElementById("shortcuts-overlay")?.remove(); return; }

    const n = Number(e.key);
    if (!Number.isNaN(n) && e.key !== " ") {
      const view = n === 0 ? "audit" : ordineViste[n - 1];
      if (view) {
        const btn = document.querySelector(`[data-view="${view}"]`);
        if (btn) { e.preventDefault(); btn.click(); }
      }
    }
  });
})();
