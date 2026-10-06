const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const app = fs.readFileSync(path.resolve(__dirname, "../../web/app.js"), "utf8");
const start = app.indexOf('window.addEventListener("storage",');
const end = app.indexOf("(async function avvia()", start);
assert.ok(start >= 0 && end > start);

function fixture(pathname = "/app/overview") {
  const handlers = {};
  const classes = new Set(["authenticated"]);
  let reloads = 0;
  let redirects = 0;
  const body = { classList: { remove: (name) => classes.delete(name) }, dataset: {} };
  vm.runInNewContext(app.slice(start, end), {
    document: { body }, console: { debug() {} },
    invalidaSessione: () => classes.delete("authenticated"),
    vaiAdAccesso: () => { redirects += 1; },
    window: {
      addEventListener: (event, handler) => { handlers[event] = handler; },
      location: { pathname, reload: () => { reloads += 1; } },
    },
  });
  return { handlers, classes, body, reloads: () => reloads, redirects: () => redirects };
}

test("successful logout in another tab hides private UI and returns to login", () => {
  const f = fixture();
  f.handlers.storage({ key: "melpis_auth_logout", newValue: "non-secret-event" });
  assert.equal(f.classes.has("authenticated"), false);
  assert.equal(f.redirects(), 1);
});

test("unrelated storage changes and removed markers do not redirect", () => {
  const f = fixture();
  f.handlers.storage({ key: "other", newValue: "value" });
  f.handlers.storage({ key: "melpis_auth_logout", newValue: null });
  assert.equal(f.classes.has("authenticated"), true);
  assert.equal(f.redirects(), 0);
});

test("a cross-tab logout does not navigate public documents", () => {
  const f = fixture("/accedi/");
  f.handlers.storage({ key: "melpis_auth_logout", newValue: "non-secret-event" });
  assert.equal(f.redirects(), 0);
});

// These are handler regressions, not substitutes for actual browser BFCache QA.
test("pagehide removes private visibility before a document can be cached", () => {
  const f = fixture();
  f.handlers.pagehide({ persisted: true });
  assert.equal(f.classes.has("authenticated"), false);
});

test("real persisted pageshow handler keeps private content hidden and reloads", () => {
  const f = fixture();
  f.handlers.pageshow({ persisted: true });
  assert.equal(f.classes.has("authenticated"), false);
  assert.equal(f.reloads(), 1);
  assert.equal(f.body.dataset.authPageshowPersisted, "true");
});

test("ordinary pageshow does not enter a reload loop", () => {
  const f = fixture();
  f.handlers.pageshow({ persisted: false });
  assert.equal(f.reloads(), 0);
  assert.equal(f.body.dataset.authPageshowPersisted, "false");
});

test("public documents are not reloaded by the authenticated restore guard", () => {
  const f = fixture("/accedi/");
  f.handlers.pageshow({ persisted: true });
  assert.equal(f.reloads(), 0);
});
