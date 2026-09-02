const API_BASE =
  typeof window !== "undefined" && typeof window.MELPIS_API_BASE === "string"
    ? window.MELPIS_API_BASE
    : "";

if (typeof window !== "undefined" && window.MELPIS_API_BASE === undefined) {
  console.warn("[App] window.MELPIS_API_BASE non definita, fallback sicuro su same-origin ('')");
}
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

function _escapeHtml(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function _sanitize(v) {
  if (typeof DOMPurify !== "undefined" && typeof DOMPurify.sanitize === "function") {
    return DOMPurify.sanitize(v == null ? "" : String(v));
  }
  return _escapeHtml(v);
}

/* ============================================================
   TOAST — notifiche non bloccanti al posto di alert()
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
   CONFERMA AZIONI DISTRUTTIVE — modal riusabile al posto di confirm()
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
   STATO RETE — banner "connessione persa / ripristinata"
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
    mostraBannerRete("Connessione persa — i dati non si aggiornano. Controlla la rete.");
  } else {
    mostraBannerRete("Server irraggiungibile — riprova tra poco.");
  }
}

function segnaReteOk() {
  if (!reteInErrore) return;
  reteInErrore = false;
  mostraBannerRete("Connessione ripristinata.", true, 3000);
}

window.addEventListener("offline", () => {
  mostraBannerRete("Connessione persa — i dati non si aggiornano. Controlla la rete.");
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
  if (btn) btn.hidden = Boolean(sessione);

  if (!sessione) {
    chiudiSidebarAccountMenu();
    return;
  }
  const email = sessione.email || "utente";
  const iniziale = (email[0] || "U").toUpperCase();

  // Sidebar account trigger
  const sbAvatar = document.getElementById("sidebar-avatar-initial");
  const sbEmail = document.getElementById("sidebar-account-email");
  if (sbAvatar) sbAvatar.textContent = iniziale;
  if (sbEmail) sbEmail.textContent = email;
}

function toggleSidebarAccountMenu(force) {
  const dropdown = document.getElementById("sidebar-account-dropdown");
  const btn = document.getElementById("sidebar-account-trigger");
  if (!dropdown || !btn) return;
  const apri = typeof force === "boolean" ? force : dropdown.hidden;
  dropdown.hidden = !apri;
  btn.setAttribute("aria-expanded", String(apri));
}

function chiudiSidebarAccountMenu() {
  toggleSidebarAccountMenu(false);
}

document.getElementById("sidebar-account-trigger")?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleSidebarAccountMenu();
});

document.getElementById("sidebar-menu-impostazioni")?.addEventListener("click", () => {
  chiudiSidebarAccountMenu();
  apriVistaImpostazioni("generale");
});

document.getElementById("sidebar-menu-piano")?.addEventListener("click", () => {
  chiudiSidebarAccountMenu();
  apriVistaImpostazioni("piano");
});

document.getElementById("sidebar-logout-btn")?.addEventListener("click", async () => {
  await faiLogout();
  window.location.href = "/accedi/";
});

document.addEventListener("click", (e) => {
  if (!e.target.closest("#sidebar-account-trigger") && !e.target.closest("#sidebar-account-dropdown")) {
    chiudiSidebarAccountMenu();
  }
});

/* Login su pagina dedicata /accedi/, registrazione su /registrati/
   (pagine standalone). Il modal è stato rimosso. */
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
    const data = await res.json();
    if (!data || data.source === "anonymous" || !data.user_id || !data.organization_id) {
      sessione = null;
      aggiornaBottoneAccesso();
      return false;
    }
    sessione = data;
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
   ACCOUNT — Piano e abbonamento (vista dedicata, ex CTA topbar)
   ============================================================ */

const ACCOUNT_PLANS = [
  {
    slug: "starter",
    nome: "Essenziale",
    prezzo: "€29",
    cadenza: "/mese",
    limite: "300 conversazioni / mese",
    features: [
      "1 numero WhatsApp Business",
      "Knowledge Base fino a 20 parti",
      "Gestione orari e listino servizi",
      "Supporto standard"
    ],
    popolare: false,
  },
  {
    slug: "pro",
    nome: "Crescita",
    prezzo: "€69",
    cadenza: "/mese",
    limite: "1.200 conversazioni / mese",
    features: [
      "WhatsApp + Instagram Direct",
      "Knowledge Base illimitata (RAG Priorità 1)",
      "Sincronizzazione Google Calendar",
      "Escalation a operatore umano",
      "Supporto prioritario"
    ],
    popolare: true,
  },
  {
    slug: "business",
    nome: "Scala",
    prezzo: "€149",
    cadenza: "/mese",
    limite: "5.000 conversazioni / mese",
    features: [
      "Tutti i canali inclusi senza limiti",
      "Multi-operatore dedicato",
      "Onboarding personalizzato e SLA 99.9%",
      "Webhook e integrazioni API custom"
    ],
    popolare: false,
  },
];

function accountStatoPill(stato) {
  const pill = document.getElementById("account-stato");
  if (!pill) return;
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
    const planName = corrente ? corrente.nome : "Nessun piano";
    const planPrice = corrente ? `${corrente.prezzo}${corrente.cadenza || "/mese"}` : "";

    const nameEl = document.getElementById("account-plan-nome");
    const priceEl = document.getElementById("account-plan-prezzo");
    const sbPlanEl = document.getElementById("sidebar-account-plan");

    if (nameEl) nameEl.textContent = planName;
    if (priceEl) priceEl.textContent = planPrice;
    if (sbPlanEl) sbPlanEl.textContent = corrente ? "Piano " + corrente.nome : "Piano e abbonamento";

    const rinnovo = document.getElementById("account-rinnovo");
    const dataIt = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleDateString("it-IT"); };
    if (rinnovo) {
      if (sub.trial_end) rinnovo.textContent = `Prova gratuita attiva fino al ${dataIt(sub.trial_end)}.`;
      else if (stato === "canceled") rinnovo.textContent = "Abbonamento disattivato: il servizio resta attivo fino al termine del periodo pagato.";
      else if (sub.current_period_end) rinnovo.textContent = `Prossimo rinnovo programmato: ${dataIt(sub.current_period_end)}.`;
      else rinnovo.textContent = "Nessun rinnovo programmato.";
    }

    // Card cambio piano: quella attiva è evidenziata e non cliccabile.
    const wrap = document.getElementById("account-plans");
    if (wrap) {
      wrap.innerHTML = "";
      ACCOUNT_PLANS.forEach((p) => {
        const attuale = p.slug === sub.plan;
        const card = document.createElement("div");
        card.className = "account-plan-card" + (attuale ? " account-plan-attuale" : "") + (p.popolare ? " popolare" : "");

        const popBadge = p.popolare ? '<span class="account-badge-popolare">Consigliato</span>' : "";
        const statusBadge = attuale ? '<span class="account-stato-pill">Piano Attivo</span>' : "";

        const featHtml = p.features.map(f => `
          <li class="account-plan-feat-item">
            <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" class="account-feat-check"><polyline points="20 6 9 17 4 12"/></svg>
            <span>${_sanitize(f)}</span>
          </li>
        `).join("");

        card.innerHTML = `
          ${popBadge}
          <div class="dash-card-header" style="margin-bottom: 0;">
            <span class="dash-card-title">${_sanitize(p.nome)}</span>
            ${statusBadge}
          </div>
          <div class="account-plan-price-row">
            <span class="account-plan-price-amount">${_sanitize(p.prezzo)}</span>
            <span class="account-plan-price-period">${_sanitize(p.cadenza || "/mese")}</span>
          </div>
          <p class="account-plan-limit">${_sanitize(p.limite)}</p>
          <ul class="account-plan-feat-list">${featHtml}</ul>
        `;

        const actions = document.createElement("div");
        actions.className = "settings-actions";
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = attuale ? "report-refresh" : (p.popolare ? "review-analyze" : "report-refresh");
        btn.textContent = attuale ? "Piano in uso" : (stato === "canceled" ? "Riattiva " + p.nome : "Passa a " + p.nome);
        if (!attuale) {
          btn.addEventListener("click", () => cambiaPiano(p.slug));
        } else {
          btn.disabled = true;
        }
        actions.appendChild(btn);
        card.appendChild(actions);
        wrap.appendChild(card);
      });
    }
    if (status) status.hidden = true;
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
    status.textContent = "Impossibile avviare il cambio piano. Riprova più tardi.";
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
    status.textContent = "Impossibile aprire il portale Stripe. Riprova più tardi.";
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
let prenotazioniInAttesaCount = 0;

/* Chiavi delle notifiche nate prima della riorganizzazione della sidebar:
   la migrazione preserva lo stato "già letto" (timestamp) di chi le aveva
   viste, altrimenti le notifiche ricomparirebbero come nuove. */
const NOTIF_KEY_MIGRATION = {
  documenti: "conoscenza",
  report: null, // badge rimosso: la voce non esiste più
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
    if (key === "prenotazioni") {
      // Badge persistente per prenotazioni in_attesa: visibile da qualsiasi vista finché non confermate/rifiutate
      const inAttesa = Number(prenotazioniInAttesaCount || 0);
      badge.textContent = inAttesa > 99 ? "99+" : String(inAttesa);
      badge.hidden = inAttesa === 0;
      badge.title = inAttesa > 0 ? `Da confermare: ${inAttesa}` : "";
      return;
    }
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

/* Destinazioni di fallback per chiavi di viste non più presenti nella nav
   (notifiche salvate prima della riorganizzazione, link memorizzati):
   apre la vista contenitore e, se prevista, il tab giusto dentro
   Impostazioni — mai un no-op silenzioso. */
const VIEW_FALLBACK = {
  audit: { view: "impostazioni", tab: "audit" },
  integrazioni: { view: "impostazioni", tab: "whatsapp" },
  account: { view: "impostazioni", tab: "piano" },
  piano: { view: "impostazioni", tab: "piano" },
  fatturazione: { view: "impostazioni", tab: "fatturazione" },
  sicurezza: { view: "impostazioni", tab: "sicurezza" },
  profilo: { view: "impostazioni", tab: "profilo" },
  documenti: { view: "conoscenza" },
  report: { view: "panoramica" },
  onboarding: { view: "assistente" },
};

function apriVistaImpostazioni(cat = "generale") {
  segnaNotificheViste("impostazioni");
  chiudiMenuMobile();
  chiudiSidebarAccountMenu();

  navItems.forEach((n) => n.classList.remove("active"));
  views.forEach((v) => {
    v.classList.toggle("view-hidden", v.dataset.viewPanel !== "impostazioni");
  });

  const titles = {
    piano: "Piano e abbonamento",
    fatturazione: "Piano e abbonamento",
  };
  topbarTitle.textContent = titles[cat] || "Impostazioni";

  attivaCategoriaImpostazioni(cat);
}

function apriView(key) {
  if (key === "impostazioni") {
    apriVistaImpostazioni("generale");
    return true;
  }
  const btn = document.querySelector(`.nav-item[data-view="${key}"]`);
  if (btn) {
    btn.click();
    return true;
  }
  const dest = VIEW_FALLBACK[key];
  if (!dest) return false;
  if (dest.view === "impostazioni") {
    apriVistaImpostazioni(dest.tab || "generale");
    return true;
  }
  const container = document.querySelector(`.nav-item[data-view="${dest.view}"]`);
  if (container) container.click();
  if (dest.tab) attivaCategoriaImpostazioni(dest.tab);
  return true;
}

/* --- Sotto-sidebar Impostazioni & Account (Pattern a due riquadri) --- */

function attivaCategoriaImpostazioni(cat) {
  const MAPPATURA_LEGACY = {
    generale: "generale",
    integrazioni: "whatsapp",
    audit: "audit",
    account: "piano",
    piano: "piano",
    fatturazione: "fatturazione",
    profilo: "profilo",
    "assistente-regole": "assistente-regole",
    assistente: "assistente-regole",
    sicurezza: "sicurezza",
    whatsapp: "whatsapp",
    instagram: "instagram",
    calendar: "calendar",
    webhook: "webhook",
  };
  const targetCat = MAPPATURA_LEGACY[cat] || cat || "generale";

  document.querySelectorAll("[data-settings-cat-btn]").forEach((b) => {
    const on = b.dataset.settingsCatBtn === targetCat;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", String(on));
  });

  document.querySelectorAll("[data-settings-panel]").forEach((p) => {
    const on = p.dataset.settingsPanel === targetCat;
    p.hidden = !on;
  });

  // Carica i dati specifici della categoria attiva
  if (targetCat === "generale") {
    if (typeof caricaTimezone === "function") caricaTimezone();
  } else if (["whatsapp", "instagram", "calendar", "webhook"].includes(targetCat)) {
    if (typeof caricaIntegrazioni === "function") caricaIntegrazioni();
  } else if (targetCat === "piano" || targetCat === "fatturazione") {
    if (typeof caricaAccount === "function") caricaAccount();
  } else if (targetCat === "audit") {
    if (typeof caricaAudit === "function") caricaAudit();
  }
}

function attivaTabImpostazioni(tab) {
  attivaCategoriaImpostazioni(tab);
}

document.querySelectorAll("[data-settings-cat-btn]").forEach((btn) => {
  btn.addEventListener("click", () => attivaCategoriaImpostazioni(btn.dataset.settingsCatBtn));
});

// Ricerca live nelle impostazioni
const settingsSearchInput = document.getElementById("settings-search-input");
if (settingsSearchInput) {
  settingsSearchInput.addEventListener("input", () => {
    const q = settingsSearchInput.value.trim().toLowerCase();
    const catBtns = document.querySelectorAll("[data-settings-cat-btn]");
    const groups = document.querySelectorAll(".settings-nav-group");
    const emptyMsg = document.getElementById("settings-search-empty");
    let matchCount = 0;

    catBtns.forEach((btn) => {
      const text = (btn.textContent + " " + (btn.dataset.keywords || "")).toLowerCase();
      const match = !q || text.includes(q);
      btn.style.display = match ? "" : "none";
      if (match) matchCount++;
    });

    groups.forEach((grp) => {
      const visibleBtns = grp.querySelectorAll('[data-settings-cat-btn]:not([style*="display: none"])');
      grp.style.display = visibleBtns.length ? "" : "none";
    });

    if (emptyMsg) {
      emptyMsg.hidden = matchCount > 0;
    }
  });
}

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
    try {
      const bRes = await apiFetch(`${API_BASE}/api/bookings`);
      if (bRes.ok) {
        const list = await bRes.json();
        prenotazioniInAttesaCount = list.filter((p) => statoNormalizzatoPrenotazione(p) === "in_attesa").length;
        if (bookingPendingValue) bookingPendingValue.textContent = String(prenotazioniInAttesaCount);
      }
    } catch { /* ignora errore fetch secondario */ }
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
    chiudiMenuMobile();

    navItems.forEach((n) => n.classList.remove("active"));
    btn.classList.add("active");

    if (viewName === "account") {
      views.forEach((v) => {
        v.classList.toggle("view-hidden", v.dataset.viewPanel !== "impostazioni");
      });
      topbarTitle.textContent = "Piano e abbonamento";
      attivaCategoriaImpostazioni("piano");
      caricaAccount();
      return;
    }

    views.forEach((v) => {
      v.classList.toggle("view-hidden", v.dataset.viewPanel !== viewName);
    });

    const titles = {
      panoramica: "Panoramica",
      inbox: "Inbox",
      prenotazioni: "Prenotazioni",
      recensioni: "Recensioni",
      assistente: "Simulatore AI",
      conoscenza: "Conoscenza",
      impostazioni: "Impostazioni",
      account: "Piano e abbonamento",
      onboarding: "Configurazione assistente",
    };
    topbarTitle.textContent = titles[viewName] || viewName;
    if (viewName === "impostazioni") {
      attivaCategoriaImpostazioni("generale");
    }
    if (viewName === "account") caricaAccount();

    if (viewName === "panoramica") {
      avviaPanoramicaPolling();
      aggiornaRiepilogo();
      aggiornaPrioritari();
    } else {
      fermaPanoramicaPolling();
    }
    if (viewName === "assistente") {
      // Il wizard salva solo owner/manager (gate lato API): per lo staff
      // la card "Configura" non ha senso, la rimuoviamo dal DOM.
      if (sessione?.ruolo === "staff") document.getElementById("onboarding-banner")?.remove();
    }
    if (viewName === "recensioni") {
      aggiornaRecensioni();
    }
    if (viewName === "prenotazioni") {
      await aggiornaImpostazioniPrenotazioni();
      inizializzaCalendarioPrenotazioni();
      await aggiornaPrenotazioni();
      await aggiornaSemaforo();
      if (bookingCalendar) {
        bookingCalendar.updateSize();
        bookingCalendar.render();
      }
      renderTabellaPrenotazioniGiorno();
    }
    if (viewName === "documenti" || viewName === "conoscenza") {
      aggiornaConoscenzaCompleta();
    }
    if (viewName === "configurazione-ai") {
      if (typeof caricaConfigurazioneAI === "function") caricaConfigurazioneAI();
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

const ONBOARDING_DRAFT_KEY = "melpis_onboarding_bozza";
let dbProfileRecord = null;

function profiloOnboarding() {
  const vertical = verticaleCorrente();
  return {
    verticale: onboardingState.selectedVertical,
    nome_attivita: onboardingEls.name.value.trim() || "Nuova attività",
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

function salvaBozzaOnboarding() {
  /* Bozza in localStorage: il wizard resta riprendibile anche se il
     browser si chiude a metà. I dati sono non-sensibili (profilo attività). */
  try {
    const bozza = {
      step: onboardingState.step,
      salvata_at: new Date().toISOString(),
      profilo: profiloOnboarding(),
      extraRules: onboardingState.extraRules || [],
    };
    localStorage.setItem(ONBOARDING_DRAFT_KEY, JSON.stringify(bozza));
    const badge = document.getElementById("onboarding-autosave");
    if (badge) {
      const ora = new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
      badge.textContent = `Bozza salvata · ${ora}`;
      badge.hidden = false;
    }
  } catch { /* localStorage pieno/bloccato: non blocca il wizard */ }
}

function leggiBozzaOnboarding() {
  try {
    const raw = localStorage.getItem(ONBOARDING_DRAFT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function pulisciBozzaOnboarding() {
  try {
    localStorage.removeItem(ONBOARDING_DRAFT_KEY);
  } catch { /* storage non disponibile */ }
  const banner = document.getElementById("onboarding-draft-banner");
  if (banner) banner.hidden = true;
  const badge = document.getElementById("onboarding-autosave");
  if (badge) badge.hidden = true;
}

function applicaProfiloAForm(record, extraRules = null) {
  if (!record) return;
  if (record.verticale) onboardingState.selectedVertical = record.verticale;
  if (onboardingEls.name) onboardingEls.name.value = record.nome_attivita || "";
  if (onboardingEls.hours) onboardingEls.hours.value = record.orari || "";
  if (onboardingEls.tone) onboardingEls.tone.value = record.tono || "";
  if (onboardingEls.services) {
    onboardingEls.services.value = Array.isArray(record.servizi)
      ? record.servizi.join("\n")
      : (record.servizi || "");
  }
  if (onboardingEls.whatsapp) onboardingEls.whatsapp.checked = Boolean(record.whatsapp_collegato);
  if (onboardingEls.docs) onboardingEls.docs.checked = Boolean(record.documenti_importati);
  onboardingState.profileLoaded = true;
  if (record.lingue_supportate?.length) onboardingState.lingue = record.lingue_supportate;
  if (record.lingua_default) onboardingState.linguaDefault = record.lingua_default;
  if (extraRules && Array.isArray(extraRules)) {
    onboardingState.extraRules = extraRules;
  }
  if (record.nome_attivita) {
    const bn = document.getElementById("business-name");
    const cbn = document.getElementById("chat-business-name");
    if (bn) bn.textContent = record.nome_attivita;
    if (cbn) cbn.textContent = record.nome_attivita;
  }
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
      salvaBozzaOnboarding();
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
    const input = label.querySelector("input");
    input?.addEventListener("change", () => salvaBozzaOnboarding());
    onboardingEls.escalationList.appendChild(label);
  });
}

async function caricaProfiloOnboarding() {
  try {
    const res = await apiFetch(`${API_BASE}/api/onboarding/profilo`);
    if (res.status === 401) {
      onboardingEls.status.textContent = 'Serve la config di accesso: clicca "Configura accesso" in alto.';
      onboardingEls.status.style.color = "var(--red)";
      return null;
    }
    if (!res.ok) return null;
    const data = await res.json();
    dbProfileRecord = data.profilo || null;
    return dbProfileRecord;
  } catch {
    return null;
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
    const savedProfile = await caricaProfiloOnboarding();
    const bozzaLocale = leggiBozzaOnboarding();

    let usaBozza = false;
    if (bozzaLocale && bozzaLocale.profilo) {
      if (!savedProfile || !savedProfile.updated_at) {
        usaBozza = true;
      } else {
        const draftDate = new Date(bozzaLocale.salvata_at || 0);
        const dbDate = new Date(savedProfile.updated_at || savedProfile.created_at || 0);
        usaBozza = draftDate >= dbDate;
      }
    }

    const banner = document.getElementById("onboarding-draft-banner");
    const timeHint = document.getElementById("onboarding-draft-time-hint");

    if (usaBozza && bozzaLocale.profilo) {
      applicaProfiloAForm(bozzaLocale.profilo, bozzaLocale.extraRules);
      if (typeof bozzaLocale.step === "number" && bozzaLocale.step >= 0 && bozzaLocale.step <= 6) {
        onboardingState.step = bozzaLocale.step;
      }
      if (banner) {
        banner.hidden = false;
        if (timeHint && bozzaLocale.salvata_at) {
          try {
            const d = new Date(bozzaLocale.salvata_at);
            timeHint.textContent = `Bozza salvata il ${d.toLocaleDateString("it-IT")} alle ${d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })}.`;
          } catch {
            timeHint.textContent = "Bozza recuperata in locale.";
          }
        }
      }
    } else if (savedProfile) {
      applicaProfiloAForm(savedProfile);
      if (banner) banner.hidden = true;
    }

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
  dbProfileRecord = record;
  pulisciBozzaOnboarding();
  document.getElementById("business-name").textContent = record.nome_attivita;
  document.getElementById("chat-business-name").textContent = record.nome_attivita;
  return record;
}

/* ============================================================
   ONBOARDING — accesso dal banner in "Assistente" (voce nav rimossa)
   ============================================================ */

function apriOnboarding() {
  chiudiMenuMobile();
  navItems.forEach((n) => n.classList.remove("active"));
  views.forEach((v) => {
    v.classList.toggle("view-hidden", v.dataset.viewPanel !== "onboarding");
  });
  topbarTitle.textContent = "Configurazione assistente";
  inizializzaOnboarding();
}

function chiudiOnboarding() {
  document.querySelector('.nav-item[data-view="assistente"]')?.click();
}

document.getElementById("onboarding-banner-cta")?.addEventListener("click", apriOnboarding);
document.getElementById("onboarding-chiudi")?.addEventListener("click", chiudiOnboarding);
document.getElementById("onboarding-draft-discard")?.addEventListener("click", () => {
  pulisciBozzaOnboarding();
  onboardingState.step = 0;
  onboardingState.extraRules = [];
  if (dbProfileRecord) {
    applicaProfiloAForm(dbProfileRecord);
  } else {
    const first = onboardingState.verticals[0];
    if (first) {
      onboardingState.selectedVertical = first.id;
      onboardingEls.tone.value = first.tono;
      onboardingEls.services.value = first.servizi.join("\n");
      onboardingEls.testMessage.value = first.esempio;
      onboardingEls.name.value = "";
      onboardingEls.hours.value = "";
      onboardingState.lingue = LINGUE_DEFAULT_PER_VERTICALE[first.id] || ["it"];
    }
  }
  renderVerticals();
  renderEscalationRules();
  renderLingue();
  renderOnboardingStep();
  toast("Bozza locale scartata. Ripartito dal profilo iniziale.", "info");
});

[onboardingEls.name, onboardingEls.hours, onboardingEls.tone, onboardingEls.services].forEach((el) => {
  el?.addEventListener("input", () => salvaBozzaOnboarding());
});
[onboardingEls.whatsapp, onboardingEls.docs].forEach((el) => {
  el?.addEventListener("change", () => salvaBozzaOnboarding());
});


/* â”€â”€ Sicurezza account: cambio password/email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ */

const SECURITY_PASSWORD_MIN = 10;

function securityStatus(el, testo, errore = false) {
  if (!el) return;
  el.textContent = testo;
  el.style.color = errore ? "var(--red)" : "var(--green-deep)";
}

document.getElementById("security-password-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const currentPwd = document.getElementById("security-password-current")?.value || "";
  const pwd = document.getElementById("security-password")?.value || "";
  const conferma = document.getElementById("security-password-confirm")?.value || "";
  const status = document.getElementById("security-password-status");
  const submit = e.target.querySelector(".security-submit");
  if (!currentPwd) {
    securityStatus(status, "Inserisci la password attuale", true);
    return;
  }
  if (pwd.length < SECURITY_PASSWORD_MIN || !/[^A-Za-z0-9]/.test(pwd)) {
    securityStatus(status, `Min ${SECURITY_PASSWORD_MIN} caratteri e almeno un simbolo (es. ! @ #)`, true);
    return;
  }
  if (pwd !== conferma) {
    securityStatus(status, "Le due password non coincidono", true);
    return;
  }
  submit.disabled = true;
  securityStatus(status, "Aggiorno…");
  try {
    const res = await apiFetch(`${API_BASE}/api/auth/password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: pwd, current_password: currentPwd }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      securityStatus(status, data.detail || "Aggiornamento non riuscito", true);
      return;
    }
    securityStatus(status, data.message || "Password aggiornata");
    const currentInput = document.getElementById("security-password-current");
    if (currentInput) currentInput.value = "";
    document.getElementById("security-password").value = "";
    document.getElementById("security-password-confirm").value = "";
  } catch {
    securityStatus(status, "Errore di connessione", true);
  } finally {
    submit.disabled = false;
  }
});

document.getElementById("security-send-reset-btn")?.addEventListener("click", async () => {
  const resetBtn = document.getElementById("security-send-reset-btn");
  const resetStatus = document.getElementById("security-reset-email-status");
  if (!resetStatus || !resetBtn) return;
  resetBtn.disabled = true;
  securityStatus(resetStatus, "Invio link sicuro in corso…");
  try {
    const res = await apiFetch(`${API_BASE}/api/auth/send-password-reset`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      securityStatus(resetStatus, data.detail || "Impossibile inviare il link di reset", true);
      return;
    }
    securityStatus(resetStatus, data.message || "Link inviato con successo.");
  } catch {
    securityStatus(resetStatus, "Errore di connessione", true);
  } finally {
    resetBtn.disabled = false;
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
  securityStatus(status, "Aggiorno…");
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
  salvaBozzaOnboarding();
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
const availabilityList = document.getElementById("availability-list");
const availabilityDate = document.getElementById("availability-date");
const bookingForm = document.getElementById("booking-form");
const bookingStatusText = document.getElementById("booking-status-text");
const bookingSettingsGrid = document.getElementById("booking-settings-grid");
const capacitySave = document.getElementById("capacity-save");
const capacityStatus = document.getElementById("capacity-status");
let bookingCalendar = null;
let bookingOpenHours = {};
let bookingAvailability = new Map();
let bookingRecords = [];
let bookingPendingOnly = false;
let bookingEditingId = null;
let bookingPollTimer = null;
let bookingSnapshot = new Map();
const bookingModal = document.getElementById("booking-modal");
const bookingSummary = document.getElementById("booking-summary");
const bookingPendingValue = document.getElementById("booking-pending-value");
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
  return _toDateKey(new Date());
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
  const noShowBtn = document.getElementById("booking-no-show-btn");
  const completedBtn = document.getElementById("booking-completed-btn");
  const editBtn = document.getElementById("booking-edit-btn");
  if (!confermaBtn || !rifiutaBtn || !annullaBtn || !noShowBtn || !completedBtn || !editBtn) return;
  const stato = statoNormalizzatoPrenotazione(p);
  const finale = STATI_FINALI_PRENOTAZIONE.includes(stato);
  confermaBtn.hidden = staff || finale || stato === "confermata";
  rifiutaBtn.hidden = staff || finale || stato === "rifiutata";
  annullaBtn.hidden = staff || finale;
  noShowBtn.hidden = staff || finale || stato !== "confermata";
  completedBtn.hidden = staff || finale || stato !== "confermata";
  editBtn.hidden = staff || finale;
  wrap.hidden = [confermaBtn, rifiutaBtn, annullaBtn, noShowBtn, completedBtn, editBtn].every((button) => button.hidden);
}

async function eseguiAzionePrenotazione(azione, { chiediConferma = false, titolo = "", descrizione = "", label = "Conferma" } = {}) {
  const p = prenotazioneCorrente;
  if (!p?.id) return;
  if (chiediConferma) {
    const ok = await confermaDestructiva({ titolo, descrizione, label });
    if (!ok) return;
  }
  const bottoni = ["booking-confirm-btn", "booking-reject-btn", "booking-cancel-btn", "booking-no-show-btn", "booking-completed-btn", "booking-edit-btn"]
    .map((id) => document.getElementById(id))
    .filter(Boolean);
  bottoni.forEach((b) => { b.disabled = true; });
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings/${encodeURIComponent(p.id)}/${azione}`, { method: "POST" });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Operazione non riuscita.");
    }
    prenotazioneCorrente = await res.json();
    chiudiDettaglioPrenotazione();
    toast(
      azione === "confirm" ? "Prenotazione confermata."
        : azione === "reject" ? "Prenotazione rifiutata."
          : azione === "mark-no-show" ? "Prenotazione segnata come no-show."
            : azione === "mark-completed" ? "Prenotazione completata."
              : "Prenotazione annullata.",
      azione === "confirm" ? "success" : "info",
    );
    await Promise.all([
      aggiornaPrenotazioni(),
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
    descrizione: `La richiesta di ${prenotazioneCorrente?.nome_cliente || "questo cliente"} verrà contrassegnata come rifiutata e il cliente non avrà il tavolo riservato.`,
    label: "Rifiuta",
  });
});

document.getElementById("booking-cancel-btn")?.addEventListener("click", () => {
  eseguiAzionePrenotazione("cancel", {
    chiediConferma: true,
    titolo: "Annullare la prenotazione?",
    descrizione: `La prenotazione di ${prenotazioneCorrente?.nome_cliente || "questo cliente"} verrà annullata e i posti torneranno disponibili.`,
    label: "Annulla prenotazione",
  });
});

document.getElementById("booking-no-show-btn")?.addEventListener("click", () => {
  eseguiAzionePrenotazione("mark-no-show", {
    chiediConferma: true,
    titolo: "Segnare come no-show?",
    descrizione: "La prenotazione verrà chiusa come no-show.",
    label: "Segna no-show",
  });
});

document.getElementById("booking-completed-btn")?.addEventListener("click", () => {
  eseguiAzionePrenotazione("mark-completed", {
    chiediConferma: true,
    titolo: "Segnare come completata?",
    descrizione: "La prenotazione verrà registrata come completata.",
    label: "Completa",
  });
});

function formattaUnitaVerticale(num, singolare = false) {
  const v = (typeof dbProfileRecord !== "undefined" && dbProfileRecord?.verticale)
    || (typeof onboardingState !== "undefined" && onboardingState?.selectedVertical)
    || "ristorante";
  const n = Number(num) || 0;
  if (v === "parrucchiere" || v === "centro_estetico") {
    return singolare || n === 1 ? `${n} persona` : `${n} persone`;
  }
  if (v === "studio_medico_dentista") {
    return singolare || n === 1 ? `${n} paziente` : `${n} pazienti`;
  }
  if (v === "hotel_bnb") {
    return singolare || n === 1 ? `${n} ospite` : `${n} ospiti`;
  }
  return singolare || n === 1 ? `${n} coperto` : `${n} coperti`;
}

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
  bookingDetail.seats.textContent = prenotazione.coperti ? formattaUnitaVerticale(prenotazione.coperti) : "Non indicati";
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

function apriBookingModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.hidden = false;
  document.body.classList.add("booking-modal-open");
}

function chiudiBookingModal(id) {
  const modal = document.getElementById(id);
  if (!modal) return;
  modal.hidden = true;
  if (![...document.querySelectorAll(".booking-modal")].some((element) => !element.hidden)) {
    document.body.classList.remove("booking-modal-open");
  }
}

function apriFormPrenotazione(prenotazione = null) {
  bookingEditingId = prenotazione?.id || null;
  bookingForm?.reset();
  document.getElementById("booking-name").value = prenotazione?.nome_cliente || "";
  document.getElementById("booking-phone").value = prenotazione?.telefono || "";
  document.getElementById("booking-date").value = prenotazione?.data || (bookingCalendar ? _toDateKey(bookingCalendar.getDate()) : "") || oggiIso();
  document.getElementById("booking-time").value = String(prenotazione?.ora || "20:00").slice(0, 5);
  document.getElementById("booking-seats").value = prenotazione?.coperti || "";
  document.getElementById("booking-note").value = prenotazione?.note || "";
  bookingStatusText.textContent = "";
  document.getElementById("booking-create-title").textContent = bookingEditingId ? "Modifica prenotazione" : "Nuova prenotazione";
  apriBookingModal("booking-create-modal");
}

document.querySelectorAll("[data-booking-close]").forEach((element) => {
  element.addEventListener("click", chiudiDettaglioPrenotazione);
});
[
  ["[data-booking-create-close]", "booking-create-modal"],
  ["[data-booking-availability-close]", "booking-availability-modal"],
  ["[data-booking-export-close]", "booking-export-modal"],
  ["[data-booking-actions-close]", "booking-actions-modal"],
].forEach(([selector, id]) => {
  document.querySelectorAll(selector).forEach((element) => element.addEventListener("click", () => chiudiBookingModal(id)));
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  document.querySelectorAll(".booking-modal").forEach((modal) => { modal.hidden = true; });
  document.body.classList.remove("booking-modal-open");
});

document.getElementById("booking-new-trigger")?.addEventListener("click", () => apriFormPrenotazione());
document.getElementById("booking-new-fab")?.addEventListener("click", () => apriFormPrenotazione());
document.getElementById("booking-edit-btn")?.addEventListener("click", () => {
  if (!prenotazioneCorrente) return;
  chiudiDettaglioPrenotazione();
  apriFormPrenotazione(prenotazioneCorrente);
});
document.getElementById("booking-actions-trigger")?.addEventListener("click", () => apriBookingModal("booking-actions-modal"));
document.getElementById("booking-open-availability")?.addEventListener("click", () => {
  chiudiBookingModal("booking-actions-modal");
  apriBookingModal("booking-availability-modal");
});
document.getElementById("booking-open-export")?.addEventListener("click", () => {
  chiudiBookingModal("booking-actions-modal");
  apriBookingModal("booking-export-modal");
});

function inizializzaCalendarioPrenotazioni() {
  if (!bookingCalendarEl || !window.FullCalendar) return;
  const slotRange = intervalloSlotPrenotazioni();
  if (bookingCalendar) {
    bookingCalendar.setOption("slotMinTime", slotRange.min);
    bookingCalendar.setOption("slotMaxTime", slotRange.max);
    bookingCalendar.updateSize();
    return;
  }
  bookingCalendar = new FullCalendar.Calendar(bookingCalendarEl, {
    initialView: "timeGridDay",
    timeZone: "local",
    locale: "it",
    height: "auto",
    allDaySlot: false,
    nowIndicator: true,
    slotDuration: "00:15:00",
    snapDuration: "00:15:00",
    slotLabelInterval: "01:00:00",
    slotMinTime: slotRange.min,
    slotMaxTime: slotRange.max,
    slotLabelContent(info) {
      const ora = `${String(info.date.getHours()).padStart(2, "0")}:${String(info.date.getMinutes()).padStart(2, "0")}`;
      const slot = bookingAvailability.get(ora.slice(0, 5));
      const liberi = slot ? `${slot.coperti_liberi} liberi` : "Disponibile";
      const stato = slot?.stato || "verde";
      return { html: `<span class="booking-slot-label booking-slot-${_sanitize(stato)}"><span class="booking-slot-dot"></span>${_sanitize(ora)}</span>` };
    },
    eventClick(info) { apriDettaglioPrenotazione(info.event.extendedProps); },
    selectable: true,
    headerToolbar: false,
    select(info) {
      apriFormPrenotazione({
        data: _toDateKey(info.start),
        ora: `${String(info.start.getHours()).padStart(2, "0")}:${String(info.start.getMinutes()).padStart(2, "0")}`,
      });
      bookingCalendar.unselect();
    },
    datesSet(info) {
      const dateKey = _toDateKey(info.start);
      aggiornaSemaforo(dateKey);
      renderTabellaPrenotazioniGiorno(dateKey);
      aggiornaToolbarCalendario();
    },
  });
  bookingCalendar.render();
  aggiornaToolbarCalendario();
}

function renderTabellaPrenotazioniGiorno(data = null) {
  const tableBody = document.getElementById("booking-table-body");
  const countEl = document.getElementById("booking-table-day-count");
  const titleEl = document.getElementById("booking-table-day-title");
  if (!tableBody) return;

  const targetDate = data ? _toDateKey(data) : (bookingCalendar ? _toDateKey(bookingCalendar.getDate()) : oggiIso());
  
  if (titleEl) {
    try {
      const dObj = new Date(`${targetDate}T12:00:00`);
      titleEl.textContent = `Prenotazioni di ${dObj.toLocaleDateString("it-IT", { weekday: "long", day: "numeric", month: "long" })}`;
    } catch {
      titleEl.textContent = `Prenotazioni del ${targetDate}`;
    }
  }

  const prenotazioniGiorno = (bookingRecords || [])
    .filter((p) => _toDateKey(p.data) === targetDate)
    .sort((a, b) => String(a.ora || "").localeCompare(String(b.ora || "")));

  if (countEl) {
    countEl.textContent = `${prenotazioniGiorno.length} prenotazioni`;
  }

  if (!prenotazioniGiorno.length) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="8" class="booking-table-empty">
          Nessuna prenotazione per ${targetDate}. Clicca "+ Nuova prenotazione" per aggiungerne una.
        </td>
      </tr>
    `;
    return;
  }

  tableBody.innerHTML = prenotazioniGiorno.map((p) => {
    const ora = String(p.ora || "").slice(0, 5);
    const stato = statoNormalizzatoPrenotazione(p);
    let badgeClass = "booking-badge-confermata";
    if (stato.includes("attesa")) badgeClass = "booking-badge-in_attesa";
    else if (stato.includes("intervento")) badgeClass = "booking-badge-richiede_intervento";
    else if (stato.includes("cancell") || stato.includes("rifiut")) badgeClass = "booking-badge-cancellata";

    return `
      <tr data-booking-id="${_sanitize(p.id)}">
        <td class="booking-row-time">${_sanitize(ora)}</td>
        <td class="booking-row-client">${_sanitize(p.nome_cliente || "Cliente")}</td>
        <td>${_sanitize(p.telefono || "—")}</td>
        <td>${_sanitize(formattaUnitaVerticale(p.coperti || 1))}</td>
        <td><span class="booking-origin-tag">${_sanitize(p.origine || "WhatsApp")}</span></td>
        <td>${_sanitize(p.note || "—")}</td>
        <td><span class="booking-badge ${badgeClass}">${_sanitize(p.stato || "confermata")}</span></td>
        <td style="text-align: right;">
          <button type="button" class="report-refresh" data-open-booking-id="${_sanitize(p.id)}" style="padding: 4px 10px; font-size: 0.75rem;">
            Dettagli
          </button>
        </td>
      </tr>
    `;
  }).join("");

  tableBody.querySelectorAll("[data-open-booking-id]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const bId = btn.dataset.openBookingId;
      const item = bookingRecords.find((b) => String(b.id) === String(bId));
      if (item) apriDettaglioPrenotazione(item);
    });
  });

  tableBody.querySelectorAll("tr[data-booking-id]").forEach((tr) => {
    tr.style.cursor = "pointer";
    tr.addEventListener("click", () => {
      const bId = tr.dataset.bookingId;
      const item = bookingRecords.find((b) => String(b.id) === String(bId));
      if (item) apriDettaglioPrenotazione(item);
    });
  });
}

async function aggiornaPrenotazioni() {
  if (!bookingCalendarEl) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings`);
    if (!res.ok) return;
    const raw = await res.json().catch(() => []);
    const prenotazioni = Array.isArray(raw) ? raw : [];
    bookingRecords = prenotazioni;
    const pending = prenotazioni.filter((p) => statoNormalizzatoPrenotazione(p) === "in_attesa");
    prenotazioniInAttesaCount = pending.length;
    bookingCount.textContent = `${prenotazioni.length} prenotazioni`;
    if (bookingPendingValue) bookingPendingValue.textContent = pending.length;
    const statoNotif = leggiStatoNotifiche();
    aggiornaBadgeNotifiche(statoNotif);
    aggiornaCampana();
    if (!bookingCalendar) inizializzaCalendarioPrenotazioni();
    if (!bookingCalendar) return;
    bookingCalendar.removeAllEvents();
    const mostrabili = bookingPendingOnly ? pending : prenotazioni;
    mostrabili.forEach((p) => {
      if (!p.data || !p.ora) return;
      const dKey = _toDateKey(p.data);
      const ora = String(p.ora).slice(0, 5);
      const [h, m] = ora.split(":").map(Number);
      const totalEndMinutes = (isNaN(m) ? 0 : m) + 15;
      const endH = totalEndMinutes >= 60 ? (h + 1) : h;
      const endM = totalEndMinutes >= 60 ? (totalEndMinutes - 60) : totalEndMinutes;
      const oraFine = `${String(endH).padStart(2, "0")}:${String(endM).padStart(2, "0")}`;
      bookingCalendar.addEvent({
        id: p.id,
        title: `${ora} · ${p.nome_cliente || "Cliente"} · ${formattaUnitaVerticale(p.coperti || 1)}`,
        start: `${dKey}T${ora}:00`,
        end: `${dKey}T${oraFine}:00`,
        backgroundColor: colorePrenotazione(p.stato),
        borderColor: colorePrenotazione(p.stato),
        classNames: statoNormalizzatoPrenotazione(p) === "in_attesa" ? ["booking-event-pending"] : [],
        extendedProps: p,
      });
    });
    const slotRange = intervalloSlotPrenotazioni();
    bookingCalendar.setOption("slotMinTime", slotRange.min);
    bookingCalendar.setOption("slotMaxTime", slotRange.max);
    bookingCalendar.updateSize();
    bookingCalendar.render();
    
    const currentDate = bookingCalendar ? _toDateKey(bookingCalendar.getDate()) : oggiIso();
    renderTabellaPrenotazioniGiorno(currentDate);

    verificaPrenotazioneAggiornata(prenotazioni);
    bookingSnapshot = new Map(prenotazioni.map((p) => [String(p.id), JSON.stringify(p)]));
  } catch (err) {
    console.error("Impossibile caricare le prenotazioni:", err);
  }
}

function intervalloSlotPrenotazioni() {
  const aperte = Object.entries(bookingOpenHours || {})
    .filter(([, capienza]) => Number(capienza) > 0)
    .map(([ora]) => Number(ora.slice(0, 2)));

  const orePrenotazioni = (bookingRecords || [])
    .filter((p) => p.ora)
    .map((p) => Number(String(p.ora).slice(0, 2)));

  const tutte = [...aperte, ...orePrenotazioni].filter((h) => !isNaN(h));
  if (!tutte.length) return { min: "06:00:00", max: "24:00:00" };

  const minH = Math.min(...tutte);
  const maxH = Math.max(...tutte);
  const min = `${String(Math.max(0, Math.min(minH, 6))).padStart(2, "0")}:00:00`;
  const max = maxH >= 23 ? "24:00:00" : `${String(Math.max(maxH + 1, 23)).padStart(2, "0")}:00:00`;
  return { min, max };
}

function aggiornaToolbarCalendario() {
  if (!bookingCalendar) return;
  const vista = bookingCalendar.view.type;
  document.querySelectorAll("[data-booking-calendar-view]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.bookingCalendarView === vista));
  });
}

function verificaPrenotazioneAggiornata(prenotazioni) {
  if (!prenotazioneCorrente?.id || bookingModal?.hidden) return;
  const next = prenotazioni.find((p) => String(p.id) === String(prenotazioneCorrente.id));
  const warning = document.getElementById("booking-detail-stale-warning");
  if (!next || bookingSnapshot.get(String(next.id)) !== JSON.stringify(next)) {
    warning.textContent = next
      ? "Questa prenotazione è stata modificata. Ricarica per vedere lo stato aggiornato."
      : "Questa prenotazione è stata cancellata. Ricarica per vedere lo stato aggiornato.";
    warning.hidden = false;
  }
}

async function aggiornaSemaforo(data = null) {
  if (!availabilityList) return;
  const targetDate = data ? _toDateKey(data) : (bookingCalendar ? _toDateKey(bookingCalendar.getDate()) : oggiIso());
  availabilityDate.textContent = new Date(`${targetDate}T12:00:00`).toLocaleDateString("it-IT", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  });
  try {
    const res = await apiFetch(`${API_BASE}/api/bookings/semaforo?data=${targetDate}`);
    if (!res.ok) return;
    const raw = await res.json().catch(() => []);
    const slots = Array.isArray(raw) ? raw : [];
    bookingAvailability = new Map(slots.map((slot) => [String(slot.ora).slice(0, 5), slot]));
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
    aggiornaRiepilogoPrenotazioni(targetDate, slots);
    renderTabellaPrenotazioniGiorno(targetDate);
    bookingCalendar?.render();
  } catch (err) {
    console.error("Impossibile caricare il semaforo:", err);
  }
}

function aggiornaRiepilogoPrenotazioni(data, slots) {
  const prenotazioniGiorno = (bookingRecords || []).filter((p) => p.data === data && !STATI_FINALI_PRENOTAZIONE.includes(statoNormalizzatoPrenotazione(p)));
  const coperti = prenotazioniGiorno.reduce((totale, p) => totale + (Number(p.coperti) || 0), 0);
  const liberi = (slots || []).reduce((totale, slot) => totale + (Number(slot.coperti_liberi) || 0), 0);
  if (bookingSummary) bookingSummary.textContent = `${prenotazioniGiorno.length} prenotazioni · ${formattaUnitaVerticale(coperti)} · ${liberi} posti liberi`;

  const emptyNotice = document.getElementById("booking-day-empty");
  if (emptyNotice) {
    emptyNotice.hidden = prenotazioniGiorno.length > 0;
    const emptyBtn = document.getElementById("booking-empty-new-btn");
    if (emptyBtn) {
      emptyBtn.onclick = () => {
        apriFormPrenotazione({ data: data ? _toDateKey(data) : oggiIso(), ora: "20:00" });
      };
    }
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
    const standard = document.getElementById("booking-standard-capacity");
    if (standard) {
      const valori = Object.values(capienze).filter((value) => Number(value) > 0);
      standard.value = valori.length ? Math.max(...valori) : "";
    }
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
    const res = await apiFetch(`${API_BASE}/api/bookings${bookingEditingId ? `/${encodeURIComponent(bookingEditingId)}` : ""}`, {
      method: bookingEditingId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail?.messaggio || err?.detail || "Errore salvataggio");
    }
    const wasEditing = Boolean(bookingEditingId);
    bookingForm.reset();
    document.getElementById("booking-date").value = payload.data;
    bookingStatusText.textContent = wasEditing ? "Modifica salvata." : "Prenotazione aggiunta.";
    bookingStatusText.style.color = "var(--sage)";
    bookingEditingId = null;
    chiudiBookingModal("booking-create-modal");
    if (bookingCalendar) {
      bookingCalendar.gotoDate(payload.data);
    }
    await aggiornaPrenotazioni();
    await aggiornaSemaforo(payload.data);
    renderTabellaPrenotazioniGiorno(payload.data);
  } catch (err) {
    bookingStatusText.textContent = bookingEditingId ? "Modifica non salvata, riprova." : err.message;
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
    await aggiornaPrenotazioni();
    capacityStatus.textContent += " Le modifiche sono attive subito.";
  } catch (err) {
    capacityStatus.textContent = err.message;
    capacityStatus.style.color = "var(--red)";
  }
});

