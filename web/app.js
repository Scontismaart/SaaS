const API_BASE = "http://localhost:8000";
const PROFILO_ID = "trattoria_da_mario";

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
  panoramica: [],
  assistente: [],
  recensioni: [],
  prenotazioni: [],
  documenti: [],
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
    const viste = new Set(stato.viste?.[key] || []);
    const nonViste = (notificationItems[key] || []).filter((id) => !viste.has(id)).length;
    badge.textContent = nonViste > 99 ? "99+" : String(nonViste);
    badge.hidden = nonViste === 0;
  });
}

function segnaNotificheViste(viewName) {
  const stato = leggiStatoNotifiche();
  stato.viste = stato.viste || {};
  stato.viste[viewName] = [...(notificationItems[viewName] || [])];
  salvaStatoNotifiche(stato);
  aggiornaBadgeNotifiche(stato);
}

async function aggiornaNotifiche() {
  try {
    const [dashboardResponse, prenotazioniResponse, documentiResponse, reportResponse] = await Promise.all([
      fetch(`${API_BASE}/api/dashboard`),
      fetch(`${API_BASE}/api/bookings`),
      fetch(`${API_BASE}/api/documenti/elenco`),
      fetch(`${API_BASE}/api/report/stato`),
    ]);
    const eventi = dashboardResponse.ok ? await dashboardResponse.json() : [];
    const prenotazioni = prenotazioniResponse.ok ? await prenotazioniResponse.json() : [];
    const documenti = documentiResponse.ok ? (await documentiResponse.json()).documenti || [] : [];
    const report = reportResponse.ok ? await reportResponse.json() : { disponibile: false };
    notificationItems = {
      panoramica: eventi.map((evento) => evento.id),
      assistente: eventi.filter((evento) => evento.tipo_evento === "messaggio").map((evento) => evento.id),
      recensioni: eventi.filter((evento) => evento.tipo_evento === "recensione").map((evento) => evento.id),
      prenotazioni: prenotazioni.map((prenotazione) => prenotazione.id),
      documenti: documenti.map((documento) => documento.id),
      report: report.disponibile && report.id ? [report.id] : [],
    };
    const stato = leggiStatoNotifiche();
    if (!stato.inizializzato) {
      stato.inizializzato = true;
      Object.entries(notificationItems).forEach(([key, ids]) => { stato.viste[key] = ids; });
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
      assistente: "Assistente",
      recensioni: "Recensioni",
      prenotazioni: "Prenotazioni",
      report: "Report",
      documenti: "Documenti",
    };
    topbarTitle.textContent = titles[viewName] || viewName;

    if (viewName === "panoramica") {
      aggiornaRiepilogo();
      aggiornaPrioritari();
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
  });
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
    const res = await fetch(`${API_BASE}/api/messaggio?profilo_id=${PROFILO_ID}`, {
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
    const res = await fetch(`${API_BASE}/api/bookings`);
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
        title: `${ora} · ${p.nome_cliente || "Cliente"} · ${p.coperti || "?"} coperti`,
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
        <time class="booking-row-time">${ora || "--:--"}</time>
        <div class="booking-row-main"><strong>${p.nome_cliente || "Cliente"}</strong><span>${p.coperti || "?"} coperti${p.telefono ? ` · ${p.telefono}` : ""}</span></div>
        <span class="booking-row-status" style="--booking-color:${colorePrenotazione(p.stato)}">${p.stato || "In attesa"}</span>`;
      bookingDayList.appendChild(item);
    });
  };
  if (prenotazioni) {
    render(prenotazioni.filter((p) => p.data === data));
  } else {
    fetch(`${API_BASE}/api/bookings`).then((res) => res.json()).then((all) => render(all.filter((p) => p.data === data))).catch(() => render([]));
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
    const res = await fetch(`${API_BASE}/api/bookings/semaforo?data=${targetDate}`);
    if (!res.ok) return;
    const slots = await res.json();
    availabilityList.innerHTML = "";
    slots.forEach((slot) => {
      const item = document.createElement("div");
      item.classList.add("availability-item", `availability-${slot.stato}`);
      item.innerHTML = `
        <span class="availability-dot"></span>
        <span class="availability-hour">${slot.ora}</span>
        <span class="availability-seats">${slot.coperti_liberi}/${slot.coperti_massimi} liberi</span>
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
    const res = await fetch(`${API_BASE}/api/bookings/settings`);
    if (!res.ok) return;
    const data = await res.json();
    const capienze = data.capienze_orarie || {};
    bookingOpenHours = capienze;
    bookingSettingsGrid.innerHTML = (data.fasce_orarie || []).map((ora) => `
      <label class="booking-setting"><span>${ora}</span><input type="number" min="0" max="500" data-capacity-hour="${ora}" value="${capienze[ora] ?? 40}"></label>
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
    const res = await fetch(`${API_BASE}/api/bookings`, {
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
    const res = await fetch(`${API_BASE}/api/bookings/settings`, {
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
const reviewAnalyze = document.getElementById("review-analyze");
const reviewDraft = document.getElementById("review-draft");
const reviewDraftText = document.getElementById("review-draft-text");
const reviewDraftSentiment = document.getElementById("review-draft-sentiment");
const reviewDraftCat = document.getElementById("review-draft-cat");
const reviewCopy = document.getElementById("review-copy");

async function inviaRecensione() {
  const testo = reviewText.value.trim();
  if (!testo) return;
  reviewAnalyze.disabled = true;
  reviewAnalyze.textContent = "Analisi in corso\u2026";
  try {
    const res = await fetch(`${API_BASE}/api/recensione`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        testo,
        valutazione_stelle: reviewStars.value ? parseInt(reviewStars.value) : null,
        autore: reviewAuthor.value.trim(),
        fonte: "manuale",
      }),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }
    const data = await res.json();
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

const trendList = document.getElementById("trend-list");

function _paroleChiave(testi, max = 3) {
  const stop = ["di", "il", "la", "le", "gli", "un", "una", "che", "per", "con", "non", "ho", "ha", "è", "e", "a", "o", "si", "in", "da", "lo", "sono", "mi", "ma", "ci", "ti", "al", "del", "della", "dei", "delle", "allo", "alla", "ai", "agli", "alle", "dal", "dalla", "dai", "dagli", "dalle", "nel", "nella", "nei", "negli", "nelle", "sul", "sulla", "sui", "sugli", "sulle", "molto", "tanto", "più", "meno", "era", "stato", "stata", "stati", "state", "essere", "questo", "quella", "quello", "conto", "fare", "fatto"];
  const words = testi.join(" ").toLowerCase().replace(/[^a-zàèéìòù\s]/g, "").split(/\s+/).filter(w => w.length > 3 && !stop.includes(w));
  const freq = {};
  words.forEach(w => { freq[w] = (freq[w] || 0) + 1; });
  return Object.entries(freq).sort((a,b) => b[1] - a[1]).slice(0, max).map(e => e[0]);
}

async function aggiornaTrends() {
  try {
    const res = await fetch(`${API_BASE}/api/dashboard`);
    if (!res.ok) return;
    const eventi = await res.json();
    const recensioni = eventi.filter(e => e.tipo_evento === "recensione");
    const totale = recensioni.length;

    if (totale === 0) {
      trendList.innerHTML = `<li class="trend-item"><div class="trend-body"><span class="trend-label" style="color:var(--sidebar-text)">Nessuna recensione ancora — incollane una qui sopra.</span></div></li>`;
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
        <span class="trend-icon trend-pos">▲</span>
        <div class="trend-body">
          <span class="trend-label">Positivo (${pctPos}%)</span>
          <div class="trend-bar-track"><div class="trend-bar-fill fill-pos" style="width:${pctPos}%"></div></div>
        </div>
      </li>`);

    if (neg > 0) items.push(`
      <li class="trend-item">
        <span class="trend-icon trend-neg">▼</span>
        <div class="trend-body">
          <span class="trend-label">Negativo (${pctNeg}%)</span>
          <div class="trend-bar-track"><div class="trend-bar-fill fill-neg" style="width:${pctNeg}%"></div></div>
        </div>
      </li>`);

    if (neut > 0) items.push(`
      <li class="trend-item">
        <span class="trend-icon trend-neutral">—</span>
        <div class="trend-body"><span class="trend-label">Neutro (${pctNeut}%)</span></div>
      </li>`);

    topCat.forEach(([cat]) => {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-topic">↗</span>
          <div class="trend-body"><span class="trend-label">Argomento ricorrente: ${cat.replace(/_/g, " ")}</span></div>
        </li>`);
    });

    keywords.forEach(kw => {
      items.push(`
        <li class="trend-item">
          <span class="trend-icon trend-new">✦</span>
          <div class="trend-body"><span class="trend-label">Parola chiave: "${kw}"</span></div>
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
    const res = await fetch(url);
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
   PANORAMICA — KPI + priorità + attività
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
    const res = await fetch(`${API_BASE}/api/dashboard/prioritari`);
    if (!res.ok) return;
    const eventi = await res.json();
    priorityList.innerHTML = "";
    if (eventi.length === 0) {
      priorityList.innerHTML = `<li class="priority-empty">Niente da gestire — tutto sotto controllo.</li>`;
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
    const res = await fetch(`${API_BASE}/api/dashboard`);
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
const docIndicizzaBtn = document.getElementById("doc-indicizza-btn");
const docQuery = document.getElementById("doc-query");
const docChiediBtn = document.getElementById("doc-chiedi-btn");
const docRisposta = document.getElementById("doc-risposta");
const docRispostaText = document.getElementById("doc-risposta-text");
const docFonti = document.getElementById("doc-fonti");
const docFontiList = document.getElementById("doc-fonti-list");

const docEmailServer = document.getElementById("doc-email-server");
const docEmailIndirizzo = document.getElementById("doc-email-indirizzo");
const docEmailPassword = document.getElementById("doc-email-password");
const docEmailSalva = document.getElementById("doc-email-salva");
const docConfigStatus = document.getElementById("doc-config-status");

async function aggiornaConteggio() {
  try {
    const res = await fetch(`${API_BASE}/api/documenti/conteggio`);
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
    const res = await fetch(`${API_BASE}/api/documenti/elenco`);
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
          const response = await fetch(`${API_BASE}/api/documenti/${encodeURIComponent(documento.id)}`, { method: "DELETE" });
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

async function aggiornaConfigStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/email/config`);
    if (!res.ok) { docConfigStatus.textContent = ""; return; }
    const data = await res.json();
    if (data.configurazioni && data.configurazioni.length > 0) {
      docEmailIndirizzo.value = data.configurazioni[0].indirizzo;
      docEmailServer.value = data.configurazioni[0].imap_server;
      docConfigStatus.textContent = `Email configurata: ${data.configurazioni[0].indirizzo}`;
      docConfigStatus.style.color = "var(--sage)";
    } else {
      docConfigStatus.textContent = "Nessuna email configurata.";
      docConfigStatus.style.color = "var(--ink-soft)";
    }
  } catch {
    docConfigStatus.textContent = "";
  }
}

docEmailSalva?.addEventListener("click", async () => {
  const imap_server = docEmailServer.value.trim();
  const indirizzo = docEmailIndirizzo.value.trim();
  const app_password = docEmailPassword.value.trim();
  if (!imap_server || !indirizzo || !app_password) {
    docConfigStatus.textContent = "Compila tutti i campi.";
    docConfigStatus.style.color = "var(--red)";
    return;
  }
  docEmailSalva.disabled = true;
  docEmailSalva.textContent = "Salvataggio\u2026";
  try {
    const res = await fetch(`${API_BASE}/api/email/configura`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ imap_server, indirizzo, app_password, polling_minuti: 5 }),
    });
    if (!res.ok) throw new Error("Errore salvataggio");
    const data = await res.json();
    docConfigStatus.textContent = data.detail;
    docConfigStatus.style.color = "var(--sage)";
    docEmailPassword.value = "";
    await aggiornaConteggio();
  } catch {
    docConfigStatus.textContent = "Errore nel salvataggio.";
    docConfigStatus.style.color = "var(--red)";
  } finally {
    docEmailSalva.disabled = false;
    docEmailSalva.textContent = "Salva e attiva polling";
  }
});

docIndicizzaBtn?.addEventListener("click", async () => {
  docIndicizzaBtn.disabled = true;
  docIndicizzaBtn.textContent = "Controllo in corso\u2026";
  try {
    const res = await fetch(`${API_BASE}/api/email/check-now`, { method: "POST" });
    const data = await res.json();
    alert(data.detail);
    await aggiornaConteggio();
  } catch {
    alert("Errore durante il controllo email.");
  } finally {
    docIndicizzaBtn.disabled = false;
    docIndicizzaBtn.textContent = "Controlla email ora";
  }
});

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
    const res = await fetch(`${API_BASE}/api/documenti/reindicizza`, { method: "POST" });
    if (!res.ok) throw new Error("Errore avvio");
    const { task_id } = await res.json();

    const poll = setInterval(async () => {
      try {
        const res2 = await fetch(`${API_BASE}/api/documenti/reindicizza/stato/${task_id}`);
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
      res = await fetch(`${API_BASE}/api/documenti/carica-file`, { method: "POST", body: form });
    } else {
      res = await fetch(`${API_BASE}/api/documenti/carica`, {
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
    const res = await fetch(`${API_BASE}/api/documenti/chiedi`, {
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
        li.innerHTML = `<strong>${f.documento}</strong> <span class="doc-fonti-score">(score: ${f.score})</span><br><span class="doc-fonti-estratto">${f.estratto}</span>`;
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
   AVVIO
   ============================================================ */

aggiornaRiepilogo();
aggiornaPrioritari();
aggiornaReport();
aggiornaConteggio();
aggiornaNotifiche();
setInterval(aggiornaNotifiche, 30000);
if (document.getElementById("booking-date")) {
  document.getElementById("booking-date").value = oggiIso();
}
