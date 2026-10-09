const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "../..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const sharedSource = fs.readFileSync(path.join(root, "web/dashboard-shared.js"), "utf8");

function createDom({ focusManager = true, realPurify = false } = {}) {
  const dom = new JSDOM(html, { url: "https://melpis.test/app/overview", runScripts: "outside-only", pretendToBeVisual: true });
  const { window } = dom;
  if (realPurify) window.eval(fs.readFileSync(path.join(root, "web/vendor/dompurify.min.js"), "utf8"));
  else window.DOMPurify = { sanitize: (value) => String(value ?? "") };
  if (focusManager) window.eval(fs.readFileSync(path.join(root, "web/dialog-focus.js"), "utf8"));
  window.eval(sharedSource);
  return dom;
}

test("shared escaping and sanitizing preserve null handling, DOMPurify policy, and fallback", (t) => {
  const dom = createDom({ realPurify: true }); t.after(() => dom.window.close());
  const shared = dom.window.MelpisDashboardShared;
  assert.equal(Object.isFrozen(shared), true);
  assert.equal(shared.escapeHtml(null), "");
  assert.equal(shared.escapeHtml(`<&>\"'`), "&lt;&amp;&gt;&quot;&#039;");
  assert.equal(shared.sanitize(null), "");
  assert.equal(shared.sanitize('<img src=x onerror="alert(1)"><script>alert(1)</script><b>ok</b>'), "<img src=\"x\"><b>ok</b>");
  dom.window.DOMPurify = undefined;
  assert.equal(shared.sanitize(`<img src=x onerror='x'>`), "&lt;img src=x onerror=&#039;x&#039;&gt;");
});

test("module evaluation is inert until a shared helper is called", (t) => {
  const dom = new JSDOM(html, { url: "https://melpis.test/app/overview", runScripts: "outside-only", pretendToBeVisual: true });
  t.after(() => dom.window.close());
  const { window } = dom;
  let listeners = 0, timers = 0, frames = 0, mutations = 0;
  const originalAddEventListener = window.EventTarget.prototype.addEventListener;
  window.EventTarget.prototype.addEventListener = function (...args) {
    listeners += 1;
    return originalAddEventListener.apply(this, args);
  };
  window.setTimeout = () => { timers += 1; return timers; };
  window.requestAnimationFrame = () => { frames += 1; return frames; };
  const observer = new window.MutationObserver((records) => { mutations += records.length; });
  observer.observe(window.document, { subtree: true, childList: true, attributes: true, characterData: true });
  window.eval(sharedSource);
  assert.equal(Object.isFrozen(window.MelpisDashboardShared), true);
  assert.deepEqual({ listeners, timers, frames, mutations }, { listeners: 0, timers: 0, frames: 0, mutations: 0 });
  observer.disconnect();
});

test("sanitization uses live DOMPurify and removes unsafe links and SVG handlers", (t) => {
  const dom = createDom({ realPurify: true }); t.after(() => dom.window.close());
  const { window } = dom, shared = window.MelpisDashboardShared;
  const clean = shared.sanitize('<a href="javascript:alert(1)">javascript</a><a href="data:text/html,boom">data</a><svg onload="alert(1)"><a>vector</a></svg><strong>format</strong><a href="https://safe.example/path">safe</a>');
  const fragment = window.document.createElement("template");
  fragment.innerHTML = clean;
  const links = [...fragment.content.querySelectorAll("a")];
  assert.equal(links.length, 4);
  assert.equal(links[0].hasAttribute("href"), false);
  assert.equal(links[1].hasAttribute("href"), false);
  assert.equal(links[3].getAttribute("href"), "https://safe.example/path");
  assert.equal(fragment.content.querySelector("svg")?.hasAttribute("onload"), false);
  assert.equal(fragment.content.querySelector("strong")?.textContent, "format");

  let sanitizedByLateProvider = 0;
  window.DOMPurify = { sanitize: (value) => { sanitizedByLateProvider += 1; return `late:${value}`; } };
  assert.equal(shared.sanitize("value"), "late:value");
  assert.equal(sanitizedByLateProvider, 1);
  window.DOMPurify = { sanitize: null };
  assert.equal(shared.sanitize("<b>fallback</b>"), "&lt;b&gt;fallback&lt;/b&gt;");
});