document.getElementById("booking-standard-capacity")?.addEventListener("change", (event) => {
  const value = Math.max(0, parseInt(event.target.value, 10) || 0);
  document.querySelectorAll("[data-capacity-hour]").forEach((input) => {
    if (parseInt(input.value, 10) > 0) input.value = value;
  });
});

document.getElementById("booking-pending-count")?.addEventListener("click", () => {
  bookingPendingOnly = !bookingPendingOnly;
  document.getElementById("booking-pending-count").setAttribute("aria-pressed", String(bookingPendingOnly));
  aggiornaPrenotazioni();
});

document.querySelectorAll("[data-booking-calendar-command]").forEach((button) => {
  button.addEventListener("click", () => {
    if (!bookingCalendar) return;
    const command = button.dataset.bookingCalendarCommand;
    if (command === "prev") bookingCalendar.prev();
    if (command === "next") bookingCalendar.next();
    if (command === "today") bookingCalendar.today();
  });
});

document.querySelectorAll("[data-booking-calendar-view]").forEach((button) => {
  button.addEventListener("click", () => bookingCalendar?.changeView(button.dataset.bookingCalendarView));
});

function prenotazioniVisibili() {
  const panel = document.querySelector('[data-view-panel="prenotazioni"]');
  return Boolean(panel && !panel.classList.contains("view-hidden") && !document.hidden);
}

function sincronizzaPollingPrenotazioni() {
  window.clearInterval(bookingPollTimer);
  bookingPollTimer = null;
  if (!prenotazioniVisibili()) return;
  bookingPollTimer = window.setInterval(() => {
    aggiornaPrenotazioni();
    aggiornaSemaforo();
  }, 30000);
}

document.addEventListener("visibilitychange", sincronizzaPollingPrenotazioni);

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
const reviewOriginalBox = document.getElementById("review-original-box");
const reviewOriginalText = document.getElementById("review-original-text");
const reviewDraftSentiment = document.getElementById("review-draft-sentiment");
const reviewDraftCat = document.getElementById("review-draft-cat");
const draftPanelTitle = document.getElementById("draft-panel-title");
const draftStatusBadge = document.getElementById("draft-status-badge");
const draftMetaInfo = document.getElementById("draft-meta-info");
const draftFeedbackText = document.getElementById("draft-feedback-text");
const btnCloseDraft = document.getElementById("btn-close-draft");
const reviewCopy = document.getElementById("review-copy");
const reviewApprove = document.getElementById("review-approve");

