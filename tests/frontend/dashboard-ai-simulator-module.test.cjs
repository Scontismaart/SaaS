const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const source = fs.readFileSync(path.join(root, "web/dashboard-ai-simulator.js"), "utf8");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function response(status, body) {
  return { status, ok: status >= 200 && status < 300, async json() { return body; } };
}

function fixture(apiFetch, { userId = "user-1", organizationId = "org-1", refreshes = {} } = {}) {
  const dom = new JSDOM(html, { url: "https://melpis.test/app/ai-simulator", runScripts: "outside-only" });
  const { window } = dom;
  const context = {
    userId, sessionOrganizationId: organizationId, selectedOrganizationId: organizationId,
    view: "assistente", transition: 1, epoch: 1,
  };
  const requests = [];
  const callbacks = [];
  const listenerRegistrations = [];
  let uuid = 0;
  Object.defineProperty(window.crypto, "randomUUID", { value: () => `uuid-${++uuid}` });
  const originalAddEventListener = window.EventTarget.prototype.addEventListener;
  window.EventTarget.prototype.addEventListener = function trackedAddEventListener(type, listener, options) {
    listenerRegistrations.push({ target: this, type: String(type), listener });
    return originalAddEventListener.call(this, type, listener, options);
  };
  const trackedApiFetch = (url, options = {}) => {
    const promise = apiFetch(url, options);
    requests.push({ url, options, promise });
    return promise;
  };
  window.eval(source);
  const module = window.MelpisDashboardAiSimulator.create({
    API_BASE: "",
    apiFetch: trackedApiFetch,
    PROFILO_ID: "profile-1",
    getContext: () => ({ ...context }),
    aggiornaRiepilogo: refreshes.riepilogo || (async () => callbacks.push("riepilogo")),
    aggiornaPrioritari: refreshes.prioritari || (async () => callbacks.push("prioritari")),
    aggiornaReport: refreshes.report || (async () => callbacks.push("report")),
    aggiornaPrenotazioni: refreshes.prenotazioni || (async () => callbacks.push("prenotazioni")),
    aggiornaSemaforo: refreshes.semaforo || (async () => callbacks.push("semaforo")),
    aggiornaNotifiche: refreshes.notifiche || (async () => callbacks.push("notifiche")),
  });
  return { dom, window, document: window.document, context, module, requests, callbacks, listenerRegistrations };
}

async function settle() {
  for (let index = 0; index < 60; index += 1) await Promise.resolve();
}

function submit(h, value) {
  h.document.getElementById("chat-input").value = value;
  h.document.getElementById("chat-form").dispatchEvent(
    new h.window.Event("submit", { bubbles: true, cancelable: true }),
  );
}

function messageRequests(h) {
  return h.requests.filter((request) => request.url.startsWith("/api/messaggio?"));
}

function messageBody(request) {
  return JSON.parse(request.options.body);
}

test("Simulator validates empty input, submits trimmed text, and preserves every classic refresh callback", async (t) => {
  const h = fixture(async () => response(200, { risposta: "Certo, siamo aperti.", richiede_umano: false, categoria: "orari" }));
  t.after(() => h.dom.window.close());
  h.module.onEnter();

  submit(h, "  \n  ");
  await settle();
  assert.equal(messageRequests(h).length, 0, "empty input must not call the message API");

  submit(h, "  Siete aperti oggi?  ");
  await settle();
  const [request] = messageRequests(h);
  assert.ok(request);
  assert.equal(request.url, "/api/messaggio?profilo_id=profile-1");
  assert.equal(request.options.method, "POST");
  assert.equal(messageBody(request).testo, "Siete aperti oggi?");
  assert.deepEqual(h.callbacks, ["riepilogo", "prioritari", "report", "prenotazioni", "semaforo", "notifiche"]);
  assert.equal(h.document.querySelector("#chat-body .bubble-ai:last-of-type p")?.textContent, "Certo, siamo aperti.");
});

