const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const shared = fs.readFileSync(path.join(root, "web/dashboard-shared.js"), "utf8");
const dialogFocus = fs.readFileSync(path.join(root, "web/dialog-focus.js"), "utf8");
const source = fs.readFileSync(path.join(root, "web/dashboard-knowledge.js"), "utf8");

function deferred() {
  let resolve;
  const promise = new Promise((yes) => { resolve = yes; });
  return { promise, resolve };
}
function response(status, body) {
  return { status, ok: status >= 200 && status < 300, async json() { return body; } };
}
const emptySummary = { faq: {}, documenti: {}, web: {}, dati_struttura: {}, conflitti_totali: 0 };
const faq = { id: "faq-1", nome: "Orari", metadata: { domanda: "Orari?", risposta: "9–18" }, is_active: true };

function fixture(transport = async (url) => {
  if (url.endsWith("/summary")) return response(200, emptySummary);
  if (url.includes("/dati-struttura")) return response(200, { servizi: [], orari: "" });
  return response(200, { documenti: [] });
}, confirm = async () => true) {
  const dom = new JSDOM(html, { url: "https://melpis.test/app/knowledge", runScripts: "outside-only" });
  const { window } = dom;
  const context = { userId: "user-1", sessionOrganizationId: "org-1",
    selectedOrganizationId: "org-1", view: "conoscenza", transition: 1, epoch: 1 };
  const calls = [];
  window.eval(dialogFocus);
  window.eval(shared);
  window.eval(source);
  const module = window.MelpisDashboardKnowledge.create({
    API_BASE: "", apiFetch(url, options) {
      calls.push({ url, options });
      return transport(url, options);
    },
    _escapeHtml: window.MelpisDashboardShared.escapeHtml,
    _sanitize: window.MelpisDashboardShared.sanitize,
    _tDash: (_key, fallback) => fallback,
    localeCorrente: () => "it-IT",
    confermaDestructiva: confirm,
    getContext: () => ({ ...context }),
  });
  module.onEnter();
  return { dom, window, document: window.document, context, module, calls };
}
async function settle() {
  for (let i = 0; i < 100; i += 1) await Promise.resolve();
}

test("Knowledge renders FAQ, empty, error, and hostile names as inert text", async (t) => {
  let list = [faq];
  const h = fixture(async (url) => {
    if (url.endsWith("/summary")) return response(200, emptySummary);
    if (url.includes("tipo=faq")) return response(200, { documenti: list });
    return response(200, { documenti: [] });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaConoscenzaCompleta();
  assert.match(h.document.getElementById("kb-faq-list").textContent, /Orari\?/);
  list = [{ ...faq, nome: '<img src=x onerror=alert(1)>', metadata: {} }];
  await h.module.aggiornaConoscenzaCompleta();
  assert.equal(h.document.querySelector("#kb-faq-list img"), null);
  assert.match(h.document.getElementById("kb-faq-list").textContent, /<img/);
  list = [];
  await h.module.aggiornaConoscenzaCompleta();
  assert.match(h.document.getElementById("kb-faq-list").textContent, /Nessuna FAQ/);
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  const broken = fixture(async (url) => response(url.endsWith("/summary") ? 200 : 500, emptySummary));
  t.after(() => broken.dom.window.close());
  await broken.module.aggiornaConoscenzaCompleta();
  assert.match(broken.document.getElementById("kb-faq-list").textContent, /Errore nel caricamento/);
});

test("stale list and summary cannot render after organization or view change", async (t) => {
  const delayed = deferred();
  const h = fixture((url) => url.endsWith("/summary") ? delayed.promise : response(200, { documenti: [faq] }));
  t.after(() => h.dom.window.close());
  const pending = h.module.aggiornaConoscenzaCompleta();
  await settle();
  h.context.selectedOrganizationId = "org-2";
  h.module.onEnter();
  delayed.resolve(response(200, { ...emptySummary, faq: { totale: 9 } }));
  await pending;
  assert.equal(h.document.getElementById("kb-badge-faq").textContent, "");
  assert.equal(h.calls.length, 1);
  h.module.onExit();
  h.context.view = "panoramica";
  h.context.transition += 1;
  await h.module.aggiornaConoscenzaCompleta();
  assert.equal(h.calls.length, 1);
});

test("logout while a FAQ read is pending leaves no private content", async (t) => {
  const delayed = deferred();
  const h = fixture((url) => url.endsWith("/summary")
    ? response(200, emptySummary) : delayed.promise);
  t.after(() => h.dom.window.close());
  const pending = h.module.aggiornaConoscenzaCompleta();
  await settle();
  h.context.userId = null;
  h.context.epoch += 1;
  h.module.invalidate();
  delayed.resolve(response(200, { documenti: [faq] }));
  await pending;
  assert.equal(h.document.querySelector("#kb-faq-list .kb-item-card"), null);
});

test("a pending tab read cannot render after switching tabs", async (t) => {
  const delayed = deferred();
  const h = fixture((url) => {
    if (url.includes("tipo=faq")) return delayed.promise;
    return response(200, url.endsWith("/summary") ? emptySummary : { documenti: [] });
  });
  t.after(() => h.dom.window.close());
  h.document.querySelector('[data-kb-tab="faq"]').click();
  await settle();
  h.document.querySelector('[data-kb-tab="web"]').click();
  await settle();
  delayed.resolve(response(200, { documenti: [faq] }));
  await settle();
  assert.equal(h.document.querySelector("#kb-faq-list .kb-item-card"), null);
  assert.equal(h.document.getElementById("kb-panel-web").hidden, false);
});

test("reentering the panel does not register another tab listener", async (t) => {
  const h = fixture();
  t.after(() => h.dom.window.close());
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  h.document.querySelector('[data-kb-tab="web"]').click();
  await settle();
  assert.equal(h.calls.filter((c) => c.url.includes("tipo=web")).length, 1);
});

test("FAQ save stays single-flight across exit and restores the initial control", async (t) => {
  const delayed = deferred();
  const h = fixture((url, options) => options?.method === "POST" ? delayed.promise
    : response(200, url.endsWith("/summary") ? emptySummary : { documenti: [] }));
  t.after(() => h.dom.window.close());
  const button = h.document.getElementById("kb-faq-save-btn");
  const initial = button.innerHTML;
  h.document.getElementById("kb-faq-domanda").value = "Question";
  h.document.getElementById("kb-faq-risposta").value = "Answer";
  button.click();
  button.dispatchEvent(new h.window.Event("click"));
  assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 1);
  h.module.onExit();
  assert.equal(button.disabled, false);
  assert.equal(button.innerHTML, initial);
  h.context.transition += 1;
  h.module.onEnter();
  button.click();
  assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 1);
  delayed.resolve(response(200, {}));
  await settle();
  assert.equal(h.document.getElementById("kb-faq-domanda").value, "Question");
  button.click();
  await settle();
  assert.equal(h.calls.filter((c) => c.options?.method === "POST").length, 2);
});

