(function attachDashboardReviews(root, factory) {
  const api = factory(root);
  if (root) root.MelpisDashboardReviews = api;
})(typeof window !== "undefined" ? window : globalThis, function createDashboardReviews(root) {
  "use strict";

  return Object.freeze({
    create(deps) {
      const {
        API_BASE, apiFetch, _escapeHtml, _sanitize, toast, _tDash, localeCorrente,
        _emptyState, _errorState, _skeletonList, ICONS, getContext,
        getOverviewApi, aggiornaNotifiche,
      } = deps;
      const document = root.document;
      const navigator = root.navigator;
      let epoch = 0;
      let active = false;
      let destroyed = false;
      let entryScope = null;
      let analysisBusy = false;
      let approvalButtonBusy = false;
      const pendingTimers = new Set();
      const inFlightMutations = new Set();
      let listSequence = 0;
      function capture(view = "recensioni") {
        return { snapshot: getContext(), epoch, view };
      }
      function current(token) {
        const now = getContext();
        const validView = token.view === "recensioni" ? active : token.view === "impostazioni";
        return validView && !destroyed && epoch === token.epoch
          && now?.view === token.view && now?.userId && now?.sessionOrganizationId
          && JSON.stringify(now) === JSON.stringify(token.snapshot);
      }
      function guard(token) { return current(token); }
      function clearWork() {
        epoch += 1;
        for (const timer of pendingTimers) root.clearTimeout(timer);
        pendingTimers.clear();
        if (reviewAnalyze && analysisBusy) {
          reviewAnalyze.disabled = false;
          reviewAnalyze.innerHTML = initialReviewAnalyzeHtml;
        }
        if (reviewApprove && approvalButtonBusy) {
          const approved = reviewAttualeData?.stato === "approvata" || reviewAttualeData?.stato === "pubblicata";
          reviewApprove.disabled = Boolean(approved);
          reviewApprove.innerHTML = approved ? approvedReviewButtonHtml : initialReviewApproveHtml;
        }
        btnRefreshReviews?.classList.remove("spin");
      }
      function scopeKey() {
        const context = getContext();
        return JSON.stringify([context?.userId, context?.sessionOrganizationId, context?.selectedOrganizationId]);
      }
      function clearDetailData() {
        reviewAttualeId = null;
        reviewAttualeData = null;
        if (reviewApprove) reviewApprove.disabled = true;
        if (reviewDraft) reviewDraft.hidden = true;
        if (reviewDraftText) reviewDraftText.value = "";
        [reviewOriginalText, draftMetaInfo, draftFeedbackText, reviewDraftSentiment, reviewDraftCat]
          .forEach((node) => { if (node) node.textContent = ""; });
      }
      function clearScopeData() {
        clearDetailData();
        recensioniListaDati = [];
        recensioniPrimoCaricamento = true;
        recensioniFiltroCorrente = "tutte";
        [reviewText, reviewAuthor, reviewSearchInput, reviewFilterSource].forEach((node) => { if (node) node.value = ""; });
        reviewFilterTabs?.querySelectorAll(".review-tab").forEach((node) => node.classList.toggle("active", node.dataset.tab === "tutte"));
        reviewHistoryList?.replaceChildren();
        trendList?.replaceChildren();
        aggiornaConteggiRecensioni();
      }

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
const initialReviewAnalyzeHtml = reviewAnalyze?.innerHTML || "";
const initialReviewApproveHtml = reviewApprove?.innerHTML || "";
const approvedReviewButtonHtml = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Approvata';

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
  const timeStr = d.toLocaleTimeString(localeCorrente(), { hour: "2-digit", minute: "2-digit" });
  if (isOggi) return `Oggi alle ${timeStr}`;
  return d.toLocaleDateString(localeCorrente(), { day: "numeric", month: "short", year: "numeric" }) + `, ${timeStr}`;
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
  if (!guard(capture())) return;
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
  if (!guard(capture())) return;
  if (reviewDraft) reviewDraft.hidden = true;
  reviewAttualeId = null;
  reviewAttualeData = null;
}

async function inviaRecensione() {
  const token = capture();
  if (!guard(token) || inFlightMutations.has("analyze")) return;
  const testo = reviewText ? reviewText.value.trim() : "";
  if (!testo) {
    toast("Inserisci il testo della recensione da analizzare.", "warning");
    reviewText?.focus();
    return;
  }

  inFlightMutations.add("analyze");
  analysisBusy = true;
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
    if (!guard(token)) return;

    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      if (!guard(token)) return;
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }

    const data = await res.json();
    if (!guard(token)) return;
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
    if (!guard(token)) return;
    await getOverviewApi()?.aggiornaRiepilogo(true);
    if (!guard(token)) return;
    await getOverviewApi()?.aggiornaPrioritari(true);
    if (!guard(token)) return;
    await aggiornaNotifiche();
  } catch (err) {
    if (guard(token)) toast("Errore: " + err.message, "error");
  } finally {
    analysisBusy = false;
    inFlightMutations.delete("analyze");
    if (reviewAnalyze && guard(token)) {
      reviewAnalyze.disabled = false;
      reviewAnalyze.innerHTML = `
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
        Analizza e genera bozza
      `;
    }
  }
}

async function approvaRecensioneDaId(recId) {
  const token = capture();
  const mutationKey = `approve:${String(recId)}`;
  if (!recId || !guard(token) || inFlightMutations.has(mutationKey)) return;
  inFlightMutations.add(mutationKey);
  try {
    const res = await apiFetch(`${API_BASE}/api/recensioni/${recId}/approva`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!guard(token)) return;
    if (!res.ok) {
      const errBody = await res.json().catch(() => null);
      if (!guard(token)) return;
      throw new Error(errBody?.detail || `Errore HTTP ${res.status}`);
    }
    const data = await res.json();
    if (!guard(token)) return;

    // Aggiorna stato locale
    const approvedStatus = data.stato || "approvata";
    recensioniListaDati = recensioniListaDati.map((r) => {
      if (String(r.id) === String(recId)) {
        return { ...r, stato: approvedStatus };
      }
      return r;
    });

    if (String(reviewAttualeId) === String(recId)) {
      reviewAttualeData = { ...reviewAttualeData, stato: approvedStatus };
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
    await getOverviewApi()?.aggiornaRiepilogo(true);
    if (!guard(token)) return;
    await getOverviewApi()?.aggiornaPrioritari(true);
  } catch (err) {
    if (guard(token)) toast("Errore durante l'approvazione: " + err.message, "error");
  } finally {
    inFlightMutations.delete(mutationKey);
    if (guard(token) && String(reviewAttualeId) === String(recId)
      && reviewAttualeData?.stato !== "approvata" && reviewAttualeData?.stato !== "pubblicata" && reviewApprove) {
      reviewApprove.disabled = false;
      reviewApprove.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Approva risposta';
    }
  }
}

async function approvaRecensione() {
  if (!reviewAttualeId) return;
  if (inFlightMutations.has(`approve:${String(reviewAttualeId)}`)) return;
  if (reviewApprove) {
    approvalButtonBusy = true;
    reviewApprove.disabled = true;
    reviewApprove.textContent = "Approvazione…";
  }
  await approvaRecensioneDaId(reviewAttualeId);
  approvalButtonBusy = false;
}

function renderStoricoRecensioni(token = capture()) {
  if (!guard(token)) return;
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
        _tDash("reviews.runtime.empty_title", "Nessuna recensione registrata"),
        _tDash("reviews.runtime.empty_desc", "Incolla una recensione nel modulo in alto: l'AI valuterà il sentiment e preparerà una bozza di risposta professionale."),
        _tDash("reviews.runtime.empty_cta", "Incolla una recensione"),
        () => {
          reviewText?.focus();
          reviewText?.scrollIntoView({ behavior: "smooth" });
        }
      ));
    } else {
      reviewHistoryList.appendChild(_emptyState(
        ICONS.alert,
        _tDash("reviews.runtime.filtered_title", "Nessun risultato con i filtri attuali"),
        _tDash("reviews.runtime.filtered_desc", "Nessuna recensione corrisponde ai criteri di filtro o ricerca selezionati."),
        _tDash("reviews.runtime.reset_filters", "Reimposta filtri"),
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
    const rawSentiment = (r.sentiment || "neutro").toLowerCase();
    const sentimentStr = /^(positiva|positivo|negativa|negativo|neutro|neutral)$/.test(rawSentiment) ? rawSentiment : "neutro";

    let statusPill = "";
    if (isApprovata) {
      statusPill = `<span class="review-status-badge status-approvata">${_escapeHtml(_tDash("reviews.runtime.status_approved", "Approvata"))}</span>`;
    } else if (isUrgente) {
      statusPill = `<span class="review-status-badge status-urgente">${_escapeHtml(_tDash("reviews.runtime.status_urgent", "Richiede attenzione"))}</span>`;
    } else {
      statusPill = `<span class="review-status-badge">${_escapeHtml(_tDash("reviews.runtime.status_draft", "Bozza pronta"))}</span>`;
    }

    const sentimentBadge = `<span class="review-sentiment-badge sentiment-${sentimentStr}">${sentimentStr.charAt(0).toUpperCase() + sentimentStr.slice(1)}</span>`;
    const catBadge = r.categoria ? `<span class="review-cat-badge">${_sanitize(r.categoria.replace(/_/g, " "))}</span>` : "";

    let aiBox = "";
    if (r.bozza_risposta) {
      aiBox = `
        <div class="history-ai-reply-box">
          <span class="ai-reply-label">${_escapeHtml(_tDash("reviews.runtime.ai_reply_label", "Bozza di risposta suggerita:"))}</span>
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
          ${!isApprovata ? `<button type="button" class="btn-history-action btn-action-primary" data-action="approve" data-id="${_escapeHtml(String(r.id))}">${_escapeHtml(_tDash("reviews.approve_reply", "Approva risposta"))}</button>` : ""}
          <button type="button" class="btn-history-action" data-action="open" data-id="${_escapeHtml(String(r.id))}">${_escapeHtml(_tDash("reviews.runtime.review_draft", "Rivedi bozza"))}</button>
          ${r.bozza_risposta ? `<button type="button" class="btn-history-action" data-action="copy" data-id="${_escapeHtml(String(r.id))}">${_escapeHtml(_tDash("reviews.copy_text", "Copia testo"))}</button>` : ""}
        </div>
      </div>
    `;

    item.querySelector('[data-action="open"]')?.addEventListener("click", () => apriDettaglioRecensione(r.id));
    item.querySelector('[data-action="approve"]')?.addEventListener("click", () => approvaRecensioneDaId(r.id));
    item.querySelector('[data-action="copy"]')?.addEventListener("click", () => {
      if (guard(capture()) && r.bozza_risposta) {
        navigator.clipboard.writeText(r.bozza_risposta).catch(() => {});
        toast(_tDash("reviews.runtime.copied_toast", "Testo della bozza copiato negli appunti!"), "info");
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

  if (reviewStatCount) reviewStatCount.textContent = _tDash("reviews.runtime.review_count", "{{count}} recensioni", { count: totale });
  if (reviewStatRating) {
    reviewStatRating.innerHTML = `<svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor" aria-hidden="true"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg> <span>${mediaStelle ? mediaStelle.toFixed(1) : "0.0"}</span>`;
  }

  // Sidebar rating & sentiment
  if (sidebarRatingNum) sidebarRatingNum.textContent = mediaStelle ? mediaStelle.toFixed(1) : "--";
  if (sidebarRatingStars) sidebarRatingStars.textContent = _stelleVisual(Math.round(mediaStelle));
  if (sidebarRatingTotal) sidebarRatingTotal.textContent = _tDash("reviews.runtime.rating_total", "Basato su {{count}} recensioni", { count: totale });

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

function renderLoadError(token, denied = false) {
  if (!guard(token)) return;
  if (denied) {
    clearDetailData();
    recensioniListaDati = [];
    aggiornaConteggiRecensioni();
    if (trendList) trendList.replaceChildren();
  }
  if (reviewHistoryList) {
    reviewHistoryList.replaceChildren(_errorState("Impossibile caricare lo storico delle recensioni.", () => aggiornaRecensioni()));
  }
}

function _paroleChiave(testi, max = 3) {
  const stop = ["di", "il", "la", "le", "gli", "un", "una", "che", "per", "con", "non", "ho", "ha", "è", "e", "a", "o", "si", "in", "da", "lo", "sono", "mi", "ma", "ci", "ti", "al", "del", "della", "dei", "delle", "allo", "alla", "ai", "agli", "alle", "dal", "dalla", "dai", "dagli", "dalle", "nel", "nella", "nei", "negli", "nelle", "sul", "sulla", "sui", "sugli", "sulle", "molto", "tanto", "più", "meno", "era", "stato", "stata", "stati", "state", "essere", "questo", "quella", "quello", "conto", "fare", "fatto"];
  const words = testi.join(" ").toLowerCase().replace(/[^a-zàèéìòù\s]/g, "").split(/\s+/).filter(w => w.length > 3 && !stop.includes(w));
  const freq = {};
  words.forEach(w => { freq[w] = (freq[w] || 0) + 1; });
  return Object.entries(freq).sort((a,b) => b[1] - a[1]).slice(0, max).map(e => e[0]);
}

async function aggiornaRecensioni(silent = false) {
  const token = capture(getContext()?.view === "impostazioni" ? "impostazioni" : "recensioni");
  if (!guard(token)) return;
  const request = ++listSequence;
  const isCurrent = () => request === listSequence && guard(token);
  if (!silent && recensioniPrimoCaricamento && reviewHistoryList) {
    reviewHistoryList.innerHTML = _skeletonList(3);
    recensioniPrimoCaricamento = false;
  }

  try {
    // 1. Chiamata ad endpoint dedicato /api/recensioni
    const res = await apiFetch(`${API_BASE}/api/recensioni?limit=50`);
    if (!isCurrent()) return;
    if (res.ok) {
      const data = await res.json().catch(() => ({ recensioni: [] }));
      if (!isCurrent()) return;
      recensioniListaDati = Array.isArray(data.recensioni) ? data.recensioni : [];
    } else {
      if (res.status === 401 || res.status === 403 || res.mfaRequired) {
        if (isCurrent()) renderLoadError(token, true);
        return;
      }
      const dashRes = await apiFetch(`${API_BASE}/api/dashboard`);
      if (!isCurrent()) return;
      if (dashRes.ok) {
        const eventi = await dashRes.json().catch(() => []);
        if (!isCurrent()) return;
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
      } else {
        if (isCurrent()) renderLoadError(token, dashRes.status === 401 || dashRes.status === 403 || dashRes.mfaRequired);
        return;
      }
    }

    if (!isCurrent()) return;
    aggiornaConteggiRecensioni();
    renderStoricoRecensioni(token);
    await aggiornaTrends(recensioniListaDati, token);
  } catch (err) {
    if (!isCurrent()) return;
    console.error("Impossibile aggiornare le recensioni:", err);
    renderLoadError(token);
  }
}

async function aggiornaTrends(datiParam, token = capture()) {
  if (!guard(token)) return;
  if (!trendList) return;
  try {
    let recensioni = datiParam;
    if (!Array.isArray(recensioni)) {
      const res = await apiFetch(`${API_BASE}/api/dashboard`);
      if (!guard(token)) return;
      const eventi = res.ok ? await res.json().catch(() => []) : [];
      if (!guard(token)) return;
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
  if (!guard(capture())) return;
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
  if (!guard(capture())) return;
  btnRefreshReviews.classList.add("spin");
  const token = capture();
  aggiornaRecensioni().finally(() => {
    if (!guard(token)) return;
    const timer = root.setTimeout(() => {
      pendingTimers.delete(timer);
      if (guard(token)) btnRefreshReviews.classList.remove("spin");
    }, 500);
    pendingTimers.add(timer);
  });
});

reviewFilterTabs?.querySelectorAll(".review-tab").forEach((tabBtn) => {
  tabBtn.addEventListener("click", () => {
    if (!guard(capture())) return;
    reviewFilterTabs.querySelectorAll(".review-tab").forEach(t => t.classList.remove("active"));
    tabBtn.classList.add("active");
    recensioniFiltroCorrente = tabBtn.dataset.tab || "tutte";
    renderStoricoRecensioni();
  });
});

reviewSearchInput?.addEventListener("input", () => renderStoricoRecensioni());
reviewFilterSource?.addEventListener("change", () => renderStoricoRecensioni());



      return Object.freeze({
        onEnter() {
          const scope = scopeKey();
          if (entryScope !== null && scope !== entryScope) { clearWork(); clearScopeData(); }
          entryScope = scope;
          active = true;
        },
        onExit() { active = false; clearWork(); },
        invalidate() { active = false; destroyed = true; clearWork(); clearScopeData(); },
        aggiornaRecensioni, apriDettaglioRecensione,
      });
    },
  });
});