test("Simulator sends actual suggestion chips through the same single-flight path", async (t) => {
  const pending = deferred();
  let mutationCount = 0;
  const h = fixture(async () => { mutationCount += 1; return pending.promise; });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  const chip = h.document.querySelector("#chat-suggestions .suggestion-chip");
  assert.ok(chip);
  chip.click();
  chip.click();
  await settle();
  assert.equal(mutationCount, 1, "repeated clicks on a chip while its message is pending remain single-flight");
  assert.equal(messageRequests(h).length, 1);
  assert.equal(messageBody(messageRequests(h)[0]).testo, chip.textContent.trim());
  assert.equal(h.document.querySelectorAll("#chat-body .bubble-typing").length, 1);

  pending.resolve(response(200, { risposta: "Risposta del simulatore", richiede_umano: false }));
  await Promise.all(messageRequests(h).map((request) => request.promise));
  await settle();
  assert.equal(h.document.querySelectorAll("#chat-body .bubble-typing").length, 0);
});

test("Simulator ignores duplicate form submissions and a chip while one message is pending", async (t) => {
  const pending = deferred();
  let mutationCount = 0;
  const h = fixture(async () => { mutationCount += 1; return pending.promise; });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  submit(h, "Messaggio inviato dal form");
  submit(h, "Messaggio inviato dal form");
  await settle();
  h.document.querySelector("#chat-suggestions .suggestion-chip").click();
  await settle();
  assert.equal(mutationCount, 1);
  assert.equal(messageRequests(h).length, 1);
  assert.equal(messageBody(messageRequests(h)[0]).testo, "Messaggio inviato dal form");
  assert.equal(h.document.querySelectorAll("#chat-body .bubble-out").length, 1, "only the accepted message is added to the chat");
  pending.resolve(response(200, { risposta: "Ok", richiede_umano: false }));
  await Promise.all(messageRequests(h).map((request) => request.promise));
  await settle();
});

test("Simulator uses a fresh idempotency key per message and keeps the conversation within one organization", async (t) => {
  const h = fixture(async () => response(200, { risposta: "Ok", richiede_umano: false }));
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  submit(h, "Primo messaggio");
  await settle();
  submit(h, "Secondo messaggio");
  await settle();
  const [first, second] = messageRequests(h);
  assert.ok(first && second);
  assert.ok(first.options.headers["Idempotency-Key"]);
  assert.ok(second.options.headers["Idempotency-Key"]);
  assert.notEqual(first.options.headers["Idempotency-Key"], second.options.headers["Idempotency-Key"]);
  assert.equal(messageBody(first).id_conversazione, messageBody(second).id_conversazione);

  h.module.onExit();
  h.context.view = "panoramica";
  h.context.transition += 1;
  h.context.view = "assistente";
  h.context.transition += 1;
  h.module.onEnter();
  submit(h, "Terzo messaggio dopo ritorno");
  await settle();
  const third = messageRequests(h)[2];
  assert.equal(messageBody(third).id_conversazione, messageBody(first).id_conversazione);
  assert.notEqual(third.options.headers["Idempotency-Key"], second.options.headers["Idempotency-Key"]);
});

test("Simulator clears the conversation on organization change and ignores a pending response after logout", async (t) => {
  const firstPending = deferred();
  const logoutPending = deferred();
  let calls = 0;
  const h = fixture(async () => {
    calls += 1;
    if (calls === 1) return firstPending.promise;
    if (calls === 3) return logoutPending.promise;
    return response(200, { risposta: "Risposta org due", richiede_umano: false });
  });
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  const originalChatHtml = h.document.getElementById("chat-body").innerHTML;
  submit(h, "Domanda organizzazione uno");
  await settle();
  const orgOneRequest = messageRequests(h)[0];
  assert.ok(orgOneRequest);
  h.context.selectedOrganizationId = "org-2";
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  assert.equal(h.document.getElementById("chat-body").innerHTML, originalChatHtml, "messages from the old organization are cleared to the original markup");
  firstPending.resolve(response(200, { risposta: "Risposta organizzazione uno", richiede_umano: false }));
  await orgOneRequest.promise;
  await settle();
  assert.doesNotMatch(h.document.getElementById("chat-body").textContent, /Risposta organizzazione uno/);

  submit(h, "Domanda organizzazione due");
  await settle();
  const orgTwoRequest = messageRequests(h)[1];
  assert.notEqual(messageBody(orgTwoRequest).id_conversazione, messageBody(orgOneRequest).id_conversazione);
  await orgTwoRequest.promise;
  await settle();

  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  submit(h, "Richiesta destinata a risposta tardiva");
  await settle();
  assert.equal(calls, 3);
  h.module.invalidate();
  assert.equal(h.document.getElementById("chat-body").innerHTML, originalChatHtml, "logout clears the private transcript");
  h.context.userId = null;
  logoutPending.resolve(response(200, { risposta: "Risposta dopo logout", richiede_umano: false }));
  await Promise.all(messageRequests(h).map((request) => request.promise));
  await settle();
  assert.equal(h.document.getElementById("chat-body").innerHTML, originalChatHtml);
  assert.doesNotMatch(h.document.getElementById("chat-body").textContent, /Risposta dopo logout/);
  assert.equal(h.document.querySelector("#chat-body .bubble-typing"), null);
});