test("file upload rejection and retry retain the original input listener", async (t) => {
  let uploads = 0;
  const h = fixture(async (url, options) => {
    if (options?.method === "POST") return response(++uploads === 1 ? 400 : 200, { detail: "File" });
    return response(200, url.endsWith("/summary") ? emptySummary : { documenti: [] });
  });
  t.after(() => h.dom.window.close());
  const input = h.document.getElementById("doc-file");
  const zone = h.document.getElementById("kb-doc-dropzone");
  const file = new h.window.File(["hello"], "menu.txt", { type: "text/plain" });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  h.document.querySelector('[data-kb-tab="documenti"]').click();
  input.dispatchEvent(new h.window.Event("change"));
  await settle();
  assert.equal(uploads, 1);
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  assert.equal(zone.querySelector("#doc-file"), input);
  input.dispatchEvent(new h.window.Event("change"));
  await settle();
  assert.equal(uploads, 2);
});

test("file upload double dispatch makes one request while pending", async (t) => {
  const delayed = deferred();
  let uploads = 0;
  const h = fixture((url, options) => {
    if (options?.method === "POST") { uploads += 1; return delayed.promise; }
    return response(200, url.endsWith("/summary") ? emptySummary : { documenti: [] });
  });
  t.after(() => h.dom.window.close());
  h.document.querySelector('[data-kb-tab="documenti"]').click();
  const input = h.document.getElementById("doc-file");
  Object.defineProperty(input, "files", { configurable: true,
    value: [new h.window.File(["hello"], "menu.txt", { type: "text/plain" })] });
  input.dispatchEvent(new h.window.Event("change"));
  input.dispatchEvent(new h.window.Event("change"));
  assert.equal(uploads, 1);
  delayed.resolve(response(200, { detail: "File indexed" }));
  await settle();
  assert.match(h.document.getElementById("doc-carica-status").textContent, /File indexed/);
});

test("detached FAQ action cannot mutate a newly selected organization", async (t) => {
  const h = fixture(async (url) => response(200, url.endsWith("/summary") ? emptySummary : { documenti: [faq] }));
  t.after(() => h.dom.window.close());
  await h.module.aggiornaConoscenzaCompleta();
  const oldDelete = h.document.querySelector("#kb-faq-list .kb-btn-delete");
  h.context.selectedOrganizationId = "org-2";
  h.module.onEnter();
  oldDelete.click();
  await settle();
  assert.equal(h.calls.some((c) => c.options?.method === "DELETE"), false);
});