const reviewHistoryCard = document.getElementById("review-history-card");
const reviewHistoryList = document.getElementById("review-history-list");
const reviewFilterTabs = document.getElementById("review-filter-tabs");
const reviewSearchInput = document.getElementById("review-search-input");
const reviewFilterSource = document.getElementById("review-filter-source");
const btnRefreshReviews = document.getElementById("btn-refresh-reviews");

const countAll = document.getElementById("count-all");
const countPending = document.getElementById("count-pending");
const countApproved = document.getElementById("count-approved");
const countUrgent = document.getElementById("count-urgent");

const reviewStatCount = document.getElementById("review-stat-count");
const reviewStatRating = document.getElementById("review-stat-rating");
const sidebarRatingNum = document.getElementById("sidebar-rating-num");
const sidebarRatingStars = document.getElementById("sidebar-rating-stars");
const sidebarRatingTotal = document.getElementById("sidebar-rating-total");
const pctPosVal = document.getElementById("pct-pos-val");
const pctNeutVal = document.getElementById("pct-neut-val");
const pctNegVal = document.getElementById("pct-neg-val");
const barPosFill = document.getElementById("bar-pos-fill");
const barNeutFill = document.getElementById("bar-neut-fill");
const barNegFill = document.getElementById("bar-neg-fill");

const trendList = document.getElementById("trend-list");

let reviewAttualeId = null;
let reviewAttualeData = null;
let recensioniPrimoCaricamento = true;
let recensioniFiltroCorrente = "tutte";
let recensioniListaDati = [];

function _formatDataRecensione(iso) {
  if (!iso) return "Data recente";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "Data non valida";
  const oggi = new Date();
  const isOggi = d.toDateString() === oggi.toDateString();
  const timeStr = d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  if (isOggi) return `Oggi alle ${timeStr}`;
  return d.toLocaleDateString("it-IT", { day: "numeric", month: "short", year: "numeric" }) + `, ${timeStr}`;
}

function _fonteLabel(fonte) {
  const f = (fonte || "").toLowerCase();
  if (f === "google") return { label: "Google Business", icon: "G", classe: "channel-google" };
  if (f === "tripadvisor") return { label: "TripAdvisor", icon: "TA", classe: "channel-tripadvisor" };
  return { label: "Manuale", icon: "M", classe: "channel-manuale" };
}

function _stelleVisual(n) {
  const num = Math.max(0, Math.min(5, Number(n) || 0));
  return "★".repeat(num) + "☆".repeat(5 - num);
}

function apriDettaglioRecensione(recId) {
  const item = recensioniListaDati.find((r) => String(r.id) === String(recId));
  if (!item) return;

  reviewAttualeId = String(item.id);
  reviewAttualeData = item;

  if (reviewOriginalText) reviewOriginalText.textContent = item.testo || "";
  if (reviewDraftText) reviewDraftText.value = item.bozza_risposta || "";
  
  const isApprovata = item.stato === "approvata" || item.stato === "pubblicata";
  const isUrgente = item.richiede_revisione_urgente || item.sentiment === "negativa" || (item.valutazione_stelle && item.valutazione_stelle <= 2);

  if (draftPanelTitle) {
    draftPanelTitle.textContent = isApprovata ? "Risposta approvata" : "Bozza di risposta generata";
  }

  if (draftStatusBadge) {
    if (isApprovata) {
      draftStatusBadge.textContent = "Approvata";
      draftStatusBadge.className = "review-status-badge status-approvata";
    } else if (isUrgente) {
      draftStatusBadge.textContent = "Richiede attenzione";
      draftStatusBadge.className = "review-status-badge status-urgente";
    } else {
      draftStatusBadge.textContent = "Bozza pronta";
      draftStatusBadge.className = "review-status-badge";
    }
  }

  const fonteInfo = _fonteLabel(item.fonte);
  if (draftMetaInfo) {
    const autoreStr = item.autore ? `Autore: ${item.autore}` : "Autore non specificato";
    const stelleStr = item.valutazione_stelle ? ` • ★ ${item.valutazione_stelle}/5` : "";
    const dataStr = item.created_at ? ` • ${_formatDataRecensione(item.created_at)}` : "";
    draftMetaInfo.textContent = `${autoreStr} • Canale: ${fonteInfo.label}${stelleStr}${dataStr}`;
  }

  if (reviewDraftSentiment) {
    const s = (item.sentiment || "neutro").toLowerCase();
    reviewDraftSentiment.textContent = s.charAt(0).toUpperCase() + s.slice(1);
    reviewDraftSentiment.className = `review-sentiment-badge sentiment-${s}`;
  }

  if (reviewDraftCat) {
    const cat = item.categoria || "generico";
    reviewDraftCat.textContent = cat.replace(/_/g, " ");
    reviewDraftCat.hidden = false;
  }

  if (draftFeedbackText) draftFeedbackText.textContent = "";

  if (reviewApprove) {
    reviewApprove.disabled = isApprovata;
    reviewApprove.innerHTML = isApprovata
      ? '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Approvata'
      : '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Approva risposta';
  }

  if (reviewDraft) {
    reviewDraft.hidden = false;
    reviewDraft.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function chiudiDettaglioRecensione() {
  if (reviewDraft) reviewDraft.hidden = true;
  reviewAttualeId = null;
  reviewAttualeData = null;
}

async function inviaRecensione() {
  const testo = reviewText ? reviewText.value.trim() : "";
  if (!testo) {
    toast("Inserisci il testo della recensione da analizzare.", "warning");
    reviewText?.focus();
    return;
  }

  reviewAnalyze.disabled = true;
  reviewAnalyze.innerHTML = `
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
    Analisi in corso…
  `;

  try {
    const res = await apiFetch(`${API_BASE}/api/recensione`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        testo,
        valutazione_stelle: reviewStars?.value ? parseInt(reviewStars.value) : null,
        autore: reviewAuthor?.value ? reviewAuthor.value.trim() : "",
        fonte: reviewSource?.value || "manuale",
      }),
    });

    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }

    const data = await res.json();
    reviewAttualeId = data.id;

    // Crea record locale e apri bozza
    const nuovoRecord = {
      id: data.id,
      testo,
      valutazione_stelle: reviewStars?.value ? parseInt(reviewStars.value) : null,
      autore: reviewAuthor?.value ? reviewAuthor.value.trim() : "",
      fonte: reviewSource?.value || "manuale",
      bozza_risposta: data.bozza_risposta,
      sentiment: data.sentiment,
      categoria: data.categoria,
      richiede_revisione_urgente: data.richiede_revisione_urgente,
      stato: data.stato || "bozza_generata",
      created_at: new Date().toISOString(),
    };

    // Aggiungi in testa alla lista locale
    recensioniListaDati = [nuovoRecord, ...recensioniListaDati.filter(r => String(r.id) !== String(data.id))];

    apriDettaglioRecensione(data.id);
    toast("Analisi completata: bozza di risposta generata!", "info");

    await aggiornaRecensioni(true);
    await aggiornaRiepilogo(true);
    await aggiornaPrioritari(true);
    await aggiornaNotifiche();
  } catch (err) {
    toast("Errore: " + err.message, "error");
  } finally {
    if (reviewAnalyze) {
      reviewAnalyze.disabled = false;
      reviewAnalyze.innerHTML = `
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
        Analizza e genera bozza
      `;
    }
  }
}

async function approvaRecensioneDaId(recId) {
  if (!recId) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/recensioni/${recId}/approva`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }
    const data = await res.json();
    
    // Aggiorna stato locale
    recensioniListaDati = recensioniListaDati.map((r) => {
      if (String(r.id) === String(recId)) {
        return { ...r, stato: data.stato || "approvata" };
      }
      return r;
    });

    if (String(reviewAttualeId) === String(recId)) {
      if (draftStatusBadge) {
        draftStatusBadge.textContent = "Approvata";
        draftStatusBadge.className = "review-status-badge status-approvata";
      }
      if (reviewApprove) {
        reviewApprove.disabled = true;
        reviewApprove.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Approvata';
      }
      if (draftFeedbackText) {
        draftFeedbackText.textContent = "Risposta approvata con successo!";
      }
    }

    toast("Risposta approvata con successo!", "info");
    renderStoricoRecensioni();
    aggiornaConteggiRecensioni();
    aggiornaRiepilogo(true);
    aggiornaPrioritari(true);
  } catch (err) {
    toast("Errore durante l'approvazione: " + err.message, "error");
  }
}

async function approvaRecensione() {
  if (!reviewAttualeId) return;
  if (reviewApprove) {
    reviewApprove.disabled = true;
    reviewApprove.textContent = "Approvazione…";
  }
  await approvaRecensioneDaId(reviewAttualeId);
}

function renderStoricoRecensioni() {
  if (!reviewHistoryList) return;

  const searchQuery = (reviewSearchInput?.value || "").toLowerCase().trim();
  const fonteFilter = (reviewFilterSource?.value || "").toLowerCase();

  let filtrate = recensioniListaDati.filter((r) => {
    // Filtro Tab
    if (recensioniFiltroCorrente === "bozza" && !(r.stato === "bozza_generata" || r.stato === "nuova")) {
      return false;
    }
    if (recensioniFiltroCorrente === "approvata" && !(r.stato === "approvata" || r.stato === "pubblicata")) {
      return false;
    }
    if (recensioniFiltroCorrente === "negativa") {
      const isNeg = r.sentiment === "negativa" || r.richiede_revisione_urgente || (r.valutazione_stelle && r.valutazione_stelle <= 2);
      if (!isNeg) return false;
    }

    // Filtro Canale
    if (fonteFilter && (r.fonte || "manuale").toLowerCase() !== fonteFilter) {
      return false;
    }

    // Ricerca testo/autore
    if (searchQuery) {
      const autore = (r.autore || "").toLowerCase();
      const testo = (r.testo || "").toLowerCase();
      const bozza = (r.bozza_risposta || "").toLowerCase();
      if (!autore.includes(searchQuery) && !testo.includes(searchQuery) && !bozza.includes(searchQuery)) {
        return false;
      }
    }

    return true;
  });

  reviewHistoryList.innerHTML = "";

  if (filtrate.length === 0) {
    if (recensioniListaDati.length === 0) {
      reviewHistoryList.appendChild(_emptyState(
        ICONS.chat,
        "Nessuna recensione registrata",
        "Incolla una recensione nel modulo in alto: l'AI valuterà il sentiment e preparerà una bozza di risposta professionale.",
        "Incolla una recensione",
        () => {
          reviewText?.focus();
          reviewText?.scrollIntoView({ behavior: "smooth" });
        }
      ));
    } else {
      reviewHistoryList.appendChild(_emptyState(
        ICONS.alert,
        "Nessun risultato con i filtri attuali",
        "Nessuna recensione corrisponde ai criteri di filtro o ricerca selezionati.",
        "Reimposta filtri",
        () => {
          recensioniFiltroCorrente = "tutte";
          if (reviewFilterTabs) {
            reviewFilterTabs.querySelectorAll(".review-tab").forEach(t => t.classList.toggle("active", t.dataset.tab === "tutte"));
          }
          if (reviewSearchInput) reviewSearchInput.value = "";
          if (reviewFilterSource) reviewFilterSource.value = "";
          renderStoricoRecensioni();
        }
      ));
    }
    return;
  }

  filtrate.forEach((r) => {
    const item = document.createElement("div");
    const isApprovata = r.stato === "approvata" || r.stato === "pubblicata";
    const isUrgente = r.richiede_revisione_urgente || r.sentiment === "negativa" || (r.valutazione_stelle && r.valutazione_stelle <= 2);

    item.className = "review-history-item" + (isUrgente ? " item-urgente" : "") + (isApprovata ? " item-approvata" : "");

    const fonteInfo = _fonteLabel(r.fonte);
    const autoreDisplay = r.autore ? _sanitize(r.autore) : "Cliente";
    const stelleHtml = _stelleVisual(r.valutazione_stelle);
    const dataDisplay = _formatDataRecensione(r.created_at || r.published_at);
    const sentimentStr = (r.sentiment || "neutro").toLowerCase();

    let statusPill = "";
    if (isApprovata) {
      statusPill = '<span class="review-status-badge status-approvata">Approvata</span>';
    } else if (isUrgente) {
      statusPill = '<span class="review-status-badge status-urgente">Richiede attenzione</span>';
    } else {
      statusPill = '<span class="review-status-badge">Bozza pronta</span>';
    }

    const sentimentBadge = `<span class="review-sentiment-badge sentiment-${sentimentStr}">${sentimentStr.charAt(0).toUpperCase() + sentimentStr.slice(1)}</span>`;
    const catBadge = r.categoria ? `<span class="review-cat-badge">${_sanitize(r.categoria.replace(/_/g, " "))}</span>` : "";

    let aiBox = "";
    if (r.bozza_risposta) {
      aiBox = `
        <div class="history-ai-reply-box">
          <span class="ai-reply-label">Bozza di risposta suggerita:</span>
          <p class="ai-reply-text">${_sanitize(r.bozza_risposta)}</p>
        </div>
      `;
    }

    item.innerHTML = `
      <div class="history-item-top">
        <div class="history-item-meta">
          <span class="channel-pill ${fonteInfo.classe}">${fonteInfo.icon} ${fonteInfo.label}</span>
          <span class="history-stars" title="${r.valutazione_stelle || 0} su 5 stelle">${stelleHtml}</span>
          <span class="history-author">${autoreDisplay}</span>
          <span class="history-date">${dataDisplay}</span>
        </div>
        <div>
          ${statusPill}
        </div>
      </div>
      <div class="history-item-body">
        <p class="history-review-text">"${_sanitize(r.testo || "")}"</p>
        ${aiBox}
      </div>
      <div class="history-item-footer">
        <div class="history-tags">
          ${sentimentBadge}
          ${catBadge}
        </div>
        <div class="history-actions">
          ${!isApprovata ? `<button type="button" class="btn-history-action btn-action-primary" data-action="approve" data-id="${r.id}">Approva</button>` : ""}
          <button type="button" class="btn-history-action" data-action="open" data-id="${r.id}">Rivedi bozza</button>
          ${r.bozza_risposta ? `<button type="button" class="btn-history-action" data-action="copy" data-id="${r.id}">Copia testo</button>` : ""}
        </div>
      </div>
    `;

    item.querySelector('[data-action="open"]')?.addEventListener("click", () => apriDettaglioRecensione(r.id));
    item.querySelector('[data-action="approve"]')?.addEventListener("click", () => approvaRecensioneDaId(r.id));
    item.querySelector('[data-action="copy"]')?.addEventListener("click", () => {
      if (r.bozza_risposta) {
        navigator.clipboard.writeText(r.bozza_risposta).catch(() => {});
        toast("Testo della bozza copiato negli appunti!", "info");
      }
    });

    reviewHistoryList.appendChild(item);
  });
}

function aggiornaConteggiRecensioni() {
  const totale = recensioniListaDati.length;
  const pending = recensioniListaDati.filter(r => r.stato === "bozza_generata" || r.stato === "nuova").length;
  const approved = recensioniListaDati.filter(r => r.stato === "approvata" || r.stato === "pubblicata").length;
  const urgent = recensioniListaDati.filter(r => r.richiede_revisione_urgente || r.sentiment === "negativa" || (r.valutazione_stelle && r.valutazione_stelle <= 2)).length;

  if (countAll) countAll.textContent = totale;
  if (countPending) countPending.textContent = pending;
  if (countApproved) countApproved.textContent = approved;
  if (countUrgent) countUrgent.textContent = urgent;

  // Calcolo media stelle
  const conStelle = recensioniListaDati.filter(r => r.valutazione_stelle != null && r.valutazione_stelle > 0);
  const mediaStelle = conStelle.length > 0
    ? (conStelle.reduce((acc, r) => acc + Number(r.valutazione_stelle), 0) / conStelle.length)
    : 0;

  if (reviewStatCount) reviewStatCount.textContent = `${totale} ${totale === 1 ? "recensione" : "recensioni"}`;
  if (reviewStatRating) {
    reviewStatRating.innerHTML = `<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg> <span>${mediaStelle ? mediaStelle.toFixed(1) : "0.0"}</span>`;
  }

  // Sidebar rating & sentiment
  if (sidebarRatingNum) sidebarRatingNum.textContent = mediaStelle ? mediaStelle.toFixed(1) : "--";
  if (sidebarRatingStars) sidebarRatingStars.textContent = _stelleVisual(Math.round(mediaStelle));
  if (sidebarRatingTotal) sidebarRatingTotal.textContent = `Basato su ${totale} ${totale === 1 ? "recensione" : "recensioni"}`;

  // Distribuzione sentiment
  const pos = recensioniListaDati.filter(r => r.sentiment === "positiva" || r.sentiment === "positivo" || (r.valutazione_stelle && r.valutazione_stelle >= 4)).length;
  const neg = recensioniListaDati.filter(r => r.sentiment === "negativa" || r.sentiment === "negativo" || (r.valutazione_stelle && r.valutazione_stelle <= 2)).length;
  const neut = totale - pos - neg;

  const pctPos = totale > 0 ? Math.round((pos / totale) * 100) : 0;
  const pctNeg = totale > 0 ? Math.round((neg / totale) * 100) : 0;
  const pctNeut = totale > 0 ? Math.max(0, 100 - pctPos - pctNeg) : 0;

  if (pctPosVal) pctPosVal.textContent = `${pctPos}%`;
  if (pctNeutVal) pctNeutVal.textContent = `${pctNeut}%`;
  if (pctNegVal) pctNegVal.textContent = `${pctNeg}%`;

  if (barPosFill) barPosFill.style.width = `${pctPos}%`;
  if (barNeutFill) barNeutFill.style.width = `${pctNeut}%`;
  if (barNegFill) barNegFill.style.width = `${pctNeg}%`;
}

function _paroleChiave(testi, max = 3) {
  const stop = ["di", "il", "la", "le", "gli", "un", "una", "che", "per", "con", "non", "ho", "ha", "è", "e", "a", "o", "si", "in", "da", "lo", "sono", "mi", "ma", "ci", "ti", "al", "del", "della", "dei", "delle", "allo", "alla", "ai", "agli", "alle", "dal", "dalla", "dai", "dagli", "dalle", "nel", "nella", "nei", "negli", "nelle", "sul", "sulla", "sui", "sugli", "sulle", "molto", "tanto", "più", "meno", "era", "stato", "stata", "stati", "state", "essere", "questo", "quella", "quello", "conto", "fare", "fatto"];
  const words = testi.join(" ").toLowerCase().replace(/[^a-zàèéìòù\s]/g, "").split(/\s+/).filter(w => w.length > 3 && !stop.includes(w));
  const freq = {};
  words.forEach(w => { freq[w] = (freq[w] || 0) + 1; });
  return Object.entries(freq).sort((a,b) => b[1] - a[1]).slice(0, max).map(e => e[0]);
}

async function aggiornaRecensioni(silent = false) {
  if (!silent && recensioniPrimoCaricamento && reviewHistoryList) {
    reviewHistoryList.innerHTML = _skeletonList(3);
    recensioniPrimoCaricamento = false;
  }

  try {
    // 1. Chiamata ad endpoint dedicato /api/recensioni
    const res = await apiFetch(`${API_BASE}/api/recensioni?limit=50`);
    if (res.ok) {
      const data = await res.json().catch(() => ({ recensioni: [] }));
      recensioniListaDati = Array.isArray(data.recensioni) ? data.recensioni : [];
    } else {
      // Fallback a /api/dashboard se /api/recensioni non è raggiungibile
      const dashRes = await apiFetch(`${API_BASE}/api/dashboard`);
      if (dashRes.ok) {
        const eventi = await dashRes.json().catch(() => []);
        recensioniListaDati = (Array.isArray(eventi) ? eventi : [])
          .filter(e => e.tipo_evento === "recensione")
          .map(e => ({
            id: e.id,
            testo: e.testo_originale,
            valutazione_stelle: e.dettagli?.stelle || e.dettagli?.valutazione_stelle || null,
            fonte: e.dettagli?.fonte || "manuale",
            autore: e.dettagli?.autore || "",
            bozza_risposta: e.risposta_ai || "",
            sentiment: e.dettagli?.sentiment || (e.priorita === "alta" ? "negativa" : "positiva"),
            categoria: e.dettagli?.categoria || "generico",
            richiede_revisione_urgente: Boolean(e.dettagli?.richiede_revisione_urgente || e.priorita === "alta"),
            stato: e.gestito_da_ai ? "approvata" : "bozza_generata",
            created_at: e.timestamp,
          }));
      }
    }

    aggiornaConteggiRecensioni();
    renderStoricoRecensioni();
    aggiornaTrends(recensioniListaDati);
  } catch (err) {
    console.error("Impossibile aggiornare le recensioni:", err);
    if (!silent && reviewHistoryList) {
      reviewHistoryList.innerHTML = "";
      reviewHistoryList.appendChild(_errorState("Impossibile caricare lo storico delle recensioni.", () => aggiornaRecensioni()));
    }
  }
}

async function aggiornaTrends(datiParam) {
  if (!trendList) return;
  try {
    let recensioni = datiParam;
    if (!Array.isArray(recensioni)) {
      const res = await apiFetch(`${API_BASE}/api/dashboard`);
      const eventi = res.ok ? await res.json().catch(() => []) : [];
      recensioni = (Array.isArray(eventi) ? eventi : []).filter(e => e.tipo_evento === "recensione");
    }

    const totale = recensioni.length;
    if (totale === 0) {
      trendList.innerHTML = "";
      const li = document.createElement("li");
      li.appendChild(_emptyState(
        ICONS.trend,
        "Nessun trend rilevato",
        "I temi ricorrenti e i trend di gradimento appariranno automaticamente analizzando le recensioni.",
        null
      ));
      trendList.appendChild(li);
      return;
    }

    const pos = recensioni.filter(e => (e.sentiment === "positiva" || e.sentiment === "positivo" || e.dettagli?.sentiment === "positiva" || (e.valutazione_stelle && e.valutazione_stelle >= 4))).length;
    const neg = recensioni.filter(e => (e.sentiment === "negativa" || e.sentiment === "negativo" || e.dettagli?.sentiment === "negativa" || (e.valutazione_stelle && e.valutazione_stelle <= 2))).length;
    const pctPos = Math.round((pos / totale) * 100);
    const pctNeg = Math.round((neg / totale) * 100);

    const catCount = {};
    recensioni.forEach(e => {
      const c = e.categoria || e.dettagli?.categoria || "generico";
      catCount[c] = (catCount[c] || 0) + 1;
    });
    const topCat = Object.entries(catCount).sort((a, b) => b[1] - a[1]).slice(0, 2);

    const testi = recensioni.map(e => e.testo || e.testo_originale || "");
    const keywords = _paroleChiave(testi, 2);

    const items = [];

    if (pos > 0) {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-pos">▲</span>
          <div class="trend-body">
            <span class="trend-label">Gradimento positivo (${pctPos}%)</span>
            <div class="trend-bar-track"><div class="trend-bar-fill fill-pos" style="width:${pctPos}%"></div></div>
          </div>
        </li>`);
    }

    if (neg > 0) {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-neg">▼</span>
          <div class="trend-body">
            <span class="trend-label">Criticità segnalate (${pctNeg}%)</span>
            <div class="trend-bar-track"><div class="trend-bar-fill fill-neg" style="width:${pctNeg}%"></div></div>
          </div>
        </li>`);
    }

    topCat.forEach(([cat]) => {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-topic">↗</span>
          <div class="trend-body"><span class="trend-label">Tema ricorrente: ${_sanitize(cat.replace(/_/g, " "))}</span></div>
        </li>`);
    });

    keywords.forEach(kw => {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-new">✦</span>
          <div class="trend-body"><span class="trend-label">Parola chiave: "${_sanitize(kw)}"</span></div>
        </li>`);
    });

    trendList.innerHTML = items.join("");
  } catch (err) {
    console.error("Impossibile aggiornare i trend:", err);
  }
}

// Event Listeners Recensioni
reviewCopy?.addEventListener("click", () => {
  const testoBozza = reviewDraftText ? reviewDraftText.value : "";
  if (!testoBozza) return;
  navigator.clipboard.writeText(testoBozza).catch(() => {});
  if (draftFeedbackText) draftFeedbackText.textContent = "Testo copiato negli appunti!";
  toast("Bozza di risposta copiata negli appunti!", "info");
});

reviewApprove?.addEventListener("click", approvaRecensione);
reviewAnalyze?.addEventListener("click", inviaRecensione);
btnCloseDraft?.addEventListener("click", chiudiDettaglioRecensione);
btnRefreshReviews?.addEventListener("click", () => {
  btnRefreshReviews.classList.add("spin");
  aggiornaRecensioni().finally(() => setTimeout(() => btnRefreshReviews.classList.remove("spin"), 500));
});

reviewFilterTabs?.querySelectorAll(".review-tab").forEach((tabBtn) => {
  tabBtn.addEventListener("click", () => {
    reviewFilterTabs.querySelectorAll(".review-tab").forEach(t => t.classList.remove("active"));
    tabBtn.classList.add("active");
    recensioniFiltroCorrente = tabBtn.dataset.tab || "tutte";
    renderStoricoRecensioni();
  });
});

reviewSearchInput?.addEventListener("input", () => renderStoricoRecensioni());
reviewFilterSource?.addEventListener("change", () => renderStoricoRecensioni());

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
    toast("La data inizio è dopo la data fine.", "error");
    return;
  }
  scaricaCsvPrenotazioni(da, a);
});

async function aggiornaReport(forza = false) {
  try {
    const url = `${API_BASE}/api/report${forza ? "?forza=true" : ""}`;
    const res = await apiFetch(url);
    if (!res.ok) return;
    const report = await res.json().catch(() => ({}));
    if (!report || !report.statistiche) return;
    reportSection.hidden = false;
    if (reportEmptyHint) reportEmptyHint.hidden = true;
    reportDate.textContent = report.statistiche?.periodo || "";
    reportTotale.textContent = report.statistiche?.totale_messaggi ?? "0";
    reportAi.textContent = report.statistiche?.gestiti_da_ai ?? "0";
    reportUmano.textContent = report.statistiche?.girati_a_umano ?? "0";
    reportAnalisi.textContent = report.analisi_testuale || "";
    reportTimestamp.textContent = report.generato_il ? "Generato: " + new Date(report.generato_il).toLocaleTimeString("it-IT", {
      hour: "2-digit", minute: "2-digit",
    }) : "";
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
   PANORAMICA — KPI + priorità + attività
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
   chiamata API fallisce (l'utente deve capire che può riprovare, non che
   la sezione sia vuota). */
function _errorState(messaggio, retryFn) {
  const wrap = document.createElement("div");
  wrap.className = "error-state";
  wrap.setAttribute("role", "alert");
  wrap.innerHTML =
    '<div class="empty-state-icon error" aria-hidden="true">' + ICONS.alert + "</div>" +
    '<span class="empty-state-title">Qualcosa è andato storto</span>' +
    '<span class="empty-state-sub">' + _sanitize(messaggio) + "</span>";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "review-analyze";
  btn.textContent = "Riprova";
  btn.addEventListener("click", retryFn);
  wrap.appendChild(btn);
  return wrap;
}

async function caricaStatoOnboarding() {
  try {
    const [resDoc, resBook, resWa] = await Promise.allSettled([
      apiFetch(`${API_BASE}/api/documenti/conteggio`),
      apiFetch(`${API_BASE}/api/bookings/settings`),
      apiFetch(`${API_BASE}/api/whatsapp/settings`)
    ]);

    let hasDocs = false;
    if (resDoc.status === "fulfilled" && resDoc.value?.ok) {
      const d = await resDoc.value.json().catch(() => ({}));
      hasDocs = Number(d.chunk_indicizzati || 0) > 0;
    }

    let hasBookingHours = false;
    if (resBook.status === "fulfilled" && resBook.value?.ok) {
      const b = await resBook.value.json().catch(() => ({}));
      const capienze = b.capienze_orarie || {};
      hasBookingHours = Object.values(capienze).some((v) => Number(v) > 0);
    }

    let hasWa = false;
    if (resWa.status === "fulfilled" && resWa.value?.ok) {
      const w = await resWa.value.json().catch(() => ({}));
      hasWa = Boolean(w.phone_number_id || w.status === "connected" || w.configured);
    }

    return {
      hasDocs,
      hasBookingHours,
      hasWa,
      isFullyConfigured: hasDocs && hasBookingHours && hasWa,
    };
  } catch {
    return { hasDocs: true, hasBookingHours: true, hasWa: true, isFullyConfigured: true };
  }
}

async function aggiornaPrioritari(silent = false) {
  if (!silent && !priorityList.children.length) {
    priorityList.innerHTML = _skeletonList(3);
  }
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard/prioritari`);
    if (!res.ok) {
      if (!silent) {
        priorityList.innerHTML = "";
        priorityList.appendChild(_errorState("Impossibile caricare le richieste urgenti.", () => aggiornaPrioritari()));
      }
      return;
    }
    const rawEventi = await res.json().catch(() => []);
    const eventi = Array.isArray(rawEventi) ? rawEventi : [];
    priorityList.innerHTML = "";
    if (eventi.length === 0) {
      const cfg = await caricaStatoOnboarding();
      const li = document.createElement("li");
      if (!cfg.isFullyConfigured) {
        li.className = "onboarding-checklist-item";
        li.innerHTML = `
          <div class="onboarding-checklist-card">
            <div class="onboarding-checklist-header">
              <div class="onboarding-checklist-icon-wrap" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="22" height="22"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </div>
              <div>
                <h3 class="onboarding-checklist-title">Completa la configurazione iniziale</h3>
                <p class="onboarding-checklist-sub">Segui questi 3 passaggi per attivare l'assistente con i tuoi clienti.</p>
              </div>
            </div>
            <div class="onboarding-checklist-steps">
              <div class="onboarding-step-row">
                <div class="onboarding-step-left">
                  <span class="onboarding-step-indicator ${cfg.hasWa ? "done" : "todo"}">${cfg.hasWa ? "✓" : "1"}</span>
                  <span class="onboarding-step-text ${cfg.hasWa ? "done" : ""}">Collega il numero WhatsApp Business</span>
                </div>
                ${cfg.hasWa
                  ? '<span class="onboarding-step-done-badge">Completato</span>'
                  : '<button type="button" class="onboarding-step-btn" data-action="setup-wa">Collega →</button>'}
              </div>
              <div class="onboarding-step-row">
                <div class="onboarding-step-left">
                  <span class="onboarding-step-indicator ${cfg.hasDocs ? "done" : "todo"}">${cfg.hasDocs ? "✓" : "2"}</span>
                  <span class="onboarding-step-text ${cfg.hasDocs ? "done" : ""}">Carica menu o listino (Knowledge Base)</span>
                </div>
                ${cfg.hasDocs
                  ? '<span class="onboarding-step-done-badge">Completato</span>'
                  : '<button type="button" class="onboarding-step-btn" data-action="setup-docs">Carica PDF →</button>'}
              </div>
              <div class="onboarding-step-row">
                <div class="onboarding-step-left">
                  <span class="onboarding-step-indicator ${cfg.hasBookingHours ? "done" : "todo"}">${cfg.hasBookingHours ? "✓" : "3"}</span>
                  <span class="onboarding-step-text ${cfg.hasBookingHours ? "done" : ""}">Configura orari e capienza tavoli</span>
                </div>
                ${cfg.hasBookingHours
                  ? '<span class="onboarding-step-done-badge">Completato</span>'
                  : '<button type="button" class="onboarding-step-btn" data-action="setup-booking">Configura →</button>'}
              </div>
            </div>
          </div>
        `;
        li.querySelector('[data-action="setup-wa"]')?.addEventListener("click", () => {
          document.querySelector('[data-view="impostazioni"]')?.click();
          setTimeout(() => document.querySelector('[data-settings-tab="whatsapp"]')?.click(), 50);
        });
        li.querySelector('[data-action="setup-docs"]')?.addEventListener("click", () => {
          document.querySelector('[data-view="conoscenza"]')?.click();
        });
        li.querySelector('[data-action="setup-booking"]')?.addEventListener("click", () => {
          document.querySelector('[data-view="impostazioni"]')?.click();
          setTimeout(() => document.querySelector('[data-settings-tab="regole"]')?.click(), 50);
        });
      } else {
        li.appendChild(_emptyState(
          ICONS.check,
          "Nessun messaggio oggi",
          "L'assistente è configurato e pronto a rispondere automaticamente ai tuoi clienti."
        ));
      }
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
      cat.textContent = (e.dettagli?.categoria || e.dettagli?.sentiment || "generico");
      li.appendChild(badge);
      li.appendChild(msg);
      li.appendChild(cat);

      if (e.tipo_evento === "recensione") {
        li.style.cursor = "pointer";
        li.title = "Clicca per aprire e gestire questa recensione";
        li.addEventListener("click", () => {
          apriView("recensioni");
          setTimeout(() => {
            if (e.id && typeof apriDettaglioRecensione === "function") {
              apriDettaglioRecensione(e.id);
            }
          }, 80);
        });
      }

      priorityList.appendChild(li);
    });
  } catch (err) {
    console.error("Impossibile aggiornare gli eventi prioritari:", err);
    priorityList.innerHTML = "";
    priorityList.appendChild(_errorState("Impossibile caricare le richieste urgenti.", aggiornaPrioritari));
  }
}

