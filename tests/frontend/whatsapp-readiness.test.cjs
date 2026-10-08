const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const app = fs.readFileSync(path.resolve(__dirname, "../../web/app.js"), "utf8").replace(/\r\n/g, "\n");
const html = fs.readFileSync(path.resolve(__dirname, "../../web/index.html"), "utf8");
const start = app.indexOf("async function caricaStatoWhatsApp()");
const source = app.slice(start, app.indexOf("\nasync function caricaStatoInstagram", start));

for (const configured of [false, true]) {
  test(`saved credentials do not certify WhatsApp reception (webhook configured=${configured})`, async (t) => {
    const dom = new JSDOM(`<div id="integ-whatsapp-connected-card"></div>
      <div id="integ-whatsapp-wizard-card"></div><span id="integ-wa-phone-number-display"></span>
      <span id="integ-wa-connected-title"></span><span id="integ-wa-connected-sub"></span>
      <span id="integ-whatsapp-stato"></span><span id="integ-wa-reception-status"></span>`, { runScripts: "outside-only" });
    t.after(() => dom.window.close());
    dom.window.apiFetch = async () => ({ ok: true, json: async () => ({ connesso: true, webhook_active: configured, phone_number_id: "123" }) });
    dom.window.eval(`const API_BASE = ""; function _aggiornaBadgeStato() {} ${source}`);
    await dom.window.eval("caricaStatoWhatsApp()");
    assert.match(dom.window.document.getElementById("integ-wa-connected-sub").textContent, /Credenziali collegate/);
    const reception = dom.window.document.getElementById("integ-wa-reception-status").textContent;
    assert.match(reception, configured ? /Da verificare/ : /Non attiva/);
    assert.doesNotMatch(dom.window.document.body.textContent, /pronto a rispondere|Attiva in tempo reale/);
  });
}

test("initial WhatsApp markup does not claim unverified operation", () => {
  const card = html.slice(html.indexOf('id="integ-whatsapp-connected-card"'), html.indexOf('id="integ-whatsapp-wizard-card"'));
  assert.doesNotMatch(card, /Connesso e pronto a rispondere|Attiva in tempo reale/);
});
