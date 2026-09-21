const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const childProcess = require("node:child_process");
const { JSDOM } = require("jsdom");

const { ROUTE_MAP, SUPPORTED_LANGS, generateHreflangs, generateLanguageSelector } = require("../../scripts/build-i18n.js");

test("i18n: mandatory namespaces exist in source locale (it)", () => {
  const required = [
    "common.json", "landing.json", "pricing.json", "sectors.json",
    "docs.json", "auth.json", "dashboard.json", "inbox.json",
    "settings.json", "errors.json"
  ];
  const itDir = path.resolve(__dirname, "../../locales/it");
  assert.ok(fs.existsSync(itDir), "locales/it directory must exist");
  for (const ns of required) {
    const filePath = path.join(itDir, ns);
    assert.ok(fs.existsSync(filePath), `Namespace ${ns} must exist in locales/it`);
    const data = JSON.parse(fs.readFileSync(filePath, "utf8"));
    assert.ok(Object.keys(data).length > 0, `Namespace ${ns} must not be empty`);
  }
});

test("i18n: glossary.json defines approved brand terminology", () => {
  const glossaryPath = path.resolve(__dirname, "../../locales/glossary.json");
  assert.ok(fs.existsSync(glossaryPath), "glossary.json must exist");
  const glossary = JSON.parse(fs.readFileSync(glossaryPath, "utf8"));
  assert.equal(glossary.terms.Melpis.en, "Melpis");
  assert.equal(glossary.terms.WhatsApp.en, "WhatsApp");
  assert.equal(glossary.terms["Google Calendar"].en, "Google Calendar");
  assert.equal(glossary.terms["Meta Cloud API"].en, "Meta Cloud API");
});

test("i18n: route map has valid absolute paths with trailing slashes", () => {
  for (const [key, routes] of Object.entries(ROUTE_MAP)) {
    for (const lang of SUPPORTED_LANGS) {
      const url = routes[lang];
      assert.ok(url, `Route ${key} must define URL for ${lang}`);
      assert.ok(url.startsWith("/"), `Route ${key}.${lang} must start with /`);
      assert.ok(url.endsWith("/"), `Route ${key}.${lang} must end with /`);
    }
  }
});

test("i18n: generateHreflangs outputs canonical and x-default", () => {
  const tags = generateHreflangs("pricing", "it");
  assert.match(tags, /rel="canonical" href="https:\/\/melpis\.it\/prezzi\/"/);
  assert.match(tags, /rel="alternate" hreflang="it" href="https:\/\/melpis\.it\/prezzi\/"/);
  assert.match(tags, /rel="alternate" hreflang="en" href="https:\/\/melpis\.it\/en\/pricing\/"/);
  assert.match(tags, /rel="alternate" hreflang="es" href="https:\/\/melpis\.it\/es\/precios\/"/);
  assert.match(tags, /rel="alternate" hreflang="fr" href="https:\/\/melpis\.it\/fr\/tarifs\/"/);
  assert.match(tags, /rel="alternate" hreflang="de" href="https:\/\/melpis\.it\/de\/preise\/"/);
  assert.match(tags, /rel="alternate" hreflang="x-default" href="https:\/\/melpis\.it\/en\/pricing\/"/);
});

test("i18n: client adapter loads and provides Intl formatters", () => {
  const clientCode = fs.readFileSync(path.resolve(__dirname, "../../web/i18n-client.js"), "utf8");
  const dom = new JSDOM("<!DOCTYPE html><html><head></head><body></body></html>", {
    url: "https://melpis.it/app/",
    runScripts: "dangerously"
  });

  dom.window.eval(clientCode);
  const MelpisI18n = dom.window.MelpisI18n;

  assert.ok(MelpisI18n, "MelpisI18n must be exposed on window");
  assert.equal(typeof MelpisI18n.init, "function");
  assert.equal(typeof MelpisI18n.t, "function");
  assert.equal(typeof MelpisI18n.formatDate, "function");
  assert.equal(typeof MelpisI18n.formatCurrency, "function");

  // Format currency with IT locale
  const formattedIt = MelpisI18n.formatCurrency(69, "EUR");
  assert.match(formattedIt, /69/);

  dom.window.close();
});