/* ============================================================
   KPI & SPARKLINE 7 GIORNI (PANORAMICA)
   ============================================================ */

function generaSparklineSvg(dataPoints, strokeColor, gradientId) {
  const pts = Array.isArray(dataPoints) && dataPoints.length === 7 ? dataPoints : [0, 0, 0, 0, 0, 0, 0];
  const maxVal = Math.max(...pts, 1);
  const width = 120;
  const height = 28;
  const padX = 4;
  const padY = 4;
  const availW = width - padX * 2;
  const availH = height - padY * 2;

  const allZero = pts.every((v) => v === 0);

  if (allZero) {
    const yBaseline = height - padY - 2;
    return `
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="width:100%;height:100%;">
        <line x1="${padX}" y1="${yBaseline}" x2="${width - padX}" y2="${yBaseline}" stroke="var(--line-strong)" stroke-width="1.5" stroke-dasharray="3,3" />
      </svg>
    `;
  }

  const coords = pts.map((val, i) => {
    const x = padX + i * (availW / (pts.length - 1));
    const y = height - padY - (val / maxVal) * availH;
    return { x: Number(x.toFixed(1)), y: Number(y.toFixed(1)) };
  });

  let pathD = `M ${coords[0].x} ${coords[0].y}`;
  for (let i = 1; i < coords.length; i++) {
    const prev = coords[i - 1];
    const curr = coords[i];
    const cpX1 = prev.x + (curr.x - prev.x) / 2;
    const cpY1 = prev.y;
    const cpX2 = prev.x + (curr.x - prev.x) / 2;
    const cpY2 = curr.y;
    pathD += ` C ${cpX1} ${cpY1}, ${cpX2} ${cpY2}, ${curr.x} ${curr.y}`;
  }

  const fillD = `${pathD} L ${coords[coords.length - 1].x} ${height} L ${coords[0].x} ${height} Z`;
  const lastPt = coords[coords.length - 1];

  return `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" style="width:100%;height:100%;">
      <defs>
        <linearGradient id="${gradientId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${strokeColor}" stop-opacity="0.3" />
          <stop offset="100%" stop-color="${strokeColor}" stop-opacity="0.0" />
        </linearGradient>
      </defs>
      <path d="${fillD}" fill="url(#${gradientId})" />
      <path d="${pathD}" fill="none" stroke="${strokeColor}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="${lastPt.x}" cy="${lastPt.y}" r="2.5" fill="${strokeColor}" />
    </svg>
  `;
}

function calcolaTrendKpi(oggi, ieri, tipoMetrica) {
  // tipoMetrica: 'totale' | 'ai' | 'umano'
  if (ieri === 0 && oggi === 0) {
    return {
      testo: tipoMetrica === "umano" ? "Nessuna escalation" : "In linea con ieri",
      icona: "—",
      classe: "trend-neutral",
    };
  }
  if (ieri === 0 && oggi > 0) {
    const isGood = tipoMetrica !== "umano";
    return {
      testo: `+${oggi} rispetto a ieri`,
      icona: "↑",
      classe: isGood ? "trend-positive" : "trend-warning",
    };
  }
  const diff = oggi - ieri;
  const pct = Math.round((diff / ieri) * 100);
  if (pct === 0) {
    return {
      testo: "In linea con ieri",
      icona: "—",
      classe: "trend-neutral",
    };
  }
  if (pct > 0) {
    if (tipoMetrica === "ai") {
      return { testo: `+${pct}% rispetto a ieri`, icona: "↑", classe: "trend-positive" };
    } else if (tipoMetrica === "umano") {
      return { testo: `+${pct}% rispetto a ieri`, icona: "↑", classe: "trend-warning" };
    } else {
      return { testo: `+${pct}% rispetto a ieri`, icona: "↑", classe: "trend-info" };
    }
  } else {
    // Calo
    if (tipoMetrica === "ai") {
      return { testo: `${pct}% rispetto a ieri`, icona: "↓", classe: "trend-neutral" };
    } else if (tipoMetrica === "umano") {
      return { testo: `${pct}% rispetto a ieri`, icona: "↓", classe: "trend-positive" };
    } else {
      return { testo: `${pct}% rispetto a ieri`, icona: "↓", classe: "trend-neutral" };
    }
  }
}

function applicaBadgeTrend(elId, trendObj) {
  const el = document.getElementById(elId);
  if (!el) return;
  el.className = `kpi-trend-badge ${trendObj.classe}`;
  el.innerHTML = `
    <span class="trend-icon">${trendObj.icona}</span>
    <span class="trend-text">${_sanitize(trendObj.testo)}</span>
  `;
}

function _toDateKey(d) {
  const date = d instanceof Date ? d : new Date(d);
  if (isNaN(date.getTime())) return "";
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

let isPanoramicaPollingActive = false;
let panoramicaPollingTimer = null;

function avviaPanoramicaPolling() {
  if (isPanoramicaPollingActive) return;
  isPanoramicaPollingActive = true;
  panoramicaPollingTimer = setInterval(async () => {
    if (!isPanoramicaPollingActive) return;
    if (document.hidden) return;
    const currentView = document.querySelector(".nav-item.active")?.dataset?.view || "panoramica";
    if (currentView !== "panoramica") {
      fermaPanoramicaPolling();
      return;
    }
    await Promise.all([
      aggiornaRiepilogo(true),
      aggiornaPrioritari(true),
    ]);
  }, 5000);
}

function fermaPanoramicaPolling() {
  isPanoramicaPollingActive = false;
  if (panoramicaPollingTimer) {
    clearInterval(panoramicaPollingTimer);
    panoramicaPollingTimer = null;
  }
}

async function aggiornaRiepilogo(silent = false) {
  if (!silent && !ticketList.children.length) {
    ticketList.innerHTML = _skeletonList(3);
  }
  try {
    const res = await apiFetch(`${API_BASE}/api/dashboard`);
    if (!res.ok) {
      if (!silent) {
        ticketList.innerHTML = "";
        ticketList.appendChild(_errorState("Impossibile caricare l'attività recente.", () => aggiornaRiepilogo()));
      }
      return;
    }
    const rawStorico = await res.json().catch(() => []);
    const storico = Array.isArray(rawStorico) ? rawStorico : [];

    // Calcolo 7 giorni storici
    const oggiDate = new Date();
    const giorni7 = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date(oggiDate);
      d.setDate(d.getDate() - i);
      const key = _toDateKey(d);
      giorni7.push({ dateKey: key, totale: 0, ai: 0, umano: 0 });
    }

    const oggiKey = _toDateKey(oggiDate);
    const eventiOggi = [];

    storico.forEach((e) => {
      if (!e.timestamp) return;
      const evDate = _toDateKey(e.timestamp);
      if (evDate === oggiKey) {
        eventiOggi.push(e);
      }
      const giornoObj = giorni7.find((g) => g.dateKey === evDate);
      if (giornoObj) {
        giornoObj.totale++;
        if (e.gestito_da_ai) giornoObj.ai++;
        else giornoObj.umano++;
      }
    });

    const totaleOggi = eventiOggi.length;
    const gestitiAiOggi = eventiOggi.filter((e) => e.gestito_da_ai).length;
    const giratiOggi = totaleOggi - gestitiAiOggi;

    if (statTotale) statTotale.textContent = totaleOggi;
    if (statAi) statAi.textContent = gestitiAiOggi;
    if (statUmano) statUmano.textContent = giratiOggi;

    // Calcolo trend e sparklines
    const totalePts = giorni7.map((g) => g.totale);
    const aiPts = giorni7.map((g) => g.ai);
    const umanoPts = giorni7.map((g) => g.umano);

    const ieriTotale = totalePts[5] || 0;
    const ieriAi = aiPts[5] || 0;
    const ieriUmano = umanoPts[5] || 0;

    // Badges
    const trendTotale = calcolaTrendKpi(totaleOggi, ieriTotale, "totale");
    const trendAi = calcolaTrendKpi(gestitiAiOggi, ieriAi, "ai");
    const trendUmano = calcolaTrendKpi(giratiOggi, ieriUmano, "umano");

    applicaBadgeTrend("trend-totale", trendTotale);
    applicaBadgeTrend("trend-ai", trendAi);
    applicaBadgeTrend("trend-umano", trendUmano);

    // Sparklines SVG
    const sparkTotaleEl = document.getElementById("sparkline-totale");
    const sparkAiEl = document.getElementById("sparkline-ai");
    const sparkUmanoEl = document.getElementById("sparkline-umano");

    if (sparkTotaleEl) {
      sparkTotaleEl.innerHTML = generaSparklineSvg(totalePts, "var(--accent)", "grad-kpi-totale");
    }
    if (sparkAiEl) {
      sparkAiEl.innerHTML = generaSparklineSvg(aiPts, "var(--sage)", "grad-kpi-ai");
    }
    if (sparkUmanoEl) {
      sparkUmanoEl.innerHTML = generaSparklineSvg(umanoPts, "var(--amber)", "grad-kpi-umano");
    }

    const totSettimana = totalePts.reduce((a, b) => a + b, 0);
    const aiSettimana = aiPts.reduce((a, b) => a + b, 0);
    const umanoSettimana = umanoPts.reduce((a, b) => a + b, 0);

    const valTotEl = document.getElementById("sparkline-totale-val");
    const valAiEl = document.getElementById("sparkline-ai-val");
    const valUmanoEl = document.getElementById("sparkline-umano-val");

    if (valTotEl) valTotEl.textContent = `${totSettimana} sett.`;
    if (valAiEl) valAiEl.textContent = `${aiSettimana} sett.`;
    if (valUmanoEl) valUmanoEl.textContent = `${umanoSettimana} sett.`;

    ticketList.innerHTML = "";
    const eventiDaMostrare = eventiOggi.length > 0 ? eventiOggi.slice().reverse() : storico.slice(0, 15);

    if (eventiDaMostrare.length === 0) {
      ticketList.appendChild(_emptyState(
        ICONS.chat,
        "In attesa di conversazioni",
        "I messaggi dei clienti e le risposte dell'assistente compariranno qui in tempo reale.",
        "Prova nel simulatore",
        () => document.querySelector('[data-view="assistente"]')?.click()
      ));
      return;
    }

    eventiDaMostrare.forEach((e) => {
      const li = document.createElement("li");
      li.classList.add("ticket-item", `prio-${e.priorita}`);
      const testoWrap = document.createElement("div");
      testoWrap.classList.add("ticket-item-text");
      const msg = document.createElement("p");
      msg.classList.add("ticket-item-msg");
      msg.textContent = e.testo_originale;
      const time = document.createElement("span");
      time.classList.add("ticket-item-time");
      const isOggi = _toDateKey(e.timestamp) === oggiKey;
      time.textContent = isOggi
        ? new Date(e.timestamp).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" })
        : new Date(e.timestamp).toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit" }) + " " + new Date(e.timestamp).toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
      testoWrap.appendChild(msg);
      testoWrap.appendChild(time);
      const tags = document.createElement("div");
      tags.classList.add("ticket-item-tags");
      const tipoBadge = document.createElement("span");
      tipoBadge.classList.add("ticket-tag", `ticket-tag-${e.tipo_evento}`);
      tipoBadge.textContent = e.tipo_evento === "recensione" ? "Recensione" : "Messaggio";
      tags.appendChild(tipoBadge);
      if (e.tipo_evento === "recensione" && e.dettagli?.stelle) {
        const stelleTag = document.createElement("span");
        stelleTag.classList.add("ticket-tag", "ticket-tag-stelle");
        stelleTag.textContent = "\u2605".repeat(e.dettagli.stelle) + "\u2606".repeat(5 - e.dettagli.stelle);
        tags.appendChild(stelleTag);
      }
      if (e.tipo_evento === "recensione") {
        const viewBtn = document.createElement("button");
        viewBtn.classList.add("ticket-copy-btn");
        viewBtn.textContent = "Visualizza";
        viewBtn.addEventListener("click", () => {
          apriView("recensioni");
          setTimeout(() => {
            if (e.id && typeof apriDettaglioRecensione === "function") {
              apriDettaglioRecensione(e.id);
            }
          }, 80);
        });
        tags.appendChild(viewBtn);
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
    if (!silent) {
      ticketList.innerHTML = "";
      ticketList.appendChild(_errorState("Impossibile caricare l'attività recente.", () => aggiornaRiepilogo()));
    }
  }
}

/* ============================================================
   KNOWLEDGE BASE RISTRUTTURATA (4 CATEGORIE)
   ============================================================ */

let kbActiveTab = "faq";

// Navigazione Tab della Knowledge Base
document.querySelectorAll(".kb-tab-btn[data-kb-tab]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const tabName = btn.dataset.kbTab;
    impostaTabConoscenza(tabName);
  });
});

function impostaTabConoscenza(tabName) {
  kbActiveTab = tabName;
  document.querySelectorAll(".kb-tab-btn[data-kb-tab]").forEach((b) => {
    const active = b.dataset.kbTab === tabName;
    b.classList.toggle("active", active);
    b.setAttribute("aria-selected", String(active));
  });

  const panels = {
    faq: document.getElementById("kb-panel-faq"),
    documenti: document.getElementById("kb-panel-documenti"),
    web: document.getElementById("kb-panel-web"),
    "dati-struttura": document.getElementById("kb-panel-dati-struttura"),
  };

  Object.entries(panels).forEach(([key, panel]) => {
    if (panel) panel.hidden = key !== tabName;
  });

  // Carica i dati specifici del tab
  if (tabName === "faq") caricaFAQ();
  else if (tabName === "documenti") caricaDocumenti();
  else if (tabName === "web") caricaPagineWeb();
  else if (tabName === "dati-struttura") caricaDatiStruttura();
}

function _formatDataOra(isoStr) {
  if (!isoStr) return "N/D";
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return isoStr;
  }
}

// ── Summary & Conflitti Aggregati ────────────────────────────

async function caricaKBSummary() {
  try {
    const res = await apiFetch(`${API_BASE}/api/conoscenza/summary`);
    if (!res.ok) return;
    const data = await res.json();

    // Aggiorna contatori tab
    const badgeFAQ = document.getElementById("kb-badge-faq");
    const badgeDoc = document.getElementById("kb-badge-documenti");
    const badgeWeb = document.getElementById("kb-badge-web");
    const badgeDati = document.getElementById("kb-badge-dati-struttura");
    if (badgeFAQ) badgeFAQ.textContent = data.faq?.totale || 0;
    if (badgeDoc) badgeDoc.textContent = data.documenti?.totale || 0;
    if (badgeWeb) badgeWeb.textContent = data.web?.totale || 0;
    if (badgeDati) badgeDati.textContent = data.dati_struttura?.totale || 0;

    // Aggiorna card statistiche
    const statFAQ = document.getElementById("kb-stat-faq");
    const statFAQMeta = document.getElementById("kb-stat-faq-meta");
    if (statFAQ) statFAQ.textContent = `${data.faq?.attive || 0}/${data.faq?.totale || 0}`;
    if (statFAQMeta) {
      statFAQMeta.textContent = data.faq?.errori ? `${data.faq.errori} con errore` : "Tutte indicizzate";
    }

    const statDoc = document.getElementById("kb-stat-doc");
    const statDocMeta = document.getElementById("kb-stat-doc-meta");
    if (statDoc) statDoc.textContent = `${data.documenti?.attive || 0}/${data.documenti?.totale || 0}`;
    if (statDocMeta) {
      statDocMeta.textContent = data.documenti?.errori ? `${data.documenti.errori} con errore` : "Tutti indicizzati";
    }

    const statWeb = document.getElementById("kb-stat-web");
    const statWebMeta = document.getElementById("kb-stat-web-meta");
    if (statWeb) statWeb.textContent = `${data.web?.attive || 0}/${data.web?.totale || 0}`;
    if (statWebMeta) {
      statWebMeta.textContent = data.web?.errori ? `${data.web.errori} non raggiungibili` : "Tutte indicizzate";
    }

    const statDati = document.getElementById("kb-stat-dati");
    if (statDati) statDati.textContent = `${data.dati_struttura?.totale || 0} configurati`;

    // Verifica e visualizzazione banner conflitti
    const bannerConflitti = document.getElementById("kb-conflitti-banner");
    const dettagliConflitti = document.getElementById("kb-conflitti-dettagli");
    if (data.conflitti_totali > 0) {
      const confRes = await apiFetch(`${API_BASE}/api/conoscenza/conflitti`);
      if (confRes.ok) {
        const confData = await confRes.json();
        if (confData.conflitti?.length && bannerConflitti && dettagliConflitti) {
          dettagliConflitti.innerHTML = "";
          confData.conflitti.forEach((c) => {
            const item = document.createElement("div");
            item.className = "kb-conflict-item";
            item.textContent = `Servizio "${c.servizio}": prezzo ufficiale ${c.prezzo_ufficiale.toFixed(2)}€ vs ${c.prezzo_conflitto.toFixed(2)}€ menzionato in "${c.fonte_conflitto}"`;
            dettagliConflitti.appendChild(item);
          });
          bannerConflitti.hidden = false;
        }
      }
    } else if (bannerConflitti) {
      bannerConflitti.hidden = true;
    }
  } catch (err) {
    console.error("Errore recupero summary knowledge base:", err);
  }
}

// ── Tab 1: FAQ Manager ───────────────────────────────────────

const kbFAQList = document.getElementById("kb-faq-list");
const kbFAQFormCard = document.getElementById("kb-faq-form-card");
const kbFAQOpenFormBtn = document.getElementById("kb-faq-open-form-btn");
const kbFAQCancelBtn = document.getElementById("kb-faq-cancel-btn");
const kbFAQSaveBtn = document.getElementById("kb-faq-save-btn");
const kbFAQDomanda = document.getElementById("kb-faq-domanda");
const kbFAQRisposta = document.getElementById("kb-faq-risposta");
const kbFAQEditId = document.getElementById("kb-faq-edit-id");
const kbFAQFormStatus = document.getElementById("kb-faq-form-status");