test("exit cancels only the Knowledge confirmation and clears its description", async (t) => {
  const h = fixture(async (url) => response(200, url.endsWith("/summary") ? emptySummary : { documenti: [faq] }),
    (options) => h.window.MelpisDashboardShared.confirmDestructive(options));
  t.after(() => h.dom.window.close());
  await h.module.aggiornaConoscenzaCompleta();
  h.document.querySelector("#kb-faq-list .kb-btn-delete").click();
  assert.equal(h.document.getElementById("confirm-modal").hidden, false);
  assert.match(h.document.getElementById("confirm-desc").textContent, /Orari/);
  h.module.onExit();
  await settle();
  assert.equal(h.document.getElementById("confirm-modal").hidden, true);
  assert.equal(h.calls.some((c) => c.options?.method === "DELETE"), false);
});

test("Knowledge Escape restores delete focus without mutating, while exit preserves another focus target", async (t) => {
  const h = fixture(async (url) => response(200, url.endsWith("/summary") ? emptySummary : { documenti: [faq] }),
    (options) => h.window.MelpisDashboardShared.confirmDestructive(options));
  t.after(() => h.dom.window.close());
  await h.module.aggiornaConoscenzaCompleta();
  const button = h.document.querySelector("#kb-faq-list .kb-btn-delete");
  button.focus();
  button.click();
  const modal = h.document.getElementById("confirm-modal");
  assert.equal(modal.hidden, false);
  modal.dispatchEvent(new h.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await settle();
  assert.equal(modal.hidden, true);
  assert.equal(h.document.activeElement, button);
  assert.equal(h.calls.some((call) => call.options?.method === "DELETE"), false);

  button.click();
  assert.equal(modal.hidden, false);
  const otherTarget = h.document.getElementById("kb-faq-domanda");
  otherTarget.focus();
  h.module.onExit();
  await settle();
  assert.equal(modal.hidden, true);
  assert.equal(h.document.activeElement, otherTarget, "leaving the view must not steal focus from its new target");
  assert.equal(h.calls.some((call) => call.options?.method === "DELETE"), false);
});

test("auth denial clears private rows and prevents follow-up reads", async (t) => {
  let listCalls = 0;
  const h = fixture(async (url) => {
    if (url.endsWith("/summary")) return response(200, emptySummary);
    return response(++listCalls === 1 ? 200 : 403, { documenti: [faq] });
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaConoscenzaCompleta();
  assert.equal(h.document.querySelectorAll("#kb-faq-list .kb-item-card").length, 1);
  await h.module.aggiornaConoscenzaCompleta();
  assert.equal(h.document.querySelectorAll("#kb-faq-list .kb-item-card").length, 0);
  assert.equal(h.calls.filter((c) => c.url.endsWith("/summary")).length, 2);
});

test("two destructive row clicks cannot share one confirmation", async (t) => {
  const pending = deferred();
  let confirmations = 0;
  const h = fixture(async (url) => response(200, url.endsWith("/summary") ? emptySummary
    : { documenti: [faq, { ...faq, id: "faq-2" }] }), () => {
    confirmations += 1;
    return pending.promise;
  });
  t.after(() => h.dom.window.close());
  await h.module.aggiornaConoscenzaCompleta();
  h.document.querySelectorAll("#kb-faq-list .kb-btn-delete").forEach((button) => button.click());
  await settle();
  assert.equal(confirmations, 1);
  pending.resolve(false);
  await settle();
  assert.equal(h.calls.some((call) => call.options?.method === "DELETE"), false);
});

test("repeated clicks on the current tab share one pending list request", async (t) => {
  const pending = deferred();
  const h = fixture(() => pending.promise);
  t.after(() => h.dom.window.close());
  const tab = h.document.querySelector('[data-kb-tab="faq"]');
  tab.click(); tab.click();
  await settle();
  assert.equal(h.calls.length, 1);
  pending.resolve(response(200, { documenti: [faq] }));
  await settle();
  assert.equal(h.document.querySelectorAll("#kb-faq-list .kb-item-card").length, 1);
});

test("web source with script scheme renders without a clickable link", async (t) => {
  const h = fixture(async (url) => response(200, url.endsWith("/summary") ? emptySummary
    : { documenti: [{ id: "web-1", tipo: "web", nome: "Site", fonte: "javascript:alert(1)", is_active: true }] }));
  t.after(() => h.dom.window.close());
  h.document.querySelector('[data-kb-tab="web"]').click();
  await settle();
  assert.equal(h.document.querySelector("#kb-web-list a"), null);
  assert.match(h.document.getElementById("kb-web-list").textContent, /javascript:alert/);
});