test("production landing CSP has no inline-code exception", () => {
  const headers = fs.readFileSync(path.resolve(__dirname, "../../web/security-headers.conf"), "utf8");
  assert.match(headers, /script-src 'self';/);
  assert.match(headers, /style-src 'self';/);
  assert.doesNotMatch(headers, /(?:script-src|style-src) [^;]*'unsafe-inline'/);
  assert.match(headers, /style-src-attr 'unsafe-inline'/);
  childProcess.execFileSync(process.execPath, ["scripts/audit-csp.js"], {
    cwd: path.resolve(__dirname, "../.."),
    stdio: "pipe"
  });
});

test("FullCalendar uses only the deployed same-origin stylesheet under CSP", () => {
  const root = path.resolve(__dirname, "../..");
  const headers = fs.readFileSync(path.join(root, "web/security-headers.conf"), "utf8");
  const dashboard = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
  const vendor = fs.readFileSync(path.join(root, "web/vendor/fullcalendar.min.js"), "utf8");
  assert.match(headers, /style-src 'self';/);
  assert.match(dashboard, /<link rel="stylesheet" href="vendor\/fullcalendar\.css">/);
  assert.ok(fs.statSync(path.join(root, "web/vendor/fullcalendar.css")).size > 1000);
  assert.doesNotMatch(vendor, /function _e\(e\)\{let t=Re\.get\(e\)/, "runtime style creation is removed");
  childProcess.execFileSync(process.execPath, ["scripts/externalize-fullcalendar-styles.js", "--check"], {
    cwd: root,
    stdio: "pipe"
  });
  const dom = new JSDOM("<!doctype html><head></head><body></body>", { runScripts: "outside-only" });
  dom.window.eval(vendor);
  assert.equal(dom.window.document.querySelectorAll("style[data-fullcalendar]").length, 0);
  dom.window.close();
});

test("pricing copy never promises automatic electronic invoicing", () => {
  const pricing = fs.readFileSync(path.resolve(__dirname, "../../web/landing/prezzi/index.html"), "utf8");
  const extraCopy = fs.readFileSync(path.resolve(__dirname, "../../scripts/i18n-extra-copy.js"), "utf8");
  assert.match(pricing, /Ricevuta Stripe immediata; fattura fiscale su richiesta\./);
  assert.doesNotMatch(pricing, /Sistema di Interscambio|codice SDI/i);
  assert.doesNotMatch(extraCopy, /standard compliant tax invoices are automatically generated|facturas oficiales se generan y envían automáticamente|factures avec mentions fiscales légales sont automatiquement générées|Rechnungen mit ausgewiesener Mehrwertsteuer automatisch erstellt/i);
});

test("localized pricing has one native invoice answer and no Italian residue", () => {
  const routes = {
    en: ["pricing", "Your Stripe receipt is available immediately; request a fiscal invoice from us when needed."],
    es: ["precios", "Recibes el recibo de Stripe de inmediato; solicita la factura fiscal cuando la necesites."],
    fr: ["tarifs", "Votre reçu Stripe est disponible immédiatement ; demandez une facture fiscale si nécessaire."],
    de: ["preise", "Ihre Stripe-Quittung ist sofort verfügbar; fordern Sie bei Bedarf eine steuerliche Rechnung an."],
  };
  for (const [lang, [route, invoiceCopy]] of Object.entries(routes)) {
    const page = fs.readFileSync(path.resolve(__dirname, `../../web/landing/${lang}/${route}/index.html`), "utf8");
    const faq = page.match(/<section class="faq-section" id="faq">([\s\S]*?)<\/section>/);
    assert.ok(faq, `${lang} commercial FAQ section exists`);
    assert.equal(faq[1].split(invoiceCopy).length - 1, 1, `${lang} has exactly one native invoice answer`);
    assert.doesNotMatch(page, /Ricevuta Stripe immediata; fattura fiscale su richiesta\./, `${lang} has no Italian invoice copy`);
  }
});