kbFAQOpenFormBtn?.addEventListener("click", () => {
  if (!kbFAQFormCard) return;
  kbFAQEditId.value = "";
  kbFAQDomanda.value = "";
  kbFAQRisposta.value = "";
  kbFAQFormStatus.textContent = "";
  kbFAQFormCard.style.display = "block";
  kbFAQDomanda.focus();
});

kbFAQCancelBtn?.addEventListener("click", () => {
  if (kbFAQFormCard) kbFAQFormCard.style.display = "none";
});

kbFAQSaveBtn?.addEventListener("click", async () => {
  const domanda = kbFAQDomanda.value.trim();
  const risposta = kbFAQRisposta.value.trim();
  const editId = kbFAQEditId.value.trim();

  if (!domanda || !risposta) {
    kbFAQFormStatus.textContent = "Inserisci sia la domanda che la risposta.";
    kbFAQFormStatus.style.color = "var(--red)";
    return;
  }

  kbFAQSaveBtn.disabled = true;
  kbFAQSaveBtn.textContent = "Salvataggio…";
  kbFAQFormStatus.textContent = "";

  try {
    const url = editId ? `${API_BASE}/api/conoscenza/faq/${encodeURIComponent(editId)}` : `${API_BASE}/api/conoscenza/faq`;
    const method = editId ? "PUT" : "POST";
    const res = await apiFetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domanda, risposta }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Errore durante il salvataggio della FAQ");
    }

    kbFAQFormCard.style.display = "none";
    kbFAQDomanda.value = "";
    kbFAQRisposta.value = "";
    kbFAQEditId.value = "";
    await caricaFAQ();
    await caricaKBSummary();
  } catch (err) {
    kbFAQFormStatus.textContent = err.message || "Errore di connessione.";
    kbFAQFormStatus.style.color = "var(--red)";
  } finally {
    kbFAQSaveBtn.disabled = false;
    kbFAQSaveBtn.textContent = "Salva FAQ";
  }
});

async function caricaFAQ() {
  if (!kbFAQList) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/elenco?tipo=faq`);
    if (!res.ok) throw new Error("Errore nel caricamento delle FAQ");
    const data = await res.json();
    const items = data.documenti || [];

    // Aggiorna status bar tab
    const statusBarText = document.getElementById("kb-faq-status-text");
    const statusUpdatedText = document.getElementById("kb-faq-updated-text");
    const attive = items.filter((d) => d.is_active).length;
    if (statusBarText) {
      statusBarText.textContent = `${attive} FAQ attive su ${items.length} totali (tutte indicizzate)`;
    }
    if (statusUpdatedText && items.length > 0) {
      const lastUpdate = items[0].updated_at || items[0].caricato_il;
      statusUpdatedText.textContent = `Ultimo aggiornamento: ${_formatDataOra(lastUpdate)}`;
    }

    kbFAQList.innerHTML = "";
    if (items.length === 0) {
      kbFAQList.innerHTML = '<p class="doc-library-empty">Nessuna FAQ configurata. Clicca su "+ Nuova FAQ" per aggiungerne una.</p>';
      return;
    }

    items.forEach((faq) => {
      const meta = faq.metadata || {};
      const domanda = meta.domanda || faq.nome;
      const risposta = meta.risposta || "";
      const isActive = faq.is_active !== false;

      const card = document.createElement("div");
      card.className = `kb-item-card ${isActive ? "" : "is-inactive"}`;

      // Contenuto principale
      const main = document.createElement("div");
      main.className = "kb-item-main";

      const title = document.createElement("div");
      title.className = "kb-item-title";
      title.textContent = domanda;

      const sub = document.createElement("div");
      sub.className = "kb-item-subtitle";
      sub.textContent = risposta;

      const metaRow = document.createElement("div");
      metaRow.className = "kb-item-meta";

      const badgeStato = document.createElement("span");
      if (faq.stato === "errore") {
        badgeStato.className = "kb-badge kb-badge-danger";
        badgeStato.textContent = "Errore";
      } else if (isActive) {
        badgeStato.className = "kb-badge kb-badge-success";
        badgeStato.textContent = "Indicizzata";
      } else {
        badgeStato.className = "kb-badge kb-badge-neutral";
        badgeStato.textContent = "Disattivata";
      }

      const dateMeta = document.createElement("span");
      dateMeta.textContent = `Aggiornata: ${_formatDataOra(faq.updated_at || faq.caricato_il)}`;

      metaRow.append(badgeStato, dateMeta);
      main.append(title, sub, metaRow);

      // Azioni: switch toggle, edit, delete
      const actions = document.createElement("div");
      actions.className = "kb-item-actions";

      // Toggle switch attivo/disattivo
      const switchLabel = document.createElement("label");
      switchLabel.className = "kb-switch";
      switchLabel.title = isActive ? "Disattiva fonte" : "Attiva fonte";

      const switchInput = document.createElement("input");
      switchInput.type = "checkbox";
      switchInput.checked = isActive;
      switchInput.addEventListener("change", async () => {
        try {
          const togRes = await apiFetch(`${API_BASE}/api/documenti/${encodeURIComponent(faq.id)}/toggle`, { method: "PATCH" });
          if (!togRes.ok) throw new Error("Errore durante l'aggiornamento dello stato");
          await caricaFAQ();
          await caricaKBSummary();
        } catch (err) {
          switchInput.checked = !switchInput.checked;
          alert(err.message || "Impossibile aggiornare lo stato.");
        }
      });

      const switchSlider = document.createElement("span");
      switchSlider.className = "kb-switch-slider";
      switchLabel.append(switchInput, switchSlider);

      // Edit button
      const editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "inbox-quick-action";
      editBtn.style.padding = "4px 8px";
      editBtn.textContent = "Modifica";
      editBtn.addEventListener("click", () => {
        kbFAQEditId.value = faq.id;
        kbFAQDomanda.value = domanda;
        kbFAQRisposta.value = risposta;
        kbFAQFormCard.style.display = "block";
        kbFAQDomanda.focus();
      });

      // Delete button
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "kb-btn-delete";
      delBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>
        <span>Elimina</span>
      `;
      delBtn.addEventListener("click", async () => {
        const ok = await confermaDestructiva({
          titolo: "Eliminare questa FAQ?",
          descrizione: `L'assistente non potrà più usare la risposta a: "${domanda}"`,
          label: "Elimina FAQ",
        });
        if (!ok) return;
        try {
          const delRes = await apiFetch(`${API_BASE}/api/conoscenza/faq/${encodeURIComponent(faq.id)}`, { method: "DELETE" });
          if (!delRes.ok) throw new Error("Errore durante l'eliminazione");
          await caricaFAQ();
          await caricaKBSummary();
        } catch (err) {
          alert(err.message || "Impossibile eliminare la FAQ.");
        }
      });

      actions.append(switchLabel, editBtn, delBtn);
      card.append(main, actions);
      kbFAQList.appendChild(card);
    });
  } catch (err) {
    console.error("Errore caricaFAQ:", err);
    kbFAQList.innerHTML = '<p class="doc-library-empty" style="color:var(--red);">Errore nel caricamento delle FAQ.</p>';
  }
}

// ── Tab 2: Documenti Manager & Drag-and-Drop ─────────────────

const docLibrary = document.getElementById("doc-library");
const docFile = document.getElementById("doc-file");
const kbDocDropzone = document.getElementById("kb-doc-dropzone");
const docCaricaTesto = document.getElementById("doc-carica-testo");
const docCaricaNome = document.getElementById("doc-carica-nome");
const docCaricaBtn = document.getElementById("doc-carica-btn");
const docCaricaStatus = document.getElementById("doc-carica-status");

// Setup drag and drop
if (kbDocDropzone && docFile) {
  kbDocDropzone.addEventListener("click", () => docFile.click());
  kbDocDropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    kbDocDropzone.classList.add("dragover");
  });
  kbDocDropzone.addEventListener("dragleave", () => {
    kbDocDropzone.classList.remove("dragover");
  });
  kbDocDropzone.addEventListener("drop", async (e) => {
    e.preventDefault();
    kbDocDropzone.classList.remove("dragover");
    const file = e.dataTransfer?.files?.[0];
    if (file) await eseguiUploadFile(file);
  });
  docFile.addEventListener("change", async () => {
    const file = docFile.files?.[0];
    if (file) await eseguiUploadFile(file);
  });
}

async function eseguiUploadFile(file) {
  if (!docCaricaStatus) return;
  docCaricaStatus.textContent = `Caricamento e indicizzazione di "${file.name}"…`;
  docCaricaStatus.style.color = "var(--ink)";
  try {
    const form = new FormData();
    form.append("file", file);
    const res = await apiFetch(`${API_BASE}/api/documenti/carica-file`, { method: "POST", body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Errore durante il caricamento del file");
    }
    const data = await res.json();
    docCaricaStatus.textContent = data.detail || `File "${file.name}" indicizzato con successo!`;
    docCaricaStatus.style.color = "var(--green)";
    if (docFile) docFile.value = "";
    await caricaDocumenti();
    await caricaKBSummary();
  } catch (err) {
    docCaricaStatus.textContent = err.message || "Errore durante l'estrazione del file.";
    docCaricaStatus.style.color = "var(--red)";
    await caricaDocumenti();
    await caricaKBSummary();
  }
}

// Upload testo libero
docCaricaBtn?.addEventListener("click", async () => {
  const testo = docCaricaTesto.value.trim();
  const nome = docCaricaNome.value.trim() || "documento.txt";
  if (!testo) {
    docCaricaStatus.textContent = "Incolla il testo del documento prima di salvare.";
    docCaricaStatus.style.color = "var(--red)";
    return;
  }
  docCaricaBtn.disabled = true;
  docCaricaBtn.textContent = "Indicizzazione…";
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/carica`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ testo, nome }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Errore durante l'indicizzazione");
    }
    docCaricaStatus.textContent = `Testo "${nome}" indicizzato con successo.`;
    docCaricaStatus.style.color = "var(--green)";
    docCaricaTesto.value = "";
    docCaricaNome.value = "";
    await caricaDocumenti();
    await caricaKBSummary();
  } catch (err) {
    docCaricaStatus.textContent = err.message || "Errore durante il salvataggio.";
    docCaricaStatus.style.color = "var(--red)";
  } finally {
    docCaricaBtn.disabled = false;
    docCaricaBtn.textContent = "Salva testo";
  }
});

async function caricaDocumenti() {
  if (!docLibrary) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/elenco`);
    if (!res.ok) throw new Error("Errore nel recupero documenti");
    const data = await res.json();
    const items = (data.documenti || []).filter((d) => d.tipo === "documento" || d.tipo === "upload");

    const statusBarText = document.getElementById("kb-doc-status-text");
    const statusUpdatedText = document.getElementById("kb-doc-updated-text");
    const attivi = items.filter((d) => d.is_active && d.stato !== "errore").length;
    if (statusBarText) {
      statusBarText.textContent = `${attivi} documenti attivi su ${items.length} totali`;
    }
    if (statusUpdatedText && items.length > 0) {
      statusUpdatedText.textContent = `Ultimo aggiornamento: ${_formatDataOra(items[0].updated_at || items[0].caricato_il)}`;
    }

    docLibrary.innerHTML = "";
    if (items.length === 0) {
      docLibrary.innerHTML = '<p class="doc-library-empty">Nessun file caricato. Usa l\'area tratteggiata sopra per caricare PDF, DOCX o immagini.</p>';
      return;
    }

    items.forEach((doc) => {
      const isActive = doc.is_active !== false && doc.stato !== "errore";
      const card = document.createElement("div");
      card.className = `kb-item-card ${isActive ? "" : "is-inactive"}`;

      const main = document.createElement("div");
      main.className = "kb-item-main";

      const title = document.createElement("div");
      title.className = "kb-item-title";
      title.textContent = doc.nome;

      const metaRow = document.createElement("div");
      metaRow.className = "kb-item-meta";

      const badgeStato = document.createElement("span");
      if (doc.stato === "errore") {
        badgeStato.className = "kb-badge kb-badge-danger";
        badgeStato.textContent = "Errore estrazione";
        badgeStato.title = doc.errore || "File illeggibile o corrotto";
      } else if (isActive) {
        badgeStato.className = "kb-badge kb-badge-success";
        badgeStato.textContent = "Indicizzato";
      } else {
        badgeStato.className = "kb-badge kb-badge-neutral";
        badgeStato.textContent = "Disattivato";
      }

      const chunkMeta = document.createElement("span");
      chunkMeta.textContent = `${doc.chunk || 0} chunk`;

      const dateMeta = document.createElement("span");
      dateMeta.textContent = `Caricato: ${_formatDataOra(doc.caricato_il)}`;

      metaRow.append(badgeStato, chunkMeta, dateMeta);
      main.append(title, metaRow);

      const actions = document.createElement("div");
      actions.className = "kb-item-actions";

      // Toggle switch
      if (doc.stato !== "errore") {
        const switchLabel = document.createElement("label");
        switchLabel.className = "kb-switch";
        switchLabel.title = isActive ? "Disattiva documento" : "Attiva documento";

        const switchInput = document.createElement("input");
        switchInput.type = "checkbox";
        switchInput.checked = isActive;
        switchInput.addEventListener("change", async () => {
          try {
            const togRes = await apiFetch(`${API_BASE}/api/documenti/${encodeURIComponent(doc.id)}/toggle`, { method: "PATCH" });
            if (!togRes.ok) throw new Error("Errore switch");
            await caricaDocumenti();
            await caricaKBSummary();
          } catch (err) {
            switchInput.checked = !switchInput.checked;
            alert(err.message || "Impossibile aggiornare lo stato.");
          }
        });

        const switchSlider = document.createElement("span");
        switchSlider.className = "kb-switch-slider";
        switchLabel.append(switchInput, switchSlider);
        actions.appendChild(switchLabel);
      }

      // Delete button
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "kb-btn-delete";
      delBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>
        <span>Elimina</span>
      `;
      delBtn.addEventListener("click", async () => {
        const ok = await confermaDestructiva({
          titolo: "Rimuovere questo documento?",
          descrizione: `"${doc.nome}" verrà eliminato definitivamente dalla knowledge base.`,
          label: "Elimina documento",
        });
        if (!ok) return;
        try {
          const delRes = await apiFetch(`${API_BASE}/api/documenti/${encodeURIComponent(doc.id)}`, { method: "DELETE" });
          if (!delRes.ok) throw new Error("Errore eliminazione");
          await caricaDocumenti();
          await caricaKBSummary();
        } catch (err) {
          alert(err.message || "Impossibile rimuovere il documento.");
        }
      });
      actions.appendChild(delBtn);

      card.append(main, actions);
      docLibrary.appendChild(card);
    });
  } catch (err) {
    console.error("Errore caricaDocumenti:", err);
  }
}

// ── Tab 3: Pagine Web Manager ────────────────────────────────

const kbWebList = document.getElementById("kb-web-list");
const kbWebUrlInput = document.getElementById("kb-web-url-input");
const kbWebImportBtn = document.getElementById("kb-web-import-btn");
const kbWebImportStatus = document.getElementById("kb-web-import-status");

kbWebImportBtn?.addEventListener("click", async () => {
  const url = (kbWebUrlInput?.value || "").trim();
  if (!url || (!url.startsWith("http://") && !url.startsWith("https://"))) {
    kbWebImportStatus.textContent = "Inserisci un URL valido che inizi con http:// o https://";
    kbWebImportStatus.style.color = "var(--red)";
    return;
  }

  kbWebImportBtn.disabled = true;
  kbWebImportBtn.textContent = "Recupero in corso…";
  kbWebImportStatus.textContent = `Scaricamento e indicizzazione dei contenuti da ${url}…`;
  kbWebImportStatus.style.color = "var(--ink)";

  try {
    const res = await apiFetch(`${API_BASE}/api/conoscenza/web`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Impossibile estrarre la pagina web");
    }

    const data = await res.json();
    kbWebImportStatus.textContent = data.detail || "Pagina web importata con successo!";
    kbWebImportStatus.style.color = "var(--green)";
    kbWebUrlInput.value = "";
    await caricaPagineWeb();
    await caricaKBSummary();
  } catch (err) {
    kbWebImportStatus.textContent = err.message || "Errore durante l'importazione.";
    kbWebImportStatus.style.color = "var(--red)";
    await caricaPagineWeb();
    await caricaKBSummary();
  } finally {
    kbWebImportBtn.disabled = false;
    kbWebImportBtn.textContent = "Importa e indicizza";
  }
});

async function caricaPagineWeb() {
  if (!kbWebList) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/elenco?tipo=web`);
    if (!res.ok) throw new Error("Errore recupero pagine web");
    const data = await res.json();
    const items = data.documenti || [];

    const statusBarText = document.getElementById("kb-web-status-text");
    const statusUpdatedText = document.getElementById("kb-web-updated-text");
    const attive = items.filter((d) => d.is_active && d.stato !== "errore").length;
    if (statusBarText) {
      statusBarText.textContent = `${attive} pagine web attive su ${items.length} totali`;
    }
    if (statusUpdatedText && items.length > 0) {
      statusUpdatedText.textContent = `Ultimo aggiornamento: ${_formatDataOra(items[0].updated_at || items[0].caricato_il)}`;
    }

    kbWebList.innerHTML = "";
    if (items.length === 0) {
      kbWebList.innerHTML = '<p class="doc-library-empty">Nessuna pagina web importata. Inserisci un link sopra per importare listino o info dal tuo sito.</p>';
      return;
    }

    items.forEach((item) => {
      const isActive = item.is_active !== false && item.stato !== "errore";
      const card = document.createElement("div");
      card.className = `kb-item-card ${isActive ? "" : "is-inactive"}`;

      const main = document.createElement("div");
      main.className = "kb-item-main";

      const title = document.createElement("div");
      title.className = "kb-item-title";
      title.textContent = item.nome;

      const sub = document.createElement("div");
      sub.className = "kb-item-subtitle";
      sub.innerHTML = `<a href="${_sanitize(item.fonte)}" target="_blank" rel="noopener noreferrer" style="color:var(--accent);">${_sanitize(item.fonte)}</a>`;

      const metaRow = document.createElement("div");
      metaRow.className = "kb-item-meta";

      const badgeStato = document.createElement("span");
      if (item.stato === "errore") {
        badgeStato.className = "kb-badge kb-badge-danger";
        badgeStato.textContent = "Errore import";
        badgeStato.title = item.errore || "URL non raggiungibile";
      } else if (isActive) {
        badgeStato.className = "kb-badge kb-badge-success";
        badgeStato.textContent = "Indicizzata";
      } else {
        badgeStato.className = "kb-badge kb-badge-neutral";
        badgeStato.textContent = "Disattivata";
      }

      const chunkMeta = document.createElement("span");
      chunkMeta.textContent = `${item.chunk || 0} chunk`;

      const dateMeta = document.createElement("span");
      dateMeta.textContent = `Importata: ${_formatDataOra(item.caricato_il)}`;

      metaRow.append(badgeStato, chunkMeta, dateMeta);
      main.append(title, sub, metaRow);

      const actions = document.createElement("div");
      actions.className = "kb-item-actions";

      if (item.stato !== "errore") {
        const switchLabel = document.createElement("label");
        switchLabel.className = "kb-switch";
        switchLabel.title = isActive ? "Disattiva pagina" : "Attiva pagina";

        const switchInput = document.createElement("input");
        switchInput.type = "checkbox";
        switchInput.checked = isActive;
        switchInput.addEventListener("change", async () => {
          try {
            const togRes = await apiFetch(`${API_BASE}/api/documenti/${encodeURIComponent(item.id)}/toggle`, { method: "PATCH" });
            if (!togRes.ok) throw new Error("Errore switch");
            await caricaPagineWeb();
            await caricaKBSummary();
          } catch (err) {
            switchInput.checked = !switchInput.checked;
            alert(err.message || "Impossibile aggiornare lo stato.");
          }
        });

        const switchSlider = document.createElement("span");
        switchSlider.className = "kb-switch-slider";
        switchLabel.append(switchInput, switchSlider);
        actions.appendChild(switchLabel);
      }

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "kb-btn-delete";
      delBtn.innerHTML = `
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>
        <span>Elimina</span>
      `;
      delBtn.addEventListener("click", async () => {
        const ok = await confermaDestructiva({
          titolo: "Rimuovere questa pagina web?",
          descrizione: `L'assistente non userà più i contenuti importati da "${item.fonte}".`,
          label: "Elimina pagina",
        });
        if (!ok) return;
        try {
          const delRes = await apiFetch(`${API_BASE}/api/documenti/${encodeURIComponent(item.id)}`, { method: "DELETE" });
          if (!delRes.ok) throw new Error("Errore eliminazione");
          await caricaPagineWeb();
          await caricaKBSummary();
        } catch (err) {
          alert(err.message || "Impossibile rimuovere la pagina.");
        }
      });
      actions.appendChild(delBtn);

      card.append(main, actions);
      kbWebList.appendChild(card);
    });
  } catch (err) {
    console.error("Errore caricaPagineWeb:", err);
  }
}

// ── Tab 4: Dati Struttura Manager ────────────────────────────

const kbServiziTbody = document.getElementById("kb-servizi-tbody");
const kbAddServizioBtn = document.getElementById("kb-add-servizio-btn");
const kbOrariInput = document.getElementById("kb-orari-input");
const kbSalvaDatiBtn = document.getElementById("kb-salva-dati-btn");
const kbDatiSaveStatus = document.getElementById("kb-dati-save-status");

function _creaRigaServizio(s = {}) {
  const tr = document.createElement("tr");
  tr.dataset.servizioId = s.id || "";

  // Nome
  const tdNome = document.createElement("td");
  const inNome = document.createElement("input");
  inNome.type = "text";
  inNome.className = "kb-table-input kb-servizio-nome";
  inNome.placeholder = "Es. Taglio Uomo";
  inNome.value = s.nome || "";
  tdNome.appendChild(inNome);

  // Prezzo
  const tdPrezzo = document.createElement("td");
  const inPrezzo = document.createElement("input");
  inPrezzo.type = "number";
  inPrezzo.className = "kb-table-input kb-servizio-prezzo";
  inPrezzo.placeholder = "25.00";
  inPrezzo.step = "0.5";
  inPrezzo.min = "0";
  inPrezzo.value = s.prezzo != null ? s.prezzo : "";
  tdPrezzo.appendChild(inPrezzo);

  // Durata
  const tdDurata = document.createElement("td");
  const inDurata = document.createElement("input");
  inDurata.type = "number";
  inDurata.className = "kb-table-input kb-servizio-durata";
  inDurata.placeholder = "30";
  inDurata.step = "5";
  inDurata.min = "5";
  inDurata.value = s.durata_minuti || 30;
  tdDurata.appendChild(inDurata);

  // Operatore
  const tdOp = document.createElement("td");
  const inOp = document.createElement("input");
  inOp.type = "text";
  inOp.className = "kb-table-input kb-servizio-operatore";
  inOp.placeholder = "Es. Marco o Qualsiasi";
  inOp.value = s.operatore || "";
  tdOp.appendChild(inOp);

  // Azioni (elimina riga)
  const tdAzioni = document.createElement("td");
  tdAzioni.style.textAlign = "center";
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "kb-btn-delete";
  removeBtn.innerHTML = `
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>
    <span>Elimina</span>
  `;
  removeBtn.title = "Elimina questo servizio";
  removeBtn.addEventListener("click", () => tr.remove());
  tdAzioni.appendChild(removeBtn);

  tr.append(tdNome, tdPrezzo, tdDurata, tdOp, tdAzioni);
  return tr;
}

kbAddServizioBtn?.addEventListener("click", () => {
  if (!kbServiziTbody) return;
  const newRow = _creaRigaServizio();
  kbServiziTbody.appendChild(newRow);
  newRow.querySelector(".kb-servizio-nome")?.focus();
});

kbSalvaDatiBtn?.addEventListener("click", async () => {
  if (!kbServiziTbody) return;
  const rows = kbServiziTbody.querySelectorAll("tr");
  const servizi = [];

  rows.forEach((tr) => {
    const nome = tr.querySelector(".kb-servizio-nome")?.value.trim();
    const prezzoRaw = tr.querySelector(".kb-servizio-prezzo")?.value.trim();
    const durataRaw = tr.querySelector(".kb-servizio-durata")?.value.trim();
    const operatore = tr.querySelector(".kb-servizio-operatore")?.value.trim() || "";

    if (nome) {
      servizi.push({
        id: tr.dataset.servizioId || null,
        nome,
        prezzo: parseFloat(prezzoRaw) || 0.0,
        durata_minuti: parseInt(durataRaw, 10) || 30,
        operatore,
      });
    }
  });

  const orari = (kbOrariInput?.value || "").trim();

  kbSalvaDatiBtn.disabled = true;
  kbSalvaDatiBtn.textContent = "Salvataggio e indicizzazione…";
  if (kbDatiSaveStatus) kbDatiSaveStatus.textContent = "";

  try {
    const res = await apiFetch(`${API_BASE}/api/conoscenza/dati-struttura`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ servizi, orari }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => null);
      throw new Error(err?.detail || "Errore durante il salvataggio dei Dati struttura");
    }

    if (kbDatiSaveStatus) {
      kbDatiSaveStatus.textContent = "Dati struttura e listino sincronizzati con successo (Priorità 1 applicata).";
      kbDatiSaveStatus.style.color = "var(--green)";
    }
    const aiCfgOrari = document.getElementById("ai-cfg-orari");
    if (aiCfgOrari && orari) {
      aiCfgOrari.value = orari;
    }
    await caricaDatiStruttura();
    await caricaKBSummary();
  } catch (err) {
    if (kbDatiSaveStatus) {
      kbDatiSaveStatus.textContent = err.message || "Errore durante il salvataggio.";
      kbDatiSaveStatus.style.color = "var(--red)";
    }
  } finally {
    kbSalvaDatiBtn.disabled = false;
    kbSalvaDatiBtn.textContent = "Salva Dati Struttura";
  }
});