test("Simulator removes orphan typing UI on exit while preserving same-org conversation history", async (t) => {
  const pending = deferred();
  const h = fixture(() => pending.promise);
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  submit(h, "Richiesta in corso");
  await settle();
  assert.ok(h.document.querySelector("#chat-body .bubble-typing"));
  const historyBeforeExit = h.document.getElementById("chat-body").innerHTML;
  h.module.onExit();
  assert.equal(h.document.querySelector("#chat-body .bubble-typing"), null);

  h.context.view = "panoramica";
  h.context.transition += 1;
  h.context.view = "assistente";
  h.context.transition += 1;
  h.module.onEnter();
  assert.equal(h.document.querySelector("#chat-body .bubble-typing"), null, "returning to the same organization never restores an orphan typing indicator");
  assert.ok(h.document.getElementById("chat-body").textContent.includes("Richiesta in corso"), "same-org history remains visible");

  pending.resolve(response(200, { risposta: "Risposta tardiva", richiede_umano: false }));
  await Promise.all(messageRequests(h).map((request) => request.promise));
  await settle();
  assert.doesNotMatch(h.document.getElementById("chat-body").textContent, /Risposta tardiva/);
  assert.notEqual(h.document.getElementById("chat-body").innerHTML, historyBeforeExit, "exit removes the transient typing node");
});

test("Simulator renders 504, HTTP, and network errors without false success or unsafe markup", async (t) => {
  for (const apiFetch of [
    async () => response(504, { detail: "gateway timeout" }),
    async () => response(403, { detail: "forbidden" }),
    async () => { throw new Error("network offline"); },
  ]) {
    const h = fixture(apiFetch);
    t.after(() => h.dom.window.close());
    h.module.onEnter();
    submit(h, '<img src=x onerror="window.compromised=true">');
    await settle();
    assert.equal(messageRequests(h).length, 1);
    assert.equal(h.document.querySelector("#chat-body img, #chat-body [onerror]"), null);
    assert.equal(h.window.compromised, undefined);
    assert.equal(h.callbacks.length, 0, "failed simulator calls must not refresh success data");
    assert.equal(h.document.querySelector("#chat-body .bubble-typing"), null);
    assert.equal(h.document.getElementById("chat-status").textContent, "online");
    assert.ok(h.document.querySelector("#chat-body .bubble-ai"), "a visible error response is shown in the actual chat DOM");
  }
});

test("Simulator does not submit while inactive and initializes form/chip listeners only once", async (t) => {
  const h = fixture(async () => response(200, { risposta: "Ok", richiede_umano: false }));
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  const form = h.document.getElementById("chat-form");
  const suggestions = h.document.getElementById("chat-suggestions");
  const countsBefore = [form, suggestions].map((target) => h.listenerRegistrations.filter((entry) => entry.target === target).length);
  h.module.onExit();
  h.context.view = "panoramica";
  h.context.transition += 1;
  h.context.view = "assistente";
  h.context.transition += 1;
  h.module.onEnter();
  h.module.onEnter();
  const countsAfter = [form, suggestions].map((target) => h.listenerRegistrations.filter((entry) => entry.target === target).length);
  assert.deepEqual(countsAfter, countsBefore);
  assert.ok(countsBefore[0] >= 1);
  assert.ok(countsBefore[1] >= 1);
  h.module.onExit();
  h.context.view = "panoramica";
  h.context.transition += 1;
  submit(h, "Non deve partire in una route inattiva");
  h.document.querySelector("#chat-suggestions .suggestion-chip").click();
  await settle();
  assert.equal(messageRequests(h).length, 0);
});