test("toast creates one accessible container, renders text safely, invokes its action once, and expires", (t) => {
  const dom = createDom(); t.after(() => dom.window.close());
  const { window } = dom;
  const timers = [];
  window.setTimeout = (callback, delay) => { timers.push({ callback, delay }); return timers.length; };
  let frames = 0, actions = 0;
  window.requestAnimationFrame = (callback) => { frames += 1; callback(); };
  const shared = window.MelpisDashboardShared;
  shared.toast("<unsafe>", "success", 1234, { testo: "Undo", onClick: () => { actions += 1; } });
  shared.toast("second", "info");
  const container = window.document.getElementById("toast-container");
  assert.equal(window.document.querySelectorAll("#toast-container").length, 1);
  assert.equal(container.getAttribute("role"), "status");
  assert.equal(container.getAttribute("aria-live"), "polite");
  assert.equal(container.children.length, 2);
  assert.equal(container.children[0].querySelector("span").textContent, "<unsafe>");
  assert.equal(container.children[0].classList.contains("toast-in"), true);
  assert.equal(frames, 2);
  assert.deepEqual(timers.map(({ delay }) => delay), [1234, 4200]);
  container.querySelector(".toast-action-btn").click();
  container.querySelector(".toast-action-btn")?.click();
  assert.equal(actions, 1);
  assert.equal(container.children.length, 1);
  timers[1].callback();
  assert.equal(container.children[0].classList.contains("toast-in"), false);
  assert.equal(timers[2].delay, 320);
  timers[2].callback();
  assert.equal(container.children.length, 0);
});

test("destructive confirmation keeps dialog focus, keyboard, single resolution, and listener cleanup behavior", async (t) => {
  const dom = createDom(); t.after(() => dom.window.close());
  const { window } = dom, doc = window.document;
  const returnTarget = doc.createElement("button"); doc.body.appendChild(returnTarget); returnTarget.focus();
  const modal = doc.getElementById("confirm-modal"), ok = doc.getElementById("confirm-ok-btn"), cancel = doc.getElementById("confirm-cancel-btn");
  const promise = window.MelpisDashboardShared.confirmDestructive({ titolo: "Delete?", descrizione: "Careful", label: "Delete" });
  assert.equal(modal.hidden, false);
  assert.equal(doc.getElementById("confirm-title").textContent, "Delete?");
  assert.equal(doc.getElementById("confirm-desc").textContent, "Careful");
  assert.equal(ok.textContent, "Delete");
  assert.equal(doc.activeElement, ok);
  modal.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
  assert.equal(doc.activeElement, cancel);
  modal.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }));
  assert.equal(doc.activeElement, ok);
  ok.click();
  assert.equal(await promise, true);
  assert.equal(modal.hidden, true);
  assert.equal(doc.activeElement, returnTarget);
  ok.click();
  assert.equal(modal.hidden, true, "the resolved dialog has no leftover click handler");
});

test("destructive confirmation resolves Escape and cancel false, and uses native confirm when modal is absent", async (t) => {
  const dom = createDom(); t.after(() => dom.window.close());
  const { window } = dom, doc = window.document;
  let promise = window.MelpisDashboardShared.confirmDestructive();
  doc.getElementById("confirm-modal").dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
  assert.equal(await promise, false);
  promise = window.MelpisDashboardShared.confirmDestructive();
  doc.getElementById("confirm-cancel-btn").click();
  assert.equal(await promise, false);
  doc.getElementById("confirm-modal").remove();
  window.confirm = (message) => message === "Please confirm";
  assert.equal(await window.MelpisDashboardShared.confirmDestructive({ titolo: "Title", descrizione: "Please confirm" }), true);
});

test("date keys retain ISO strings, local Date components, and invalid input behavior", (t) => {
  const dom = createDom(); t.after(() => dom.window.close());
  const { toDateKey } = dom.window.MelpisDashboardShared;
  assert.equal(toDateKey("2026-02-03"), "2026-02-03");
  assert.equal(toDateKey("2026-99-99"), "2026-99-99", "the raw ISO-shaped shortcut does not validate calendar ranges");
  assert.equal(toDateKey(new dom.window.Date(2026, 0, 9, 23, 30)), "2026-01-09");
  const localBoundary = new dom.window.Date("2026-01-01T00:30:00+02:00");
  const localExpected = `${localBoundary.getFullYear()}-${String(localBoundary.getMonth() + 1).padStart(2, "0")}-${String(localBoundary.getDate()).padStart(2, "0")}`;
  assert.equal(toDateKey(localBoundary), localExpected, "Date instances use local calendar fields at a timezone boundary");
  assert.equal(toDateKey("not-a-date"), "");
  assert.equal(toDateKey(undefined), "");
  assert.equal(toDateKey(new dom.window.Date(NaN)), "");
  assert.equal(toDateKey(null), "1970-01-01");
});