async function caricaDatiStruttura() {
  if (!kbServiziTbody) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/conoscenza/dati-struttura`);
    if (!res.ok) throw new Error("Errore recupero dati struttura");
    const data = await res.json();

    const statusBarText = document.getElementById("kb-dati-status-text");
    const statusUpdatedText = document.getElementById("kb-dati-updated-text");
    if (statusBarText) {
      statusBarText.textContent = `${(data.servizi || []).length} servizi configurati — Priorità 1 (Massima autorevolezza)`;
    }
    if (statusUpdatedText) {
      statusUpdatedText.textContent = data.updated_at ? `Ultimo aggiornamento: ${_formatDataOra(data.updated_at)}` : "Pronto per la configurazione";
    }

    if (kbOrariInput) {
      kbOrariInput.value = data.orari || "";
    }

    kbServiziTbody.innerHTML = "";
    if (data.servizi && data.servizi.length > 0) {
      data.servizi.forEach((s) => {
        kbServiziTbody.appendChild(_creaRigaServizio(s));
      });
    } else {
      // Inserisci riga iniziale vuota pronta all'uso
      kbServiziTbody.appendChild(_creaRigaServizio());
    }
  } catch (err) {
    console.error("Errore caricaDatiStruttura:", err);
  }
}

// ── Tester "Chiedi alla Knowledge Base" ───────────────────────

const docQuery = document.getElementById("doc-query");
const docChiediBtn = document.getElementById("doc-chiedi-btn");
const docRisposta = document.getElementById("doc-risposta");
const docRispostaText = document.getElementById("doc-risposta-text");
const docFonti = document.getElementById("doc-fonti");
const docFontiList = document.getElementById("doc-fonti-list");

docChiediBtn?.addEventListener("click", async () => {
  const domanda = (docQuery?.value || "").trim();
  if (!domanda) return;
  docChiediBtn.disabled = true;
  docChiediBtn.textContent = "Interrogazione AI in corso…";
  docRisposta.hidden = true;
  try {
    const res = await apiFetch(`${API_BASE}/api/documenti/chiedi`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ domanda, k: 5 }),
    });
    if (!res.ok) throw new Error("Errore durante l'elaborazione della domanda");
    const data = await res.json();
    docRispostaText.textContent = data.risposta;
    docRisposta.hidden = false;

    if (data.fonti && data.fonti.length > 0) {
      docFonti.hidden = false;
      docFontiList.innerHTML = "";
      data.fonti.forEach((f) => {
        const li = document.createElement("li");
        li.className = "doc-fonti-item";

        // Label priorità
        let priorityLabel = "";
        let priorityClass = "kb-badge-neutral";
        if (f.priorita === 1 || f.tipo === "dati_struttura") {
          priorityLabel = "Priorità 1 (Dati struttura)";
          priorityClass = "kb-badge-success";
        } else if (f.priorita === 2 || f.tipo === "faq") {
          priorityLabel = "Priorità 2 (FAQ)";
          priorityClass = "kb-badge-priority";
        } else if (f.priorita === 3 || f.tipo === "documento" || f.tipo === "upload") {
          priorityLabel = "Priorità 3 (Documento)";
          priorityClass = "kb-badge-warning";
        } else if (f.priorita === 4 || f.tipo === "web") {
          priorityLabel = "Priorità 4 (Web)";
          priorityClass = "kb-badge-neutral";
        }

        const statoFonte = f.stato === "indicizzata" ? '<span class="kb-badge kb-badge-success">Indicizzata</span>' : '<span class="kb-badge kb-badge-warning">In elaborazione</span>';

        li.innerHTML = `
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
            <strong>${_sanitize(f.documento)}</strong>
            <div style="display:flex;gap:6px;">
              <span class="kb-badge ${priorityClass}">${priorityLabel}</span>
              ${statoFonte}
            </div>
          </div>
          <div style="font-size:0.75rem;color:var(--ink-soft);">Score rilevanza semantica: <span class="doc-fonti-score">${_sanitize(f.score)}</span></div>
        `;
        docFontiList.appendChild(li);
      });
    } else {
      docFonti.hidden = true;
    }
  } catch (err) {
    docRispostaText.textContent = err.message || "Errore durante la ricerca.";
    docRisposta.hidden = false;
    docFonti.hidden = true;
  } finally {
    docChiediBtn.disabled = false;
    docChiediBtn.textContent = "Fai una domanda di test";
  }
});

// Funzione principale richiamata dal router della vista "conoscenza"
async function aggiornaConoscenzaCompleta() {
  await caricaKBSummary();
  if (kbActiveTab === "faq") await caricaFAQ();
  else if (kbActiveTab === "documenti") await caricaDocumenti();
  else if (kbActiveTab === "web") await caricaPagineWeb();
  else if (kbActiveTab === "dati-struttura") await caricaDatiStruttura();
}

/* ============================================================
   INBOX (HITL) — Layout a 3 colonne
   ============================================================ */

let inboxState = {
  mainFilter: "all",
  quickFilter: "all",
  selectedTicketId: null,
  tickets: [],
  team: [],
  isLoading: false,
};

const TICKET_STATUS_LABEL = {
  AI_ACTIVE: "AI",
  PENDING_STAFF: "Richiede operatore",
  CLAIMED: "Preso in carico",
  RESOLVED: "Risolto",
};

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

const AVATAR_COLOR_PALETTES = [
  { bg: "#EBF5FF", text: "#1E40AF" },
  { bg: "#F0FDF4", text: "#166534" },
  { bg: "#FEF3C7", text: "#92400E" },
  { bg: "#FEE2E2", text: "#991B1B" },
  { bg: "#F3E8FF", text: "#6B21A8" },
  { bg: "#ECFDF5", text: "#065F46" },
  { bg: "#FFF1F2", text: "#9F1239" },
  { bg: "#F5F3FF", text: "#5B21B6" },
];

function _getAvatarColors(identifier) {
  let hash = 0;
  const str = String(identifier || "");
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return AVATAR_COLOR_PALETTES[Math.abs(hash) % AVATAR_COLOR_PALETTES.length];
}

function _getAvatarInitial(nameOrPhone) {
  if (!nameOrPhone) return "C";
  const trimmed = nameOrPhone.trim();
  if (trimmed.startsWith("+")) {
    return trimmed.slice(-2);
  }
  const parts = trimmed.split(" ").filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return trimmed.slice(0, 2).toUpperCase();
}

function formatInboxDate(value) {
  if (!value) return "";
  const d = new Date(value);
  return d.toLocaleString("it-IT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function formatRelativeTime(value) {
  if (!value) return "";
  const d = new Date(value);
  const now = new Date();
  const diffSec = Math.floor((now - d) / 1000);
  if (diffSec < 60) return "Adesso";
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin} min fa`;
  const diffOre = Math.floor(diffMin / 60);
  if (diffOre < 24 && d.getDate() === now.getDate()) return `${diffOre} ore fa`;
  if (diffOre < 48 && (now.getDate() - d.getDate() === 1 || diffOre < 24)) return "Ieri";
  return d.toLocaleDateString("it-IT", { day: "2-digit", month: "short" });
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

function formatMessageContent(rawText) {
  if (!rawText) return "";
  let text = String(rawText);
  // Escapa caratteri HTML base
  text = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Riconosci link markdown [testo](url)
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+)\)/g, (match, linkText, url) => {
    return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="thread-link">${linkText}</a>`;
  });

  // Riconosci URL raw non racchiusi in tag
  text = text.replace(/(^|[\s(])((?:https?:\/\/|www\.)[^\s<)]+)/g, (match, prefix, url) => {
    const href = url.startsWith("www.") ? `https://${url}` : url;
    return `${prefix}<a href="${href}" target="_blank" rel="noopener noreferrer" class="thread-link">${url}</a>`;
  });

  // Newline in <br>
  text = text.replace(/\n/g, "<br>");

  if (typeof DOMPurify !== "undefined" && DOMPurify.sanitize) {
    return DOMPurify.sanitize(text, { ADD_ATTR: ["target", "rel", "class"] });
  }
  return text;
}

/* ---------- Polling & Caricamento Inbox ---------- */

let inboxPollingTimer = null;
let isInboxPollingActive = false;

function avviaInboxPolling() {
  fermaInboxPolling();
  isInboxPollingActive = true;
  inboxPollingTimer = setInterval(async () => {
    if (!isInboxPollingActive) return;
    if (document.hidden) return; // Pausa se la scheda è in background
    const currentView = document.querySelector(".nav-item.active")?.dataset?.view || "panoramica";
    if (currentView !== "inbox") {
      fermaInboxPolling();
      return;
    }
    await caricaInbox(true); // silent = true: nessun skeleton, zero flicker
  }, 3000);
}

function fermaInboxPolling() {
  isInboxPollingActive = false;
  if (inboxPollingTimer) {
    clearInterval(inboxPollingTimer);
    inboxPollingTimer = null;
  }
}

async function caricaInbox(silent = false) {
  const container = document.getElementById("inbox-list");
  if (!container) return;

  if (!silent && !inboxState.tickets.length) {
    container.innerHTML = _skeletonList(4);
  }

  try {
    const [ticketsRes, teamRes] = await Promise.all([
      apiFetch(`${API_BASE}/api/inbox/tickets?limit=100`),
      apiFetch(`${API_BASE}/api/inbox/team`).catch(() => ({ ok: false })),
    ]);

    if (!ticketsRes.ok) {
      if (!silent) {
        container.innerHTML = "";
        container.appendChild(_errorState("Impossibile caricare le conversazioni.", () => caricaInbox()));
      }
      return;
    }

    const data = await ticketsRes.json();
    const newTickets = data.tickets || [];

    const prevSig = (inboxState.tickets || []).map(t => `${t.id}:${t.last_message_at}:${t.ticket_status}:${t.unread_count || 0}:${t.last_message_preview}`).join("|");
    const newSig = newTickets.map(t => `${t.id}:${t.last_message_at}:${t.ticket_status}:${t.unread_count || 0}:${t.last_message_preview}`).join("|");

    inboxState.tickets = newTickets;

    if (teamRes.ok) {
      try {
        const teamData = await teamRes.json();
        inboxState.team = teamData.members || [];
      } catch (e) {
        inboxState.team = [];
      }
    }

    aggiornaContatoriFiltri();

    if (prevSig !== newSig || !silent) {
      renderInboxConversazioni();
    }

    // Se c'era un ticket selezionato o siamo su desktop e nessun ticket è selezionato, seleziona il primo
    if (inboxState.selectedTicketId) {
      const exists = inboxState.tickets.some((t) => t.id === inboxState.selectedTicketId);
      if (exists) {
        await caricaDettaglioTicket(inboxState.selectedTicketId, silent);
      } else {
        const firstVisible = getFilteredTickets()[0];
        if (firstVisible && window.innerWidth >= 1024) {
          selezionaTicket(firstVisible.id);
        } else {
          inboxState.selectedTicketId = null;
          mostraPlaceholderDettaglio();
        }
      }
    } else if (window.innerWidth >= 768) {
      const firstVisible = getFilteredTickets()[0];
      if (firstVisible) {
        selezionaTicket(firstVisible.id);
      } else {
        mostraPlaceholderDettaglio();
      }
    }
  } catch (err) {
    console.error("Errore caricamento inbox:", err);
    if (!silent) {
      container.innerHTML = "";
      container.appendChild(_errorState("Impossibile caricare l'inbox.", () => caricaInbox()));
    }
  }
}

function getFilteredTickets() {
  let list = [...inboxState.tickets];

  // 1. Filtro Principale (Colonna 1)
  const mf = inboxState.mainFilter;
  if (mf === "ai_managed") {
    list = list.filter((t) => t.ticket_status === "AI_ACTIVE");
  } else if (mf === "pending_staff") {
    list = list.filter((t) => t.ticket_status === "PENDING_STAFF");
  } else if (mf === "escalated") {
    list = list.filter((t) => t.ticket_status === "PENDING_STAFF" || t.priorita === "alta" || t.is_overdue);
  } else if (mf === "channel_whatsapp") {
    list = list.filter((t) => (t.canale || "whatsapp").toLowerCase() === "whatsapp");
  } else if (mf === "channel_instagram") {
    list = list.filter((t) => (t.canale || "").toLowerCase() === "instagram");
  } else if (mf === "status_open") {
    list = list.filter((t) => t.ticket_status !== "RESOLVED");
  } else if (mf === "status_pending") {
    list = list.filter((t) => t.ticket_status === "PENDING_STAFF");
  } else if (mf === "status_resolved") {
    list = list.filter((t) => t.ticket_status === "RESOLVED");
  }

  // 2. Quick Filter (Colonna 2 chips)
  const qf = inboxState.quickFilter;
  if (qf === "whatsapp") {
    list = list.filter((t) => (t.canale || "whatsapp").toLowerCase() === "whatsapp");
  } else if (qf === "instagram") {
    list = list.filter((t) => (t.canale || "").toLowerCase() === "instagram");
  } else if (qf === "ai") {
    list = list.filter((t) => t.ticket_status === "AI_ACTIVE");
  } else if (qf === "human") {
    list = list.filter((t) => t.ticket_status === "CLAIMED");
  } else if (qf === "escalated") {
    list = list.filter((t) => t.ticket_status === "PENDING_STAFF" || t.priorita === "alta" || t.is_overdue);
  }

  return list;
}

function aggiornaContatoriFiltri() {
  const all = inboxState.tickets;
  const countAll = all.length;
  const countWa = all.filter((t) => (t.canale || "whatsapp").toLowerCase() === "whatsapp").length;
  const countIg = all.filter((t) => (t.canale || "").toLowerCase() === "instagram").length;
  const countEscalated = all.filter((t) => t.ticket_status === "PENDING_STAFF" || t.priorita === "alta" || t.is_overdue).length;

  const elAll = document.getElementById("chip-cnt-all");
  const elWa = document.getElementById("chip-cnt-wa");
  const elIg = document.getElementById("chip-cnt-ig");
  const elEsc = document.getElementById("chip-cnt-escalated");

  if (elAll) elAll.textContent = countAll;
  if (elWa) elWa.textContent = countWa;
  if (elIg) elIg.textContent = countIg;
  if (elEsc) elEsc.textContent = countEscalated;
}

function renderInboxConversazioni() {
  const container = document.getElementById("inbox-list");
  if (!container) return;

  const tickets = getFilteredTickets();
  container.innerHTML = "";

  if (!tickets.length) {
    if (!inboxState.tickets.length) {
      const waConfigured = Boolean(window._waConnected || false);
      if (!waConfigured) {
        container.appendChild(
          _emptyState(
            ICONS.inbox,
            "Nessuna conversazione",
            "Collega il tuo account WhatsApp Business o Instagram per iniziare a ricevere i messaggi dei clienti.",
            "Collega i canali",
            () => {
              document.querySelector('[data-view="impostazioni"]')?.click();
              setTimeout(() => document.querySelector('[data-settings-tab="whatsapp"]')?.click(), 50);
            }
          )
        );
      } else {
        container.appendChild(
          _emptyState(
            ICONS.inbox,
            "In attesa di nuovi messaggi",
            "Le conversazioni dei clienti su WhatsApp e Instagram compariranno automaticamente qui in tempo reale."
          )
        );
      }
    } else {
      container.appendChild(
        _emptyState(
          ICONS.inbox,
          "Nessun risultato",
          "Non ci sono conversazioni corrispondenti ai filtri attivi.",
          "Mostra tutte",
          () => {
            inboxState.mainFilter = "all";
            inboxState.quickFilter = "all";
            inboxState.search = "";
            const searchInput = document.getElementById("inbox-search-input");
            if (searchInput) searchInput.value = "";
            document.querySelectorAll(".inbox-nav-filter").forEach((b) => {
              b.classList.toggle("active", b.dataset.inboxMainFilter === "all");
            });
            document.querySelectorAll(".inbox-quick-filter-chip").forEach((b) => {
              b.classList.toggle("active", b.dataset.inboxQuickFilter === "all");
            });
            renderInboxConversazioni();
          }
        )
      );
    }
    return;
  }

  tickets.forEach((t) => {
    const row = document.createElement("div");
    row.className = "inbox-conv-row";
    if (t.id === inboxState.selectedTicketId) {
      row.classList.add("active");
    }
    row.dataset.ticketId = t.id;

    // Avatar
    const colors = _getAvatarColors(t.phone_number || t.id);
    const initial = _getAvatarInitial(t.phone_number || "Cliente");
    const avatarEl = document.createElement("div");
    avatarEl.className = "inbox-conv-avatar";
    avatarEl.style.backgroundColor = colors.bg;
    avatarEl.style.color = colors.text;
    avatarEl.textContent = initial;

    // Body
    const bodyEl = document.createElement("div");
    bodyEl.className = "inbox-conv-body";

    // Top Line: Nome + Tempo relativo
    const topLine = document.createElement("div");
    topLine.className = "inbox-conv-top-line";

    const nameEl = document.createElement("span");
    nameEl.className = "inbox-conv-name";
    nameEl.textContent = t.phone_number || "Cliente";

    const timeEl = document.createElement("span");
    timeEl.className = "inbox-conv-time";
    timeEl.textContent = formatRelativeTime(t.last_message_at || t.created_at);

    topLine.appendChild(nameEl);
    topLine.appendChild(timeEl);

    // Meta Line: Canale + Stato
    const metaLine = document.createElement("div");
    metaLine.className = "inbox-conv-meta-line";

    const isIg = (t.canale || "").toLowerCase() === "instagram";
    const channelIcon = document.createElement("span");
    channelIcon.className = `conv-channel-icon ${isIg ? "icon-ig" : "icon-wa"}`;
    channelIcon.innerHTML = isIg
      ? '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="18" height="18" rx="5" stroke="#E1306C" stroke-width="2"/><circle cx="12" cy="12" r="4" stroke="#E1306C" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1" fill="#E1306C"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none"><path d="M12 21a9 9 0 1 0-4.5-1.2L3 21l1.2-4.5A9 9 0 0 0 12 21Z" stroke="#25D366" stroke-width="2" stroke-linejoin="round"/></svg>';

    const channelName = document.createElement("span");
    channelName.textContent = isIg ? "Instagram" : "WhatsApp";

    const sep = document.createElement("span");
    sep.className = "conv-meta-sep";
    sep.textContent = "·";

    const statusPill = document.createElement("span");
    statusPill.className = `conv-status-pill status-${(t.ticket_status || "").toLowerCase()}`;

    let statusText = TICKET_STATUS_LABEL[t.ticket_status] || t.ticket_status;
    let statusIcon = "";
    if (t.ticket_status === "AI_ACTIVE") {
      statusIcon = '<svg viewBox="0 0 24 24" fill="none" width="13" height="13"><rect x="3" y="6" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.8"/><circle cx="8.5" cy="12" r="1.5" fill="currentColor"/><circle cx="15.5" cy="12" r="1.5" fill="currentColor"/><path d="M12 2v4" stroke="currentColor" stroke-width="1.8"/></svg>';
    } else if (t.ticket_status === "PENDING_STAFF") {
      statusIcon = '<span class="inbox-dot-red"></span>';
    } else if (t.ticket_status === "CLAIMED") {
      statusIcon = '<svg viewBox="0 0 24 24" fill="none" width="13" height="13"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="7" r="4" stroke="currentColor" stroke-width="1.8"/></svg>';
      if (t.assigned_nome) statusText = `Preso da ${t.assigned_nome}`;
    } else if (t.ticket_status === "RESOLVED") {
      statusIcon = '<svg viewBox="0 0 24 24" fill="none" width="13" height="13"><path d="M5 12l5 5L20 7" stroke="#0e8a38" stroke-width="2.2" stroke-linecap="round"/></svg>';
    }

    statusPill.innerHTML = `${statusIcon} <span>${statusText}</span>`;

    metaLine.appendChild(channelIcon);
    metaLine.appendChild(channelName);
    metaLine.appendChild(sep);
    metaLine.appendChild(statusPill);

    // Preview
    const previewEl = document.createElement("p");
    previewEl.className = "inbox-conv-preview";
    previewEl.textContent = t.last_message_preview || "(Nessun messaggio recente)";

    bodyEl.appendChild(topLine);
    bodyEl.appendChild(metaLine);
    bodyEl.appendChild(previewEl);

    row.appendChild(avatarEl);
    row.appendChild(bodyEl);

    row.addEventListener("click", () => {
      selezionaTicket(t.id);
      // Su mobile switcha a vista dettaglio
      if (window.innerWidth < 768) {
        document.querySelector(".inbox-view")?.classList.add("show-detail");
      }
    });

    container.appendChild(row);
  });
}

function selezionaTicket(ticketId) {
  inboxState.selectedTicketId = ticketId;

  // Evidenzia riga attiva
  document.querySelectorAll(".inbox-conv-row").forEach((row) => {
    row.classList.toggle("active", row.dataset.ticketId === ticketId);
  });

  caricaDettaglioTicket(ticketId);
}

function mostraPlaceholderDettaglio() {
  const emptyEl = document.getElementById("inbox-detail-empty");
  const contentEl = document.getElementById("inbox-detail-content");
  if (emptyEl) emptyEl.hidden = false;
  if (contentEl) contentEl.hidden = true;
}

function creaControlliFeedback(m) {
  const container = document.createElement("div");
  container.className = "thread-feedback";

  const upBtn = document.createElement("button");
  upBtn.type = "button";
  upBtn.className = "thread-feedback-btn";
  upBtn.innerHTML = `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg> <span>${m.feedback_staff_up || 0}</span>`;
  upBtn.title = "Risposta appropriata";

  const downBtn = document.createElement("button");
  downBtn.type = "button";
  downBtn.className = "thread-feedback-btn";
  downBtn.innerHTML = `<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg> <span>${m.feedback_staff_down || 0}</span>`;
  downBtn.title = "Risposta da migliorare";

  upBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const res = await apiFetch(`${API_BASE}/api/inbox/messages/${encodeURIComponent(m.id)}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "up" }),
      });
      if (res.ok) {
        upBtn.classList.add("selected");
        toast("Feedback registrato", "success");
      }
    } catch (err) {
      console.error(err);
    }
  });

  downBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const res = await apiFetch(`${API_BASE}/api/inbox/messages/${encodeURIComponent(m.id)}/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: "down" }),
      });
      if (res.ok) {
        downBtn.classList.add("selected");
        toast("Feedback registrato", "success");
      }
    } catch (err) {
      console.error(err);
    }
  });

  container.appendChild(upBtn);
  container.appendChild(downBtn);
  return container;
}

/* ---------- Dettaglio Conversazione & Thread ---------- */

function _renderMsgRow(m, ticket) {
  const row = document.createElement("div");
  const isInbound = m.direction === "inbound";
  row.className = `inbox-msg-row ${isInbound ? "inbound" : "outbound"}`;
  row.dataset.msgId = m.id;

  // Avatar
  const avatar = document.createElement("div");
  avatar.className = `inbox-msg-avatar ${!isInbound ? "melpis-avatar" : ""}`;
  if (isInbound) {
    const colors = _getAvatarColors(ticket.phone_number || ticket.id);
    avatar.style.backgroundColor = colors.bg;
    avatar.style.color = colors.text;
    avatar.textContent = _getAvatarInitial(ticket.phone_number || "Cliente");
  } else {
    avatar.innerHTML = '<img src="logo.webp" alt="Melpis" width="28" height="28" style="border-radius:6px; display:block;">';
  }

  // Bubble
  const bubble = document.createElement("div");
  bubble.className = "inbox-msg-bubble";

  // Autore per outbound
  if (!isInbound) {
    const author = document.createElement("span");
    author.className = "inbox-msg-author";
    author.textContent = m.handling_type === "ai_handled" ? "Melpis AI" : (ticket.assigned_nome || "Operatore");
    bubble.appendChild(author);
  }

  // Testo formattato con link cliccabili
  const textEl = document.createElement("div");
  textEl.className = "inbox-msg-text";
  textEl.innerHTML = formatMessageContent(m.content_text || `(messaggio ${m.message_type})`);
  bubble.appendChild(textEl);

  // Feedback staff per messaggi AI
  if (!isInbound && m.handling_type === "ai_handled") {
    bubble.appendChild(creaControlliFeedback(m));
  }

  // Meta / Timestamp
  const meta = document.createElement("div");
  meta.className = "inbox-msg-meta";
  const quando = formatInboxDate(m.created_at);
  const status = MESSAGE_STATUS_LABEL[m.status] || m.status;
  meta.textContent = isInbound ? quando : `${quando} · ${status}`;
  bubble.appendChild(meta);

  row.appendChild(avatar);
  row.appendChild(bubble);
  return row;
}

