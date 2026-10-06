const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const source = fs.readFileSync(path.resolve(__dirname, "../../web/mfa.js"), "utf8");
const FACTOR_ID = "22222222-2222-4222-8222-222222222222";
const CHALLENGE_ID = "33333333-3333-4333-8333-333333333333";
const SECRET = "short-lived-test-secret";

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function setup(responses) {
  const dom = new JSDOM(`<!doctype html><html><body>
    <section id="security-mfa-card">
      <p id="security-mfa-status"></p><div id="security-mfa-factors"></div>
      <button id="security-mfa-enroll-start" hidden></button>
      <div id="security-mfa-enrollment" hidden><img id="security-mfa-qr" hidden><code id="security-mfa-secret"></code>
        <form id="security-mfa-enrollment-form"><input id="security-mfa-enrollment-code"><button type="submit"></button></form>
        <p id="security-mfa-enrollment-status"></p><button id="security-mfa-enrollment-cancel"></button>
      </div>
      <div id="security-mfa-challenge" hidden>
        <form id="security-mfa-challenge-form"><input id="security-mfa-challenge-code"><button type="submit"></button></form>
        <p id="security-mfa-challenge-status"></p><button id="security-mfa-challenge-cancel"></button>
      </div>
    </section>
  </body></html>`, { url: "http://test/app/", runScripts: "outside-only" });
  const calls = [];
  dom.window.MelpisAPI = {
    base: "",
    fetch: async (url, options = {}) => {
      calls.push({ url, options });
      const next = responses.shift();
      if (!next) throw new Error("unexpected request");
      return response(next.status, next.body);
    },
  };
  dom.window.apriVistaImpostazioni = (tab) => { dom.window.lastSettingsTab = tab; };
  dom.window.eval(source);
  return { dom, calls };
}

async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("enrollment 422 is not mislabeled as an invalid OTP", async () => {
  const { dom } = setup([
    { status: 200, body: { aal: "aal1", factors: [] } },
    { status: 422, body: { detail: "raw provider secret-data" } },
    { status: 200, body: { aal: "aal1", factors: [] } },
  ]);
  await dom.window.MelpisMfa.loadStatus();
  dom.window.document.getElementById("security-mfa-enroll-start").click();
  await flush();
  await flush();
  const message = dom.window.document.getElementById("security-mfa-status").textContent;
  assert.match(message, /operazione MFA/);
  assert.doesNotMatch(message, /Codice errato|secret-data|provider/);
  assert.equal(dom.window.document.getElementById("security-mfa-enrollment").hidden, true);
  dom.window.close();
});

test("MFA enrollment keeps QR and secret transient, promotes session, and clears setup data", async () => {
  const { dom, calls } = setup([
    { status: 200, body: { aal: "aal1", factors: [] } },
    { status: 200, body: { factor_id: FACTOR_ID, qr_code: "data:image/svg+xml;base64,c3Zn", secret: SECRET } },
    { status: 200, body: { challenge_id: CHALLENGE_ID } },
    { status: 200, body: { ok: true, aal: "aal2", csrf_token: "csrf-only" } },
    { status: 200, body: { aal: "aal2", factors: [{ id: FACTOR_ID, status: "verified", friendly_name: "Authenticator" }] } },
  ]);
  const win = dom.window;
  await win.MelpisMfa.loadStatus();
  assert.equal(win.document.getElementById("security-mfa-enroll-start").hidden, false);

  win.document.getElementById("security-mfa-enroll-start").click();
  await flush();
  assert.equal(win.document.getElementById("security-mfa-enrollment").hidden, false);
  assert.equal(win.document.getElementById("security-mfa-secret").textContent, SECRET);
  assert.equal(win.document.getElementById("security-mfa-qr").src, "data:image/svg+xml;base64,c3Zn");

  win.document.getElementById("security-mfa-enrollment-code").value = "123456";
  win.document.getElementById("security-mfa-enrollment-form").dispatchEvent(
    new win.Event("submit", { bubbles: true, cancelable: true }),
  );
  await flush();
  await flush();

  assert.deepEqual(calls.map((call) => call.url), [
    "/api/auth/mfa",
    "/api/auth/mfa/enroll",
    "/api/auth/mfa/challenge",
    "/api/auth/mfa/verify",
    "/api/auth/mfa",
  ]);
  assert.equal(win.document.getElementById("security-mfa-secret").textContent, "");
  assert.equal(win.document.getElementById("security-mfa-qr").hasAttribute("src"), false);
  assert.equal(win.document.getElementById("security-mfa-enrollment").hidden, true);
  assert.match(win.document.getElementById("security-mfa-status").textContent, /sessione è aggiornata/);
  assert.equal(win.localStorage.length, 0);
  assert.equal(JSON.parse(calls[3].options.body).code, "123456");
  assert.doesNotMatch(JSON.stringify(calls), /short-lived-test-secret/);
  dom.window.close();
});

