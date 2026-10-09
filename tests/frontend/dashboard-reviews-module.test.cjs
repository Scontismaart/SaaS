const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const { createDashboardHarness } = require("./helpers/dashboard-harness.cjs");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sharedSource = fs.readFileSync(path.join(root, "web/dashboard-shared.js"), "utf8");
const source = fs.readFileSync(path.join(root, "web/dashboard-reviews.js"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((yes) => { resolve = yes; });
  return { promise, resolve };
}

function response(status, body) {
  return { status, ok: status >= 200 && status < 300, async json() { return body; } };
}

function fixture(apiFetch) {
  const dom = new JSDOM(html, { url: "https://melpis.test/app/reviews", runScripts: "outside-only" });
  const { window } = dom;
  const scheduledTimers = [];
  let timerId = 0;
  window.setTimeout = (callback, delay) => { scheduledTimers.push({ callback, delay, id: ++timerId }); return timerId; };
  window.clearTimeout = () => {};
  window.HTMLElement.prototype.scrollIntoView = function scrollIntoView() {};
  const context = {
    userId: "user-1", sessionOrganizationId: "org-1", selectedOrganizationId: "org-1",
    view: "recensioni", transition: 1, epoch: 1,
  };
  const toasts = [];
  const requests = [];
  const trackedApiFetch = (url, options) => {
    const promise = apiFetch(url, options);
    requests.push({ url, options, promise });
    return promise;
  };
  window.eval(sharedSource);
  window.eval(source);
  const module = window.MelpisDashboardReviews.create({
    API_BASE: "", apiFetch: trackedApiFetch, _escapeHtml: window.MelpisDashboardShared.escapeHtml,
    _sanitize: window.MelpisDashboardShared.sanitize,
    toast: (...args) => toasts.push(args), _tDash: (_key, fallback) => fallback,
    localeCorrente: () => "it-IT", _emptyState(_icon, title, description = "") {
      const node = window.document.createElement("div"); node.className = "empty-state"; node.textContent = `${title} ${description}`; return node;
    },
    _errorState(message) { const node = window.document.createElement("div"); node.className = "error-state"; node.textContent = message; return node; },
    _skeletonList() { return "<div class='skeleton-list'>loading</div>"; },
    ICONS: { chat: "", alert: "", trend: "" }, getContext: () => ({ ...context }),
    getOverviewApi: () => ({ async aggiornaRiepilogo() {}, async aggiornaPrioritari() {} }),
    async aggiornaNotifiche() {},
  });
  module.onEnter();
  return { dom, window, document: window.document, context, module, toasts, requests, scheduledTimers };
}

async function settle() {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}

async function clickAndWait(h, selector) {
  h.document.querySelector(selector).click();
  await h.requests.at(-1)?.promise;
  await settle();
}

const review = {
  id: "review-1", testo: "Ottimo servizio", valutazione_stelle: 5, autore: "Cliente",
  fonte: "google", bozza_risposta: "Grazie per la visita", sentiment: "positiva",
  categoria: "servizio", stato: "bozza_generata", created_at: "2026-10-08T12:00:00Z",
};

test("review loader rejects stale responses after org change and route exit", async (t) => {
  const pending = deferred();
  const calls = [];
  const h = fixture((url) => { calls.push(url); return pending.promise; });
  t.after(() => h.dom.window.close());
  const loading = h.module.aggiornaRecensioni();
  const before = h.document.getElementById("review-history-list").innerHTML;
  h.context.selectedOrganizationId = "org-2";
  pending.resolve(response(200, { recensioni: [review] }));
  await loading;
  assert.deepEqual(calls, ["/api/recensioni?limit=50"]);
  assert.equal(h.document.getElementById("review-history-list").innerHTML, before);

  h.context.selectedOrganizationId = "org-1";
  const late = deferred();
  calls.length = 0;
  const again = h.module.aggiornaRecensioni();
  h.module.onExit();
  late.resolve(response(200, { recensioni: [review] }));
  await again;
  assert.deepEqual(calls, ["/api/recensioni?limit=50"]);
  assert.equal(h.document.querySelectorAll(".review-history-item").length, 0);
});

test("review fallback never crosses a 403 and both failed endpoints render an error", async (t) => {
  const calls = [];
  const h = fixture(async (url) => {
    calls.push(url);
    if (url.startsWith("/api/recensioni")) return response(403, { detail: "denied" });
    return response(200, { recensioni: [] });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  assert.deepEqual(calls, ["/api/recensioni?limit=50"]);
  assert.equal(h.document.querySelectorAll(".error-state").length, 1);
  assert.equal(h.document.querySelectorAll(".review-history-item").length, 0);

  calls.length = 0;
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  await h.module.aggiornaRecensioni();
  // This fixture still returns 403, which must remain a single-call denial.
  assert.deepEqual(calls, ["/api/recensioni?limit=50"]);
});

test("untrusted review fields render as text and cannot create executable markup", async (t) => {
  const hostile = {
    ...review, id: `review"><img src=x onerror=alert(1)>`,
    autore: `<img src=x onerror=alert(1)>`,
    testo: `<script>window.compromised=true</script>`,
    bozza_risposta: `<svg onload=alert(1)>`, categoria: `<img onerror=alert(1)>`,
    sentiment: `negativa"><img src=x onerror=alert(1)>`,
  };
  const h = fixture(async () => response(200, { recensioni: [hostile] }));
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  assert.equal(h.document.querySelectorAll("#review-history-list script, #review-history-list img, #review-history-list svg[onload]").length, 0);
  assert.equal(h.document.querySelector("#review-history-list [onerror], #review-history-list [onload]"), null);
  assert.equal(h.window.compromised, undefined);
});

test("review authentication failures never fall back to the dashboard endpoint", async (t) => {
  for (const status of [401, 403]) {
    const calls = [];
    const h = fixture(async (url) => {
      calls.push(url);
      return response(status, { detail: "denied" });
    });
    await h.module.aggiornaRecensioni();
    assert.deepEqual(calls, ["/api/recensioni?limit=50"]);
    assert.equal(h.document.querySelectorAll(".error-state").length, 1);
    h.dom.window.close();
  }
});

test("authorization failure clears an open review draft and disables approval", async (t) => {
  let listCalls = 0;
  let approvalCalls = 0;
  const h = fixture(async (url) => {
    if (url.startsWith("/api/recensioni?")) {
      listCalls += 1;
      return listCalls === 1
        ? response(200, { recensioni: [review] })
        : response(403, { detail: "organization denied" });
    }
    approvalCalls += 1;
    return response(200, { stato: "approvata" });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  await clickAndWait(h, '[data-action="open"]');
  assert.equal(h.document.getElementById("review-draft").hidden, false);
  await h.module.aggiornaRecensioni();
  assert.equal(h.document.getElementById("review-draft").hidden, true);
  assert.equal(h.document.getElementById("review-draft-text").value, "");
  assert.equal(h.document.getElementById("review-approve").disabled, true);
  h.document.getElementById("review-approve").click();
  await settle();
  assert.equal(approvalCalls, 0);
});

test("non-auth review endpoint failures use the dashboard fallback, then fail closed", async (t) => {
  const calls = [];
  const h = fixture(async (url) => {
    calls.push(url);
    return response(500, { detail: "offline" });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  assert.deepEqual(calls, ["/api/recensioni?limit=50", "/api/dashboard"]);
  assert.equal(h.document.querySelectorAll(".error-state").length, 1);
  assert.equal(h.document.querySelectorAll(".review-history-item").length, 0);
});

test("ordinary refresh failure preserves the open draft and unsaved response text", async (t) => {
  let listCalls = 0;
  const h = fixture(async (url) => {
    if (url.startsWith("/api/recensioni?") && ++listCalls === 1) return response(200, { recensioni: [review] });
    return response(500, { detail: "offline" });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  h.module.apriDettaglioRecensione(review.id);
  h.document.getElementById("review-draft-text").value = "Risposta non salvata";
  const metrics = h.document.getElementById("review-header-stats").textContent;
  const trends = h.document.getElementById("trend-list").innerHTML;
  await h.module.aggiornaRecensioni();
  assert.equal(h.document.getElementById("review-draft").hidden, false);
  assert.equal(h.document.getElementById("review-draft-text").value, "Risposta non salvata");
  assert.equal(h.document.getElementById("review-approve").disabled, false);
  assert.equal(h.document.getElementById("review-header-stats").textContent, metrics);
  assert.equal(h.document.getElementById("trend-list").innerHTML, trends);
  assert.ok(h.document.querySelector("#review-history-list .error-state"));
});

test("Settings refresh keeps the existing Reviews refresh callback available", async (t) => {
  const calls = [];
  const h = fixture(async (url) => {
    calls.push(url);
    return response(200, { recensioni: [review] });
  });
  t.after(() => h.dom.window.close());
  h.module.onExit();
  h.context.view = "impostazioni";
  h.context.transition += 1;
  await h.module.aggiornaRecensioni();
  assert.deepEqual(calls, ["/api/recensioni?limit=50"]);
  assert.equal(h.document.querySelectorAll(".review-history-item").length, 1);
});

test("review approval is single-flight, accepts success, and reports a denied approval", async (t) => {
  let mutationCalls = 0;
  const h = fixture(async (url) => {
    if (url.startsWith("/api/recensioni?")) return response(200, { recensioni: [review] });
    mutationCalls += 1;
    return response(200, { stato: "approvata" });
  });
  t.after(() => h.dom.window.close());
  const idleAnalyzeHtml = h.document.getElementById("review-analyze").innerHTML;
  const idleApproveHtml = h.document.getElementById("review-approve").innerHTML;
  h.module.onExit();
  assert.equal(h.document.getElementById("review-analyze").innerHTML, idleAnalyzeHtml);
  assert.equal(h.document.getElementById("review-approve").innerHTML, idleApproveHtml);
  h.context.transition += 1;
  h.module.onEnter();
  await h.module.aggiornaRecensioni();
  await clickAndWait(h, '[data-action="open"]');
  const approve = h.document.getElementById("review-approve");
  approve.click();
  approve.click();
  await h.requests.at(-1).promise;
  await settle();
  assert.equal(mutationCalls, 1);
  assert.equal(h.document.getElementById("draft-status-badge").textContent, "Approvata");

  const denied = fixture(async (url) => {
    if (url.startsWith("/api/recensioni?")) return response(200, { recensioni: [review] });
    return response(403, { detail: "forbidden" });
  });
  await denied.module.aggiornaRecensioni();
  await clickAndWait(denied, '[data-action="open"]');
  await clickAndWait(denied, "#review-approve");
  assert.equal(denied.toasts.at(-1)[1], "error");
  assert.equal(denied.document.getElementById("draft-status-badge").textContent, "Bozza pronta");
  denied.dom.window.close();
});

test("approval lock survives route exit while transient controls recover without stale success UI", async (t) => {
  const pending = deferred();
  let mutationCalls = 0;
  const h = fixture(async (url) => {
    if (url.startsWith("/api/recensioni?")) return response(200, { recensioni: [review] });
    mutationCalls += 1;
    return mutationCalls === 1 ? pending.promise : response(200, { stato: "approvata" });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  await clickAndWait(h, '[data-action="open"]');
  const approve = h.document.getElementById("review-approve");
  approve.click();
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  assert.equal(h.document.getElementById("review-approve").disabled, false);
  h.document.getElementById("review-approve").click();
  assert.equal(mutationCalls, 1, "the pending side effect stays single-flight across route transitions");

  pending.resolve(response(200, { stato: "approvata" }));
  await h.requests.at(-1).promise;
  await settle();
  assert.equal(h.document.getElementById("draft-status-badge").textContent, "Bozza pronta");
  assert.equal(h.toasts.length, 0, "the old context does not show a success toast");
  assert.equal(h.document.getElementById("review-approve").disabled, false);

  await clickAndWait(h, "#review-approve");
  assert.equal(mutationCalls, 2, "a fresh action is available after the prior request settles");
  assert.equal(h.document.getElementById("draft-status-badge").textContent, "Approvata");
});

test("late refresh completion after route exit does not schedule an orphan timer", async (t) => {
  const pending = deferred();
  let calls = 0;
  const h = fixture(() => (++calls === 1 ? Promise.resolve(response(200, { recensioni: [review] })) : pending.promise));
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  h.document.getElementById("btn-refresh-reviews").click();
  const refresh = h.requests.at(-1).promise;
  h.module.onExit();
  pending.resolve(response(200, { recensioni: [review] }));
  await refresh;
  await settle();
  assert.equal(h.scheduledTimers.length, 0);
  assert.equal(h.document.getElementById("btn-refresh-reviews").classList.contains("spin"), false);
});

test("stale approval after an organization switch does not commit UI or toast", async (t) => {
  const pending = deferred();
  const calls = [];
  const h = fixture((url) => {
    calls.push(url);
    if (url.startsWith("/api/recensioni?")) return Promise.resolve(response(200, { recensioni: [review] }));
    return pending.promise;
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  const approve = h.document.querySelector('[data-action="approve"]');
  approve.click();
  h.context.selectedOrganizationId = "org-2";
  pending.resolve(response(200, { stato: "approvata" }));
  await h.requests.at(-1).promise;
  await settle();
  assert.deepEqual(calls, ["/api/recensioni?limit=50", "/api/recensioni/review-1/approva"]);
  assert.equal(h.document.getElementById("draft-status-badge").textContent, "Bozza pronta");
  assert.equal(h.toasts.length, 0);
});

test("Reviews apiFetch keeps the selected organization and CSRF transport headers", async (t) => {
  const h = createDashboardHarness({
    url: "https://melpis.test/app/reviews",
    overrides: {
      "/api/recensioni": { recensioni: [review] },
      "POST /api/recensioni/review-1/approva": { stato: "approvata" },
    },
  });
  t.after(h.dispose);
  await h.ready();
  const request = h.requests.find((entry) => entry.pathname === "/api/recensioni");
  assert.ok(request, "the production Reviews module loads its list");
  assert.equal(request.options.headers["X-Organization-Id"], "org-1");
  assert.equal(request.options.headers["X-CSRF-Token"], undefined, "safe GETs do not send a CSRF token");
  assert.equal(request.options.credentials, "include");
  h.document.querySelector('[data-action="approve"]').click();
  await h.settle();
  const post = h.requests.find((entry) => entry.pathname === "/api/recensioni/review-1/approva");
  assert.ok(post, "the production Reviews action uses apiFetch");
  assert.equal(post.options.headers["X-Organization-Id"], "org-1");
  assert.equal(post.options.headers["X-CSRF-Token"], "csrf-test-token");
  assert.equal(post.options.credentials, "include");
});

test("Reviews listeners stay single-instance through repeated route entry", async (t) => {
  const h = createDashboardHarness();
  t.after(h.dispose);
  await h.ready();
  const targets = [
    [h.document.getElementById("review-analyze"), "click"],
    [h.document.getElementById("review-approve"), "click"],
    [h.document.getElementById("review-search-input"), "input"],
    [h.document.getElementById("review-filter-source"), "change"],
  ];
  const counts = targets.map(([target, type]) => h.listenerRegistrations.filter((listener) => listener.target === target && listener.type === type).length);
  for (let index = 0; index < 3; index += 1) {
    await h.navigate("recensioni");
    await h.navigate("inbox");
  }
  const repeatedCounts = targets.map(([target, type]) => h.listenerRegistrations.filter((listener) => listener.target === target && listener.type === type).length);
  assert.deepEqual(repeatedCounts, counts);
  assert.ok(counts.every((count) => count === 1));
});

test("destroyed Reviews module refuses new network work", async (t) => {
  const calls = [];
  const h = fixture(async (url) => { calls.push(url); return response(200, { recensioni: [] }); });
  t.after(() => h.dom.window.close());
  h.module.invalidate();
  await h.module.aggiornaRecensioni();
  h.document.querySelector('[data-action="approve"]')?.click();
  assert.deepEqual(calls, []);
});

test("Reviews preserves same-org form state but clears list and draft on scope change and logout", async (t) => {
  const h = fixture(async () => response(200, { recensioni: [review] }));
  t.after(() => h.dom.window.close());
  await h.module.aggiornaRecensioni();
  h.module.apriDettaglioRecensione(review.id);
  const before = h.document.getElementById("review-draft-text").value;
  h.module.onExit(); h.context.transition += 1; h.module.onEnter();
  assert.equal(h.document.getElementById("review-draft-text").value, before);
  h.module.onExit(); h.context.selectedOrganizationId = "org-2"; h.module.onEnter();
  assert.equal(h.document.getElementById("review-history-list").textContent, "");
  assert.equal(h.document.getElementById("review-draft-text").value, "");
  assert.equal(h.document.getElementById("review-draft").hidden, true);
  await h.module.aggiornaRecensioni();
  h.module.apriDettaglioRecensione(review.id);
  h.module.invalidate();
  assert.equal(h.document.getElementById("review-draft-text").value, "");
  assert.equal(h.document.getElementById("review-history-list").textContent, "");
});