async function caricaDettaglioTicket(ticketId, silent = false) {
  const emptyEl = document.getElementById("inbox-detail-empty");
  const contentEl = document.getElementById("inbox-detail-content");
  if (!contentEl) return;

  const ticket = inboxState.tickets.find((t) => t.id === ticketId);
  if (!ticket) {
    mostraPlaceholderDettaglio();
    return;
  }

  if (emptyEl) emptyEl.hidden = true;
  contentEl.hidden = false;

  // 1. Header Dettaglio
  const nameEl = document.getElementById("inbox-detail-name");
  const phoneEl = document.getElementById("inbox-detail-phone");
  const avatarEl = document.getElementById("inbox-detail-avatar");
  const channelBadge = document.getElementById("inbox-detail-channel");
  const actionsEl = document.getElementById("inbox-detail-actions");

  if (nameEl) nameEl.textContent = ticket.phone_number || "Cliente";
  if (phoneEl) phoneEl.textContent = ticket.phone_number || "";

  if (avatarEl) {
    const colors = _getAvatarColors(ticket.phone_number || ticket.id);
    avatarEl.style.backgroundColor = colors.bg;
    avatarEl.style.color = colors.text;
    avatarEl.textContent = _getAvatarInitial(ticket.phone_number || "Cliente");
  }

  const isIg = (ticket.canale || "").toLowerCase() === "instagram";
  if (channelBadge) {
    channelBadge.className = `inbox-channel-badge ${isIg ? "ig" : "wa"}`;
    channelBadge.innerHTML = isIg
      ? '<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><rect x="3" y="3" width="18" height="18" rx="5" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="2"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor"/></svg><span>Instagram</span>'
      : '<svg viewBox="0 0 24 24" fill="none" width="14" height="14"><path d="M12 21a9 9 0 1 0-4.5-1.2L3 21l1.2-4.5A9 9 0 0 0 12 21Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg><span>WhatsApp</span>';
  }

  // Pulsanti Azione (Claim / Resolve / Release / Assign)
  if (actionsEl && (!silent || actionsEl.dataset.ticketId !== ticket.id || actionsEl.dataset.ticketStatus !== ticket.ticket_status)) {
    actionsEl.dataset.ticketId = ticket.id;
    actionsEl.dataset.ticketStatus = ticket.ticket_status;
    actionsEl.innerHTML = "";

    // Assegna a (se team disponibile e ticket aperto)
    if (ticket.ticket_status !== "RESOLVED" && inboxState.team.length > 0) {
      const assignSel = document.createElement("select");
      assignSel.className = "inbox-action-select";
      const placeholderOpt = document.createElement("option");
      placeholderOpt.value = "";
      placeholderOpt.textContent = "Assegna a…";
      placeholderOpt.disabled = true;
      placeholderOpt.selected = !ticket.assigned_to;
      assignSel.appendChild(placeholderOpt);

      inboxState.team.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.user_id;
        opt.textContent = `${m.nome || m.email}${m.user_id === ticket.assigned_to ? " (assegnato)" : ""}`;
        if (m.user_id === ticket.assigned_to) opt.selected = true;
        assignSel.appendChild(opt);
      });

      assignSel.addEventListener("change", async () => {
        if (!assignSel.value) return;
        assignSel.disabled = true;
        try {
          const res = await apiFetch(`${API_BASE}/api/inbox/assign/${encodeURIComponent(ticket.id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ assigned_to: assignSel.value, expected_version: ticket.version }),
          });
          if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Impossibile assegnare.");
          }
          toast("Ticket assegnato con successo", "success");
          await caricaInbox();
        } catch (err) {
          assignSel.disabled = false;
          toast(err.message, "error");
        }
      });
      actionsEl.appendChild(assignSel);
    }

    // Tasto Claim
    if (ticket.ticket_status === "PENDING_STAFF" || ticket.ticket_status === "AI_ACTIVE") {
      const claimBtn = document.createElement("button");
      claimBtn.type = "button";
      claimBtn.className = "inbox-action-btn primary";
      claimBtn.textContent = "Prendi in carico";
      claimBtn.title = "Prendi in carico la conversazione per rispondere manualmente";
      claimBtn.addEventListener("click", async () => {
        claimBtn.disabled = true;
        claimBtn.textContent = "Carico…";
        try {
          const res = await apiFetch(`${API_BASE}/api/inbox/claim/${encodeURIComponent(ticket.id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_version: ticket.version }),
          });
          if (!res.ok) throw new Error("Impossibile fare il claim del ticket.");
          toast("Hai preso in carico la conversazione", "success");
          await caricaInbox();
        } catch (err) {
          toast(err.message, "error");
          claimBtn.disabled = false;
          claimBtn.textContent = "Prendi in carico";
        }
      });
      actionsEl.appendChild(claimBtn);
    }

    // Tasti Rilascia e Risolvi per CLAIMED
    if (ticket.ticket_status === "CLAIMED") {
      const releaseBtn = document.createElement("button");
      releaseBtn.type = "button";
      releaseBtn.className = "inbox-action-btn";
      releaseBtn.textContent = "Rilascia";
      releaseBtn.title = "Rilascia all'assistente AI o ad altri operatori";
      releaseBtn.addEventListener("click", async () => {
        releaseBtn.disabled = true;
        try {
          const res = await apiFetch(`${API_BASE}/api/inbox/release/${encodeURIComponent(ticket.id)}`, { method: "POST" });
          if (!res.ok) throw new Error("Impossibile rilasciare il ticket.");
          toast("Conversazione rilasciata", "info");
          await caricaInbox();
        } catch (err) {
          toast(err.message, "error");
          releaseBtn.disabled = false;
        }
      });
      actionsEl.appendChild(releaseBtn);

      const resolveBtn = document.createElement("button");
      resolveBtn.type = "button";
      resolveBtn.className = "inbox-action-btn primary";
      resolveBtn.textContent = "Risolvi";
      resolveBtn.title = "Segna la conversazione come risolta";
      resolveBtn.addEventListener("click", async () => {
        resolveBtn.disabled = true;
        try {
          const res = await apiFetch(`${API_BASE}/api/inbox/resolve/${encodeURIComponent(ticket.id)}`, { method: "POST" });
          if (!res.ok) throw new Error("Impossibile risolvere il ticket.");
          toast("Ticket segnato come risolto", "success");
          await caricaInbox();
        } catch (err) {
          toast(err.message, "error");
          resolveBtn.disabled = false;
        }
      });
      actionsEl.appendChild(resolveBtn);
    }
  }

  // 2. Banner di Stato Discreto (AI / Richiesta Staff)
  const statusStrip = document.getElementById("inbox-status-strip");
  const aiBadge = document.getElementById("inbox-ai-badge");
  const aiBadgeText = document.getElementById("inbox-ai-badge-text");

  if (statusStrip && aiBadge && aiBadgeText) {
    statusStrip.className = "inbox-status-strip";
    if (ticket.ticket_status === "AI_ACTIVE") {
      statusStrip.hidden = false;
      aiBadge.innerHTML = '<svg viewBox="0 0 24 24" fill="none" width="16" height="16"><rect x="3" y="6" width="18" height="14" rx="3" stroke="currentColor" stroke-width="1.8"/><circle cx="8.5" cy="12" r="1.5" fill="currentColor"/><circle cx="15.5" cy="12" r="1.5" fill="currentColor"/><path d="M12 2v4" stroke="currentColor" stroke-width="1.8"/></svg><span>L\'assistente sta gestendo la conversazione</span>';
    } else if (ticket.ticket_status === "PENDING_STAFF") {
      statusStrip.hidden = false;
      statusStrip.classList.add("pending");
      aiBadge.innerHTML = '<span class="inbox-dot-red"></span><span>Questa conversazione richiede l\'intervento di un operatore.</span>';
    } else if (ticket.ticket_status === "CLAIMED") {
      statusStrip.hidden = false;
      const assignedLabel = ticket.assigned_nome ? `In gestione da ${ticket.assigned_nome}` : "In gestione da te";
      aiBadge.innerHTML = `<svg viewBox="0 0 24 24" fill="none" width="16" height="16"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="7" r="4" stroke="currentColor" stroke-width="1.8"/></svg><span>${assignedLabel}</span>`;
    } else {
      statusStrip.hidden = false;
      aiBadge.innerHTML = '<svg viewBox="0 0 24 24" fill="none" width="16" height="16"><path d="M5 12l5 5L20 7" stroke="#0e8a38" stroke-width="2.2" stroke-linecap="round"/></svg><span>Conversazione risolta</span>';
    }
  }

  // 3. Thread Messaggi (Zero-Flicker)
  const threadContainer = document.getElementById("inbox-thread-messages");
  if (threadContainer) {
    const isNewTicket = threadContainer.dataset.ticketId !== ticket.id;
    threadContainer.dataset.ticketId = ticket.id;

    if (!silent && isNewTicket) {
      threadContainer.innerHTML = _skeletonList(3);
    }

    try {
      const res = await apiFetch(`${API_BASE}/api/inbox/tickets/${encodeURIComponent(ticket.id)}/messages?limit=200`);
      if (!res.ok) throw new Error("Errore recupero messaggi");
      const msgData = await res.json();
      const messages = msgData.messages || [];

      const renderedMsgRows = threadContainer.querySelectorAll(".inbox-msg-row[data-msg-id]");
      const renderedIds = Array.from(renderedMsgRows).map((r) => r.dataset.msgId);
      const newIds = messages.map((m) => String(m.id));

      const isSameList =
        !isNewTicket &&
        renderedIds.length === newIds.length &&
        renderedIds.every((id, idx) => id === newIds[idx]);

      if (isSameList && renderedIds.length > 0) {
        // Aggiorna solo stato metadati in-place
        messages.forEach((m) => {
          const row = threadContainer.querySelector(`.inbox-msg-row[data-msg-id="${m.id}"]`);
          if (row) {
            const meta = row.querySelector(".inbox-msg-meta");
            if (meta) {
              const isInbound = m.direction === "inbound";
              const quando = formatInboxDate(m.created_at);
              const status = MESSAGE_STATUS_LABEL[m.status] || m.status;
              const expectedText = isInbound ? quando : `${quando} · ${status}`;
              if (meta.textContent !== expectedText) {
                meta.textContent = expectedText;
              }
            }
          }
        });
      } else {
        const isNearBottom =
          threadContainer.scrollHeight - threadContainer.scrollTop - threadContainer.clientHeight < 150;

        threadContainer.innerHTML = "";
        if (!messages.length) {
          threadContainer.innerHTML = '<p class="inbox-empty" style="text-align:center; padding:30px 0;">Nessun messaggio in questa conversazione.</p>';
        } else {
          messages.forEach((m) => {
            const row = _renderMsgRow(m, ticket);
            threadContainer.appendChild(row);
          });
        }

        const scrollToBottom = () => {
          if (threadContainer) {
            threadContainer.scrollTop = threadContainer.scrollHeight;
          }
        };

        if (isNearBottom || isNewTicket || !silent) {
          scrollToBottom();
          requestAnimationFrame(scrollToBottom);
          setTimeout(scrollToBottom, 40);
          setTimeout(scrollToBottom, 120);
        }
      }
    } catch (err) {
      console.error("Errore caricamento thread:", err);
      if (!silent) {
        threadContainer.innerHTML = '<p class="inbox-empty error" style="text-align:center; padding:20px;">Impossibile caricare lo storico dei messaggi.</p>';
      }
    }
  }

  // 4. Input Box Risposta
  const replyForm = document.getElementById("inbox-reply-form");
  const disabledBanner = document.getElementById("inbox-reply-disabled-banner");
  const claimInlineBtn = document.getElementById("inbox-claim-inline-btn");
  const msgInput = document.getElementById("inbox-message-input");
  const sendBtn = document.getElementById("inbox-send-btn");

  if (ticket.ticket_status === "CLAIMED") {
    if (replyForm) replyForm.hidden = false;
    if (disabledBanner) disabledBanner.hidden = true;
    if (msgInput) {
      msgInput.disabled = false;
      msgInput.placeholder = `Scrivi un messaggio su ${isIg ? "Instagram" : "WhatsApp"}…`;
      if (!silent) msgInput.focus();
    }
    if (sendBtn) sendBtn.disabled = false;
  } else {
    if (replyForm) replyForm.hidden = true;
    if (disabledBanner) disabledBanner.hidden = false;
    const disabledText = document.getElementById("inbox-reply-disabled-text");
    if (disabledText) {
      disabledText.textContent = ticket.ticket_status === "RESOLVED"
        ? "Questa conversazione è risolta."
        : "Per rispondere manualmente, prendi prima in carico la conversazione.";
    }
    if (claimInlineBtn) {
      claimInlineBtn.style.display = ticket.ticket_status === "RESOLVED" ? "none" : "inline-block";
      claimInlineBtn.onclick = async () => {
        try {
          const res = await apiFetch(`${API_BASE}/api/inbox/claim/${encodeURIComponent(ticket.id)}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_version: ticket.version }),
          });
          if (!res.ok) throw new Error("Impossibile fare il claim.");
          toast("Preso in carico", "success");
          await caricaInbox();
        } catch (e) {
          toast(e.message, "error");
        }
      };
    }
  }
}

/* ---------- Invio Risposta Manuale ---------- */

async function inviaRispostaInbox() {
  if (!inboxState.selectedTicketId) return;
  const ticket = inboxState.tickets.find((t) => t.id === inboxState.selectedTicketId);
  if (!ticket || ticket.ticket_status !== "CLAIMED") return;

  const msgInput = document.getElementById("inbox-message-input");
  const sendBtn = document.getElementById("inbox-send-btn");
  if (!msgInput) return;

  const content = msgInput.value.trim();
  if (!content) return;

  if (sendBtn) sendBtn.disabled = true;
  msgInput.disabled = true;

  try {
    const idempotencyKey = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    const res = await apiFetch(`${API_BASE}/api/inbox/reply/${encodeURIComponent(ticket.id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        message_type: "text",
        idempotency_key: idempotencyKey,
      }),
    });

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Invio risposta fallito.");
    }

    msgInput.value = "";
    toast("Messaggio inviato", "success");
    await caricaDettaglioTicket(ticket.id);
    await caricaInbox();
  } catch (err) {
    console.error("Errore invio messaggio:", err);
    toast(err.message, "error");
  } finally {
    if (sendBtn) sendBtn.disabled = false;
    if (msgInput) {
      msgInput.disabled = false;
      msgInput.focus();
    }
  }
}

/* ---------- Setup Event Listeners Inbox ---------- */

function inizializzaEventiInbox() {
  // 1. Filtri Principali (Colonna 1)
  document.querySelectorAll("[data-inbox-main-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      inboxState.mainFilter = btn.dataset.inboxMainFilter;
      document.querySelectorAll("[data-inbox-main-filter]").forEach((b) => b.classList.toggle("active", b === btn));

      // Aggiorna label mobile
      const activeLabel = document.getElementById("inbox-mobile-active-label");
      if (activeLabel) activeLabel.textContent = btn.querySelector(".inbox-nav-text")?.textContent || "Filtri";

      // Chiudi drawer mobile/tablet se aperto
      document.getElementById("inbox-filters-panel")?.classList.remove("open");
      const backdrop = document.getElementById("inbox-filter-backdrop");
      if (backdrop) backdrop.hidden = true;

      renderInboxConversazioni();
    });
  });

  // 2. Quick Filters (Colonna 2 chips)
  document.querySelectorAll("[data-quick-filter]").forEach((chip) => {
    chip.addEventListener("click", () => {
      inboxState.quickFilter = chip.dataset.quickFilter;
      document.querySelectorAll("[data-quick-filter]").forEach((c) => c.classList.toggle("active", c === chip));
      renderInboxConversazioni();
    });
  });

  // 3. Form Invio Risposta
  const replyForm = document.getElementById("inbox-reply-form");
  if (replyForm) {
    replyForm.addEventListener("submit", (e) => {
      e.preventDefault();
      inviaRispostaInbox();
    });
  }

  const sendBtn = document.getElementById("inbox-send-btn");
  if (sendBtn) {
    sendBtn.addEventListener("click", (e) => {
      e.preventDefault();
      inviaRispostaInbox();
    });
  }

  const msgInput = document.getElementById("inbox-message-input");
  if (msgInput) {
    msgInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        inviaRispostaInbox();
      }
    });
  }

  // 4. Mobile Controls (Back button & Filter drawer toggle)
  const backBtn = document.getElementById("inbox-back-to-list");
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      document.querySelector(".inbox-view")?.classList.remove("show-detail");
    });
  }

  const filterToggle = document.getElementById("inbox-filter-toggle");
  const filterClose = document.getElementById("inbox-filters-close");
  const filterBackdrop = document.getElementById("inbox-filter-backdrop");
  const filterPanel = document.getElementById("inbox-filters-panel");

  if (filterToggle && filterPanel) {
    filterToggle.addEventListener("click", () => {
      filterPanel.classList.add("open");
      if (filterBackdrop) filterBackdrop.hidden = false;
    });
  }

  if (filterClose && filterPanel) {
    filterClose.addEventListener("click", () => {
      filterPanel.classList.remove("open");
      if (filterBackdrop) filterBackdrop.hidden = true;
    });
  }

  if (filterBackdrop && filterPanel) {
    filterBackdrop.addEventListener("click", () => {
      filterPanel.classList.remove("open");
      filterBackdrop.hidden = true;
    });
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", inizializzaEventiInbox);
} else {
  inizializzaEventiInbox();
}

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
   MENU MOBILE — sidebar off-canvas sotto 1100px
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

function chiudiMenuUtente() {
  chiudiSidebarAccountMenu();
}

document.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  if (!event.target.closest("#sidebar-account-btn") && !event.target.closest("#sidebar-account-popover")) {
    chiudiSidebarAccountMenu();
  }
  if (!event.target.closest(".notif-wrap")) chiudiPannelloNotifiche();
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  chiudiMenuMobile();
  chiudiSidebarAccountMenu();
  chiudiPannelloNotifiche();
});

/* ============================================================
   CENTRO NOTIFICHE — campana in topbar
   Aggrega i conteggi già calcolati in notificationItems
   (aggiornati ogni 30s da aggiornaNotifiche).
   ============================================================ */

const NOTIF_LABELS = {
  inbox: "Inbox",
  prenotazioni: "Prenotazioni",
  recensioni: "Recensioni",
  conoscenza: "Conoscenza",
};

const notifBell = document.getElementById("notif-bell");
const notifPanel = document.getElementById("notif-panel");
const notifList = document.getElementById("notif-list");
const bellBadge = document.getElementById("bell-badge");

function conteggioNonViste() {
  const stato = leggiStatoNotifiche();
  return Object.keys(NOTIF_LABELS).map((key) => {
    if (key === "prenotazioni") {
      // Nel pannello campana mostra sempre il count reale di in_attesa (azione richiesta)
      return { key, nonViste: Number(prenotazioniInAttesaCount || 0) };
    }
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
    p.textContent = "Tutto aggiornato: nessuna novità.";
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
  document.body.classList.add("authenticated");
  document.querySelectorAll(".app-shell").forEach((el) => {
    el.style.visibility = "";
  });
  if (sessionStorage.getItem("melpis_benvenuto")) {
    sessionStorage.removeItem("melpis_benvenuto");
    toast("Benvenuto in Melpis: il tuo periodo di prova è attivo.", "success");
  }
  if (typeof caricaProfiloImpostazioni === "function") {
    await caricaProfiloImpostazioni();
  }
  aggiornaRiepilogo();
  aggiornaPrioritari();
  avviaPanoramicaPolling();
  aggiornaReport();
  aggiornaConteggio();
  aggiornaNotifiche();
  aggiornaCampana();
  setInterval(aggiornaNotifiche, 30000);
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    mostraBannerRete("Connessione persa — i dati non si aggiornano. Controlla la rete.");
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
     Audit). DEBITO TECNICO NOTO: la lista è statica — se aggiungi un tab o
     una vista, aggiorna questa mappa (nessun modo automatico per rilevarlo). */
  const VAI_A = [
    { q: ["audit", "log", "registro", "storico azioni"], gruppo: "Gestione", titolo: "Audit", sub: "Impostazioni â€º Audit", view: "impostazioni", tab: "audit" },
    { q: ["integrazioni", "whatsapp", "instagram", "webhook", "collega", "canali"], gruppo: "Gestione", titolo: "Integrazioni", sub: "Impostazioni â€º Integrazioni", view: "impostazioni", tab: "integrazioni" },
    { q: ["fuso", "timezone", "password", "email account"], gruppo: "Gestione", titolo: "Impostazioni generali", sub: "Gestione â€º Generale", view: "impostazioni", tab: "generale" },
    { q: ["fattur", "abbonament", "piano", "rinnovo", "pagament", "upgrade", "downgrade", "cancellazion", "prezz"], gruppo: "Account", titolo: "Piano e abbonamento", sub: "Account", view: "account" },
    { q: ["menu", "conoscenza", "allergeni", "carta dei vini", "documenti", "pdf", "knowledge"], gruppo: "Assistente", titolo: "Conoscenza", sub: "Assistente › Conoscenza", view: "conoscenza" },
    { q: ["configurazione", "personalità", "regole", "tono", "lingue", "istruzioni", "identità", "orari", "escalation"], gruppo: "Assistente", titolo: "Configurazione AI", sub: "Assistente › Configurazione AI", view: "configurazione-ai" },
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
  const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function risolviTema(preferenza) {
    if (preferenza === "dark") return "dark";
    if (preferenza === "light") return "light";
    return mediaQuery.matches ? "dark" : "light";
  }

  function applica(preferenza) {
    const effettivo = risolviTema(preferenza);
    document.documentElement.dataset.theme = effettivo;

    const btns = document.querySelectorAll("#theme-segmented-control .theme-seg-btn");
    btns.forEach((btn) => {
      const val = btn.getAttribute("data-theme-val");
      const isActive = val === preferenza;
      btn.classList.toggle("active", isActive);
      btn.setAttribute("aria-checked", isActive ? "true" : "false");
    });
  }

  function impostaTema(nuovaPreferenza) {
    localStorage.setItem(KEY, nuovaPreferenza);
    applica(nuovaPreferenza);
  }

  const salvato = localStorage.getItem(KEY) || "system";
  applica(salvato);

  mediaQuery.addEventListener("change", () => {
    if ((localStorage.getItem(KEY) || "system") === "system") {
      applica("system");
    }
  });

  document.querySelectorAll("#theme-segmented-control .theme-seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = btn.getAttribute("data-theme-val");
      if (val) impostaTema(val);
    });
  });
})();

/* ============================================================
   IMPOSTAZIONI — fuso orario organizzazione
   ============================================================ */

let caricaTimezone;

(function inizializzaTimezone() {
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
    } catch { /* silenzioso: la vista riproverà al prossimo switch */ }
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

  caricaTimezone = carica;
})();

/* ============================================================
   CONFIGURAZIONE AI — Identità, Tono, Multilingua e Regole
   ============================================================ */

let caricaConfigurazioneAI;