test("Simulator ignores JSON that settles after the view is exited and reentered", async (t) => {
  const parsed = deferred();
  const h = fixture(async () => ({ status: 200, ok: true, json: () => parsed.promise }));
  t.after(() => h.dom.window.close());
  h.module.onEnter();
  submit(h, "Domanda in attesa di JSON");
  await settle();
  h.module.onExit();
  h.context.transition += 1;
  h.module.onEnter();
  parsed.resolve({ risposta: "Risposta obsoleta", richiede_umano: false });
  await settle();
  assert.doesNotMatch(h.document.getElementById("chat-body").textContent, /Risposta obsoleta/);
  assert.deepEqual(h.callbacks, []);
  assert.equal(h.document.querySelector("#chat-body .bubble-typing"), null);
});

test("Simulator checks its scope after each refresh callback before starting the next", async (t) => {
  const names = ["riepilogo", "prioritari", "report", "prenotazioni", "semaforo", "notifiche"];
  for (const [index, name] of names.entries()) {
    const pending = deferred();
    const refreshes = {
      [name]: () => { pending.started = true; return pending.promise; },
    };
    const h = fixture(async () => response(200, { risposta: "Risposta", richiede_umano: false }), { refreshes });
    t.after(() => h.dom.window.close());
    h.module.onEnter();
    submit(h, `Domanda ${name}`);
    await settle();
    assert.equal(pending.started, true, `${name} callback was reached`);
    h.context.selectedOrganizationId = "org-2";
    h.module.onExit();
    h.context.transition += 1;
    h.module.onEnter();
    pending.resolve();
    await settle();
    assert.deepEqual(h.callbacks, names.slice(0, index), `no callback after ${name} runs in the new organization`);
    assert.equal(h.document.querySelectorAll("#chat-body .bubble-out").length, 0);
  }
});

test("Simulator retains its message lock across exit and return and restores original disabled states", async (t) => {
  const pending = deferred();
  let calls = 0;
  const h = fixture(async () => {
    calls += 1;
    return calls === 1 ? pending.promise : response(200, { risposta: "Nuova risposta", richiede_umano: false });
  });
  t.after(() => h.dom.window.close());
  const input = h.document.getElementById("chat-input");
  const send = h.document.querySelector("#chat-form button[type=submit]");
  const chips = [...h.document.querySelectorAll("#chat-suggestions button")];
  chips[1].disabled = true;
  h.module.onEnter();
  submit(h, "Prima domanda");
  await settle();
  assert.equal(input.disabled, true);
  assert.equal(send.disabled, true);
  assert.ok(chips.every((chip) => chip.disabled));
  h.module.onExit();
  assert.equal(input.disabled, false);
  assert.equal(send.disabled, false);
  assert.deepEqual(chips.map((chip) => chip.disabled), [false, true, false, false]);
  h.context.transition += 1;
  h.module.onEnter();
  submit(h, "Tentativo mentre la prima richiesta è in corso");
  chips[0].click();
  await settle();
  assert.equal(calls, 1);
  assert.equal(send.disabled, true);
  pending.resolve(response(200, { risposta: "Risposta obsoleta", richiede_umano: false }));
  await settle();
  assert.equal(send.disabled, false);
  assert.deepEqual(chips.map((chip) => chip.disabled), [false, true, false, false]);
  submit(h, "Seconda domanda");
  await settle();
  assert.equal(calls, 2);
  assert.doesNotMatch(h.document.getElementById("chat-body").textContent, /Risposta obsoleta/);
});