test("AAL2-required action opens Security, challenges existing factor, then verifies code", async () => {
  const { dom, calls } = setup([
    { status: 200, body: { aal: "aal1", factors: [{ id: FACTOR_ID, status: "verified", friendly_name: "Authenticator" }] } },
    { status: 200, body: { challenge_id: CHALLENGE_ID } },
    { status: 200, body: { ok: true, aal: "aal2", csrf_token: "csrf-only" } },
    { status: 200, body: { aal: "aal2", factors: [{ id: FACTOR_ID, status: "verified", friendly_name: "Authenticator" }] } },
  ]);
  const win = dom.window;
  win.MelpisMfa.openForStepUp();
  await flush();
  await flush();
  assert.equal(win.lastSettingsTab, "sicurezza");
  assert.equal(win.document.getElementById("security-mfa-challenge").hidden, false);
  assert.equal(calls[1].url, "/api/auth/mfa/challenge");

  win.document.getElementById("security-mfa-challenge-code").value = "654321";
  win.document.getElementById("security-mfa-challenge-form").dispatchEvent(
    new win.Event("submit", { bubbles: true, cancelable: true }),
  );
  await flush();
  await flush();
  assert.equal(calls[2].url, "/api/auth/mfa/verify");
  assert.equal(win.document.getElementById("security-mfa-challenge").hidden, true);
  assert.match(win.document.getElementById("security-mfa-status").textContent, /Riprova l'operazione/);
  assert.doesNotMatch(JSON.stringify(calls), /csrf-only|access_token|refresh_token/);
  dom.window.close();
});

test("expired or incorrect code shows a safe error without logging or persisting secrets", async () => {
  const { dom, calls } = setup([
    { status: 200, body: { aal: "aal1", factors: [] } },
    { status: 200, body: { factor_id: FACTOR_ID, qr_code: "data:image/svg+xml;base64,c3Zn", secret: SECRET } },
    { status: 200, body: { challenge_id: CHALLENGE_ID } },
    { status: 422, body: { detail: "provider error containing secret" } },
  ]);
  const win = dom.window;
  await win.MelpisMfa.loadStatus();
  win.document.getElementById("security-mfa-enroll-start").click();
  await flush();
  win.document.getElementById("security-mfa-enrollment-code").value = "000000";
  win.document.getElementById("security-mfa-enrollment-form").dispatchEvent(
    new win.Event("submit", { bubbles: true, cancelable: true }),
  );
  await flush();
  await flush();
  const message = win.document.getElementById("security-mfa-enrollment-status").textContent;
  assert.match(message, /Codice errato o scaduto/);
  assert.doesNotMatch(message, /provider error|secret/);
  assert.equal(win.document.getElementById("security-mfa-secret").textContent, SECRET);
  assert.equal(win.localStorage.length, 0);
  assert.equal(JSON.parse(calls[3].options.body).code, "000000");
  assert.doesNotMatch(JSON.stringify(calls), /short-lived-test-secret/);
  dom.window.close();
});

test("stale primary authentication shows a visible re-login requirement", async () => {
  const { dom, calls } = setup([
    { status: 200, body: { aal: "aal1", factors: [] } },
    { status: 428, body: { detail: "reauthentication required" } },
    { status: 200, body: { aal: "aal1", factors: [] } },
  ]);
  const win = dom.window;
  await win.MelpisMfa.loadStatus();
  win.document.getElementById("security-mfa-enroll-start").click();
  await flush();
  await flush();
  assert.equal(calls[1].url, "/api/auth/mfa/enroll");
  assert.match(win.document.getElementById("security-mfa-status").textContent, /accedi di nuovo/);
  dom.window.close();
});