(function inizializzaConfigurazioneAI() {
  const form = document.getElementById("ai-config-form");
  const saveBtn = document.getElementById("ai-cfg-save-btn");
  const saveStatus = document.getElementById("ai-cfg-save-status");

  const nomeInput = document.getElementById("ai-cfg-nome");
  const vertSelect = document.getElementById("ai-cfg-verticale");
  const descTextarea = document.getElementById("ai-cfg-descrizione");
  const orariTextarea = document.getElementById("ai-cfg-orari");

  const tonoSelect = document.getElementById("ai-cfg-tono-select");
  const tonoCustom = document.getElementById("ai-cfg-tono-custom");
  const defaultLinguaSelect = document.getElementById("ai-cfg-lingua-default");
  const addRuleInput = document.getElementById("ai-cfg-new-rule-input");
  const addRuleBtn = document.getElementById("ai-cfg-add-rule-btn");
  const rulesContainer = document.getElementById("ai-cfg-rules-list");

  let currentRules = [];

  const VERTICALI_VALIDI = ["ristorante", "parrucchiere", "hotel_bnb", "centro_estetico", "studio_medico_dentista"];

  const REGOLE_DEFAULT_BASE = [
    "Allergie gravi, intolleranze alimentari o requisiti medici specifici",
    "Lamentele, reclami formali o clienti insoddisfatti",
    "Richieste speciali fuori listino o non coperte dal menu/documenti",
    "Richieste di sconti personalizzati, convenzioni o accordi commerciali riservati",
  ];

  function renderRules() {
    if (!rulesContainer) return;
    rulesContainer.innerHTML = "";
    if (!currentRules.length) {
      rulesContainer.innerHTML = '<p class="settings-help-sm">Nessuna regola attiva. Aggiungine una con il campo sottostante.</p>';
      return;
    }
    currentRules.forEach((rule, idx) => {
      const item = document.createElement("div");
      item.className = "settings-rule-item";

      const label = document.createElement("label");
      label.className = "settings-rule-label";
      label.innerHTML = `<input type="checkbox" class="ai-cfg-rule-checkbox" data-rule-index="${idx}" checked> <span>${_sanitize(rule)}</span>`;

      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "settings-rule-remove-btn";
      delBtn.title = "Rimuovi questa regola";
      delBtn.innerHTML = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> <span>Elimina</span>';
      delBtn.addEventListener("click", () => {
        currentRules.splice(idx, 1);
        renderRules();
      });

      item.appendChild(label);
      item.appendChild(delBtn);
      rulesContainer.appendChild(item);
    });
  }

  function aggiornaSelectLinguaDefault(linguaScelta = null) {
    if (!defaultLinguaSelect) return;
    const currentVal = linguaScelta || defaultLinguaSelect.value || "it";
    const selezionate = ["it", ...Array.from(document.querySelectorAll(".ai-cfg-lang-opt:checked")).map((cb) => cb.value)];

    const LABELS = {
      it: "Italiano (it)",
      en: "English (en)",
      es: "Español (es)",
      fr: "Français (fr)",
      de: "Deutsch (de)",
    };

    defaultLinguaSelect.innerHTML = "";
    selezionate.forEach((code) => {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = LABELS[code] || code.toUpperCase();
      opt.selected = code === currentVal;
      defaultLinguaSelect.appendChild(opt);
    });

    if (!selezionate.includes(currentVal)) {
      defaultLinguaSelect.value = "it";
    }
  }

  document.querySelectorAll(".ai-cfg-lang-opt").forEach((cb) => {
    cb.addEventListener("change", () => aggiornaSelectLinguaDefault());
  });

  addRuleBtn?.addEventListener("click", () => {
    if (!addRuleInput) return;
    const text = addRuleInput.value.trim();
    if (!text) return;
    currentRules.push(text);
    addRuleInput.value = "";
    renderRules();
  });

  addRuleInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addRuleBtn?.click();
    }
  });

  async function carica() {
    try {
      const res = await apiFetch(`${API_BASE}/api/onboarding/profilo`);
      if (!res.ok) return;
      const data = await res.json();
      const prof = data.profilo || {};
      dbProfileRecord = prof;

      const businessName = prof.nome_attivita || "La tua attività";
      const bName = document.getElementById("business-name");
      if (bName) bName.textContent = businessName;
      const cName = document.getElementById("chat-business-name");
      if (cName) cName.textContent = businessName;

      // Identità
      if (nomeInput && prof.nome_attivita) nomeInput.value = prof.nome_attivita;
      if (vertSelect && VERTICALI_VALIDI.includes(prof.verticale)) vertSelect.value = prof.verticale;
      if (descTextarea && prof.descrizione) descTextarea.value = prof.descrizione;
      if (orariTextarea && prof.orari) {
        orariTextarea.value = prof.orari;
        const kbOrari = document.getElementById("kb-orari-input");
        if (kbOrari && !kbOrari.value) kbOrari.value = prof.orari;
      }

      // Tono
      if (tonoSelect && prof.tono) {
        const presets = ["professionale_caloroso", "informale_amichevole", "formale_elegante"];
        if (presets.includes(prof.tono)) {
          tonoSelect.value = prof.tono;
          if (tonoCustom) tonoCustom.value = "";
        } else {
          tonoSelect.value = "professionale_caloroso";
          if (tonoCustom) tonoCustom.value = prof.tono;
        }
      }

      // Multilingua
      const supportate = prof.lingue_supportate || ["it"];
      document.querySelectorAll(".ai-cfg-lang-opt").forEach((cb) => {
        cb.checked = supportate.includes(cb.value);
      });
      aggiornaSelectLinguaDefault(prof.lingua_default || "it");

      // Regole escalation
      if (Array.isArray(prof.regole_escalation) && prof.regole_escalation.length > 0) {
        currentRules = [...prof.regole_escalation];
      } else {
        currentRules = [...REGOLE_DEFAULT_BASE];
      }
      renderRules();
    } catch (err) {
      console.error("Impossibile caricare la configurazione AI:", err);
    }
  }

  function raccogliPayload() {
    const nome = (nomeInput?.value || "").trim() || dbProfileRecord?.nome_attivita || "La tua attività";
    const verticaleSelezionato = VERTICALI_VALIDI.includes(vertSelect?.value)
      ? vertSelect.value
      : (VERTICALI_VALIDI.includes(dbProfileRecord?.verticale) ? dbProfileRecord.verticale : "ristorante");
    const descrizione = (descTextarea?.value || "").trim();
    const orari = (orariTextarea?.value || "").trim() || dbProfileRecord?.orari || "Martedì - Domenica: 12:00-15:00 / 19:30-23:30";

    let tono = tonoSelect ? tonoSelect.value : (dbProfileRecord?.tono || "professionale_caloroso");
    if (tonoCustom && tonoCustom.value.trim()) {
      tono = tonoCustom.value.trim();
    }

    const lingueSelezionate = ["it", ...Array.from(document.querySelectorAll(".ai-cfg-lang-opt:checked")).map((cb) => cb.value)];
    const linguaDefault = defaultLinguaSelect?.value || "it";

    const regoleSelezionate = [];
    document.querySelectorAll(".ai-cfg-rule-checkbox").forEach((cb) => {
      if (cb.checked) {
        const idx = Number(cb.dataset.ruleIndex);
        if (currentRules[idx]) regoleSelezionate.push(currentRules[idx]);
      }
    });

    return {
      verticale: verticaleSelezionato,
      nome_attivita: nome,
      orari,
      descrizione,
      tono,
      servizi: Array.isArray(dbProfileRecord?.servizi) && dbProfileRecord.servizi.length ? dbProfileRecord.servizi : ["Servizio al tavolo", "Menu alla carta"],
      regole_escalation: regoleSelezionate.length ? regoleSelezionate : currentRules,
      whatsapp_collegato: Boolean(dbProfileRecord?.whatsapp_collegato),
      documenti_importati: Boolean(dbProfileRecord?.documenti_importati),
      lingue_supportate: lingueSelezionate,
      lingua_default: lingueSelezionate.includes(linguaDefault) ? linguaDefault : "it",
    };
  }

  async function eseguiSalvataggio() {
    if (saveBtn) saveBtn.disabled = true;
    if (saveStatus) { saveStatus.textContent = "Salvataggio in corso…"; saveStatus.style.color = ""; }

    try {
      const payload = raccogliPayload();
      const res = await apiFetch(`${API_BASE}/api/onboarding/profilo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (saveStatus) {
          saveStatus.textContent = err.detail || "Errore durante il salvataggio";
          saveStatus.style.color = "var(--red)";
        }
        return;
      }
      const data = await res.json();
      dbProfileRecord = data.profilo;

      if (payload.nome_attivita) {
        const bName = document.getElementById("business-name");
        if (bName) bName.textContent = payload.nome_attivita;
        const cName = document.getElementById("chat-business-name");
        if (cName) cName.textContent = payload.nome_attivita;
      }

      // Sincronizza campo orari anche nella Knowledge Base (Dati Struttura)
      const kbOrari = document.getElementById("kb-orari-input");
      if (kbOrari && payload.orari) {
        kbOrari.value = payload.orari;
      }

      if (saveStatus) securityStatus(saveStatus, "Configurazione AI salvata e sincronizzata!");
      toast("Configurazione AI salvata e sincronizzata con successo", "success");
    } catch {
      if (saveStatus) {
        saveStatus.textContent = "Errore di connessione con il server";
        saveStatus.style.color = "var(--red)";
      }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  form?.addEventListener("submit", (e) => {
    e.preventDefault();
    eseguiSalvataggio();
  });

  caricaConfigurazioneAI = carica;
})();

/* ============================================================
   AUDIT — registro attività
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
   INTEGRAZIONI — stato canali e webhook
   ============================================================ */

/* ============================================================
   INTEGRAZIONI — stato canali e test di connessione reale
   ============================================================ */

function _aggiornaBadgeStato(el, statoKey, customLabel) {
  if (!el) return;
  el.className = `integrazione-stato badge-status ${statoKey}`;
  const dot = '<span class="badge-status-dot"></span>';
  let label = customLabel;
  if (!label) {
    if (statoKey === "connected") label = "Connesso";
    else if (statoKey === "disconnected") label = "Non connesso";
    else if (statoKey === "expired_token") label = "Errore — Token scaduto";
    else if (statoKey === "pending" || statoKey === "pending_verification") label = "In attesa di verifica";
    else label = "Errore";
  }
  el.innerHTML = `${dot}<span class="badge-status-label">${_sanitize(label)}</span>`;
}

async function eseguiTestIntegrazione(canale, btn, feedbackEl) {
  if (!btn) return;
  const originalHtml = btn.innerHTML;
  btn.classList.add("loading");
  btn.innerHTML = `
    <svg viewBox="0 0 24 24" fill="none" width="15" height="15"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.19" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    Verifico…
  `;
  if (feedbackEl) feedbackEl.hidden = true;

  try {
    const res = await apiFetch(`${API_BASE}/api/integrazioni/test/${encodeURIComponent(canale)}`, {
      method: "POST",
    });
    const data = await res.json().catch(() => ({}));

    const badgeEl = document.getElementById(`integ-${canale === "calendar" ? "calendar" : canale}-stato`);
    if (badgeEl && data.status) {
      _aggiornaBadgeStato(badgeEl, data.status);
    }

    if (feedbackEl) {
      feedbackEl.hidden = false;
      feedbackEl.className = `integ-test-feedback ${data.success ? "success" : data.status === "expired_token" ? "error" : "warning"}`;
      feedbackEl.textContent = data.message || (data.success ? "Test completato con successo." : "Errore durante la verifica.");
    }

    if (data.success) {
      toast(data.message || "Connessione verificata con successo!", "success");
    } else {
      toast(data.message || "Verifica fallita: controlla le impostazioni.", "error");
    }
  } catch (err) {
    if (feedbackEl) {
      feedbackEl.hidden = false;
      feedbackEl.className = "integ-test-feedback error";
      feedbackEl.textContent = "Errore di rete o server non raggiungibile.";
    }
    toast("Impossibile eseguire il test di connessione.", "error");
  } finally {
    btn.classList.remove("loading");
    btn.innerHTML = originalHtml;
  }
}

/* ============================================================
   INTEGRAZIONI: WHATSAPP GUIDED SETUP, INSTAGRAM, CALENDAR
   ============================================================ */

function _setWaWizardStep(stepNum) {
  [1, 2, 3].forEach((s) => {
    const tab = document.getElementById(`wa-step-tab-${s}`);
    const panel = document.getElementById(`wa-wz-panel-${s}`);
    if (tab) {
      tab.classList.toggle("active", s === stepNum);
      tab.classList.toggle("done", s < stepNum);
    }
    if (panel) {
      panel.hidden = (s !== stepNum);
    }
  });
}

async function caricaStatoWhatsApp() {
  const connectedCard = document.getElementById("integ-whatsapp-connected-card");
  const wizardCard = document.getElementById("integ-whatsapp-wizard-card");
  const phoneDisplay = document.getElementById("integ-wa-phone-number-display");
  const connectedTitle = document.getElementById("integ-wa-connected-title");
  const connectedSub = document.getElementById("integ-wa-connected-sub");

  try {
    const res = await apiFetch(`${API_BASE}/api/whatsapp/settings`);
    if (!res.ok) return;
    const d = await res.json();

    if (d.connesso) {
      if (connectedCard) connectedCard.hidden = false;
      if (wizardCard) wizardCard.hidden = true;
      if (phoneDisplay) phoneDisplay.textContent = d.display_phone_number || d.phone_number_id || "Numero collegato";
      if (connectedTitle) connectedTitle.textContent = d.verified_name || "WhatsApp Business";
      if (connectedSub) connectedSub.textContent = "Connesso e pronto a rispondere";
    } else {
      if (connectedCard) connectedCard.hidden = true;
      if (wizardCard) wizardCard.hidden = false;
      _setWaWizardStep(1);
    }
  } catch (err) {
    console.warn("caricaStatoWhatsApp error:", err);
  }
}

async function caricaStatoInstagram() {
  const connectedCard = document.getElementById("integ-instagram-connected-card");
  const wizardCard = document.getElementById("integ-instagram-wizard-card");
  const igIdVal = document.getElementById("integ-ig-id");

  try {
    const res = await apiFetch(`${API_BASE}/api/instagram/account`);
    if (res.ok) {
      const d = await res.json();
      if (connectedCard) connectedCard.hidden = false;
      if (wizardCard) wizardCard.hidden = true;
      if (igIdVal) igIdVal.textContent = d.ig_user_id ? `@${d.ig_user_id}` : "Account collegato";
    } else {
      if (connectedCard) connectedCard.hidden = true;
      if (wizardCard) wizardCard.hidden = false;
    }
  } catch (err) {
    if (connectedCard) connectedCard.hidden = true;
    if (wizardCard) wizardCard.hidden = false;
  }
}

async function caricaIntegrazioni() {
  const status = document.getElementById("integrazioni-status");
  try {
    await Promise.allSettled([
      caricaStatoWhatsApp(),
      caricaStatoInstagram(),
      caricaStatoCalendar()
    ]);
  } catch (err) {
    if (status) { status.textContent = "Errore durante il caricamento integrazioni."; status.style.color = "var(--red)"; }
  }
}

// WhatsApp Wizard Event Listeners
document.getElementById("wa-wz-goto-step2")?.addEventListener("click", () => {
  _setWaWizardStep(2);
});

document.getElementById("wa-wz-back-step1")?.addEventListener("click", () => {
  _setWaWizardStep(1);
});

document.getElementById("wa-connect-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const phoneId = document.getElementById("wa-phone-number-id")?.value.trim();
  const wabaId = document.getElementById("wa-waba-id")?.value.trim();
  const token = document.getElementById("wa-access-token")?.value.trim();
  const statusEl = document.getElementById("wa-connect-status");
  const submitBtn = document.getElementById("wa-connect-submit");

  if (!phoneId || !wabaId || !token) {
    if (statusEl) {
      statusEl.textContent = "Compila tutti i campi obbligatori.";
      statusEl.className = "security-status err";
    }
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Verifica con Meta in corso…";
  }
  if (statusEl) {
    statusEl.textContent = "Verifica credenziali con Meta Cloud API…";
    statusEl.className = "security-status";
  }

  try {
    const res = await apiFetch(`${API_BASE}/api/whatsapp/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone_number_id: phoneId, waba_id: wabaId, access_token: token }),
    });
    const data = await res.json();
    if (res.ok) {
      if (statusEl) statusEl.textContent = "";
      toast(data.message || "WhatsApp collegato con successo!", "success");
      _setWaWizardStep(3);
    } else {
      if (statusEl) {
        statusEl.textContent = data.detail || "Errore durante la connessione con Meta.";
        statusEl.className = "security-status err";
      }
      toast(data.detail || "Verifica non riuscita", "error");
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = "Errore di connessione con il server.";
      statusEl.className = "security-status err";
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Verifica e Salva Collegamento";
    }
  }
});

document.getElementById("wa-wz-send-test-btn")?.addEventListener("click", async () => {
  const testPhone = document.getElementById("wa-wz-test-phone")?.value.trim();
  const statusEl = document.getElementById("wa-wz-test-status");
  const btn = document.getElementById("wa-wz-send-test-btn");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Invio in corso…";
  }
  if (statusEl) {
    statusEl.textContent = "Invio del messaggio di prova a Meta…";
    statusEl.className = "security-status";
  }

  try {
    const res = await apiFetch(`${API_BASE}/api/whatsapp/send-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_phone: testPhone || null }),
    });
    const data = await res.json();
    if (res.ok && data.success) {
      if (statusEl) {
        statusEl.textContent = data.message || "Messaggio di test inviato con successo!";
        statusEl.className = "security-status ok";
      }
      toast(data.message || "Messaggio inviato!", "success");
    } else {
      if (statusEl) {
        statusEl.textContent = data.message || data.detail || "Errore durante l'invio del messaggio di test.";
        statusEl.className = "security-status err";
      }
      toast(data.message || "Invio fallito", "error");
    }
  } catch {
    if (statusEl) {
      statusEl.textContent = "Errore di comunicazione col server.";
      statusEl.className = "security-status err";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Invia messaggio di test";
    }
  }
});

document.getElementById("wa-wz-finish-btn")?.addEventListener("click", async () => {
  await caricaStatoWhatsApp();
  toast("WhatsApp configurato e operativo!", "success");
});

// WhatsApp Connected Card Handlers
document.getElementById("integ-wa-open-test-btn")?.addEventListener("click", () => {
  const box = document.getElementById("integ-wa-test-box");
  if (box) box.hidden = !box.hidden;
});

document.getElementById("integ-wa-send-test-submit")?.addEventListener("click", async () => {
  const phone = document.getElementById("integ-wa-test-phone-input")?.value.trim();
  const feedback = document.getElementById("integ-wa-test-feedback");
  const btn = document.getElementById("integ-wa-send-test-submit");

  if (!phone) {
    if (feedback) {
      feedback.hidden = false;
      feedback.className = "integ-test-feedback error";
      feedback.textContent = "Inserisci un numero di cellulare per ricevere la prova.";
    }
    return;
  }

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Invio…";
  }

  try {
    const res = await apiFetch(`${API_BASE}/api/whatsapp/send-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_phone: phone }),
    });
    const d = await res.json();
    if (feedback) {
      feedback.hidden = false;
      feedback.className = `integ-test-feedback ${d.success ? "success" : "error"}`;
      feedback.textContent = d.message || (d.success ? "Messaggio inviato!" : "Errore durante l'invio.");
    }
    if (d.success) toast(d.message, "success");
  } catch {
    if (feedback) {
      feedback.hidden = false;
      feedback.className = "integ-test-feedback error";
      feedback.textContent = "Errore di connessione.";
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Invia prova";
    }
  }
});

document.getElementById("integ-wa-reconfig-btn")?.addEventListener("click", () => {
  const connectedCard = document.getElementById("integ-whatsapp-connected-card");
  const wizardCard = document.getElementById("integ-whatsapp-wizard-card");
  if (connectedCard) connectedCard.hidden = true;
  if (wizardCard) wizardCard.hidden = false;
  _setWaWizardStep(2);
});

document.getElementById("integ-wa-disconnect-btn")?.addEventListener("click", async () => {
  const ok = await confermaDestructiva({
    titolo: "Disconnettere WhatsApp Business?",
    descrizione: "L'assistente AI smetterà di rispondere automaticamente ai messaggi in arrivo su questo numero WhatsApp.",
    label: "Disconnetti WhatsApp",
  });
  if (!ok) return;

  try {
    const res = await apiFetch(`${API_BASE}/api/whatsapp/disconnect`, { method: "POST" });
    if (res.ok) {
      toast("WhatsApp disconnesso con successo.");
      await caricaStatoWhatsApp();
    } else {
      toast("Errore durante la disconnessione.", "error");
    }
  } catch {
    toast("Errore di rete.", "error");
  }
});

// Instagram Handlers
document.getElementById("ig-connect-form")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const igUserId = document.getElementById("ig-user-id-input")?.value.trim();
  const igToken = document.getElementById("ig-token-input")?.value.trim();
  const statusEl = document.getElementById("ig-connect-status");
  const submitBtn = document.getElementById("ig-connect-submit");

  if (!igUserId || !igToken) {
    if (statusEl) {
      statusEl.textContent = "Compila tutti i campi obbligatori.";
      statusEl.className = "security-status err";
    }
    return;
  }

  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = "Collegamento in corso…";
  }

  try {
    const res = await apiFetch(`${API_BASE}/api/instagram/account`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ig_user_id: igUserId, access_token: igToken }),
    });
    if (res.ok) {
      toast("Instagram Direct collegato con successo!", "success");
      await caricaStatoInstagram();
    } else {
      const err = await res.json();
      if (statusEl) {
        statusEl.textContent = err.detail || "Errore durante il collegamento di Instagram.";
        statusEl.className = "security-status err";
      }
    }
  } catch {
    if (statusEl) {
      statusEl.textContent = "Errore di connessione.";
      statusEl.className = "security-status err";
    }
  } finally {
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Collega Instagram Direct";
    }
  }
});

document.getElementById("integ-instagram-disconnect")?.addEventListener("click", async () => {
  const ok = await confermaDestructiva({
    titolo: "Disconnettere Instagram Direct?",
    descrizione: "L'assistente AI non risponderà più ai messaggi diretti su questo account Instagram.",
    label: "Disconnetti Instagram",
  });
  if (!ok) return;

  try {
    const res = await apiFetch(`${API_BASE}/api/instagram/account`, { method: "DELETE" });
    if (res.ok) {
      toast("Instagram Direct disconnesso con successo.");
      await caricaStatoInstagram();
    } else {
      toast("Errore durante la disconnessione.", "error");
    }
  } catch {
    toast("Errore di rete.", "error");
  }
});

document.querySelectorAll(".btn-test-conn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const canale = btn.dataset.canale;
    const feedbackEl = document.getElementById(`integ-${canale}-feedback`);
    eseguiTestIntegrazione(canale, btn, feedbackEl);
  });
});

/* ============================================================
   GOOGLE CALENDAR — stato, connect, disconnect
   ============================================================ */

async function caricaStatoCalendar() {
  const stato = document.getElementById("integ-calendar-stato");
  const sub = document.getElementById("integ-calendar-sub");
  const help = document.getElementById("integ-calendar-help");
  const calIdMeta = document.getElementById("integ-calendar-id");
  const syncModeMeta = document.getElementById("integ-calendar-sync-mode");
  const btnConnect = document.getElementById("integ-calendar-connect");
  const btnTest = document.getElementById("integ-calendar-test");
  const btnDisconnect = document.getElementById("integ-calendar-disconnect");

  if (!stato || !sub) return;

  try {
    const res = await apiFetch(`${API_BASE}/api/calendar/status`);
    if (!res.ok) {
      _aggiornaBadgeStato(stato, "error", "Errore");
      sub.textContent = "Impossibile verificare lo stato";
      return;
    }
    const d = await res.json();
    if (d.connected) {
      _aggiornaBadgeStato(stato, "connected", "Connesso");
      const calId = d.calendar_id || "Primary (Predefinito)";
      const sync = d.sync_enabled ? "Sincronizzazione attiva" : "Sincronizzazione in pausa";
      sub.textContent = `${calId} · ${sync}`;
      if (calIdMeta) calIdMeta.textContent = calId;
      if (syncModeMeta) syncModeMeta.textContent = d.sync_enabled ? "Bidirezionale automatica" : "In pausa";
      if (help) help.textContent = d.last_sync_at
        ? `Ultima sincronizzazione: ${new Date(d.last_sync_at).toLocaleString("it-IT")}`
        : "Sincronizzazione attiva: le prenotazioni confermate vengono sincronizzate con Google Calendar.";
      if (btnConnect) btnConnect.hidden = true;
      if (btnTest) btnTest.hidden = false;
      if (btnDisconnect) btnDisconnect.hidden = false;
    } else {
      _aggiornaBadgeStato(stato, "disconnected", "Non connesso");
      sub.textContent = "Nessun account Google collegato";
      if (calIdMeta) calIdMeta.textContent = "Nessun calendario";
      if (syncModeMeta) syncModeMeta.textContent = "Disattivata";
      if (btnConnect) btnConnect.hidden = false;
      if (btnTest) btnTest.hidden = true;
      if (btnDisconnect) btnDisconnect.hidden = true;
    }
  } catch {
    _aggiornaBadgeStato(stato, "error", "Errore");
    sub.textContent = "Errore di connessione";
  }
}

document.getElementById("integ-calendar-connect")?.addEventListener("click", () => {
  window.location.href = `${API_BASE}/api/calendar/auth`;
});

document.getElementById("integ-calendar-disconnect")?.addEventListener("click", async () => {
  const ok = await confermaDestructiva({
    titolo: "Disconnettere Google Calendar?",
    descrizione: "Le prenotazioni esistenti restano memorizzate in Melpis, ma non verranno più sincronizzate con Google Calendar.",
    label: "Disconnetti",
  });
  if (!ok) return;
  try {
    const res = await apiFetch(`${API_BASE}/api/calendar/disconnect`, { method: "DELETE" });
    if (res.ok) {
      toast("Google Calendar disconnesso con successo.");
      await caricaStatoCalendar();
    } else {
      toast("Errore durante la disconnessione.", "error");
    }
  } catch {
    toast("Errore di connessione.", "error");
  }
});

/* Gestione redirect OAuth callback */
(function gestisciCalendarRedirect() {
  const params = new URLSearchParams(window.location.search);
  const cal = params.get("calendar");
  if (cal === "connected") {
    const url = new URL(window.location);
    url.searchParams.delete("calendar");
    window.history.replaceState({}, "", url);
    const btn = document.querySelector('[data-view="impostazioni"]');
    if (btn) btn.click();
    setTimeout(() => {
      const tabBtn = document.querySelector('[data-settings-tab-btn="integrazioni"]');
      if (tabBtn) tabBtn.click();
    }, 100);
    setTimeout(() => toast("Google Calendar connesso con successo!", "success"), 400);
  } else if (cal === "error") {
    const reason = params.get("reason") || "errore_sconosciuto";
    const url = new URL(window.location);
    url.searchParams.delete("calendar");
    url.searchParams.delete("reason");
    window.history.replaceState({}, "", url);
    const btn = document.querySelector('[data-view="impostazioni"]');
    if (btn) btn.click();
    setTimeout(() => {
      const tabBtn = document.querySelector('[data-settings-tab-btn="integrazioni"]');
      if (tabBtn) tabBtn.click();
    }, 100);
    const msgs = {
      no_refresh_token: "Autorizzazione negata: la tua app Google non è in produzione. Aggiungi il tuo account come test user nella Google Cloud Console.",
      invalid_state: "Sessione scaduta: riprova la connessione.",
      invalid_nonce: "Sessione scaduta: riprova la connessione.",
      nonce_expired: "Timeout: la richiesta è scaduta, riprova.",
      missing_code: "Autorizzazione annullata.",
      server_error: "Errore del server: riprova più tardi.",
    };
    setTimeout(() => toast(msgs[reason] || `Errore: ${reason}`, "error"), 400);
  }
})();

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
