const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const source = fs.readFileSync(path.resolve(__dirname, "../../web/auth.js"), "utf8");

test("safeNext accepts canonical internal paths and queries", () => {
  const dom = new JSDOM("<!doctype html><html><body><a id=\"google-btn\"></a></body></html>", {
    url: "https://melpis.test/accedi/?next=%2Fapp%2Finbox",
    runScripts: "outside-only",
  });
  dom.window.fetch = async () => ({ ok: false });
  dom.window.eval(source);
  assert.equal(dom.window.eval('safeNext("/app/inbox")'), "/app/inbox");
  assert.equal(dom.window.eval('safeNext("/app/inbox?filter=open")'), "/app/inbox?filter=open");
  dom.window.eval("collegaGoogle()");
  assert.match(dom.window.document.getElementById("google-btn").href, /next=%2Fapp%2Finbox$/);
  dom.window.close();
});

test("safeNext and Google sign-in preserve the canonical Settings tab destination", () => {
  const next = "/app/settings?tab=calendar&source=google";
  const dom = new JSDOM("<!doctype html><html><body><a id=\"google-btn\"></a></body></html>", {
    url: `https://melpis.test/accedi/?next=${encodeURIComponent(next)}`,
    runScripts: "outside-only",
  });
  dom.window.fetch = async () => ({ ok: false });
  dom.window.eval(source);
  assert.equal(dom.window.eval(`safeNext(${JSON.stringify(next)})`), next);
  dom.window.eval("collegaGoogle()");
  assert.equal(new URL(dom.window.document.getElementById("google-btn").href).searchParams.get("next"), next);
  dom.window.close();
});

test("safeNext rejects external, parser-normalized, and control-character paths", () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "https://melpis.test/accedi/",
    runScripts: "outside-only",
  });
  dom.window.fetch = async () => ({ ok: false });
  dom.window.eval(source);
  const unsafe = [
    "https://evil.com", "//evil.com", "/\\evil.com", "/%0A/evil.com", "/%250A/evil.com",
    "/%2f%2fevil.com", "/%252f%252fevil.com", "/line\nbreak", "/tab\tpath", "/del\u007fpath", "/c0\u0001path",
  ];
  for (const value of unsafe) {
    assert.equal(dom.window.eval(`safeNext(${JSON.stringify(value)})`), "/app/", `unsafe next accepted: ${JSON.stringify(value)}`);
  }
  dom.window.close();
});

test("login uses the raw fragment next to preserve all dashboard query parameters", () => {
  const target = "/app/inbox?filter=open&sort=recent&cursor=a%26b";
  const dom = new JSDOM("<!doctype html><html><body><a id=\"google-btn\"></a></body></html>", {
    url: `https://melpis.test/accedi/?next=/app/inbox#next=${target}`,
    runScripts: "outside-only",
  });
  dom.window.fetch = async () => ({ ok: false });
  dom.window.eval(source);
  assert.equal(dom.window.eval('urlConNext("/registrati/")'), `/registrati/?next=${encodeURIComponent(target)}`);
  dom.window.eval("collegaGoogle()");
  assert.equal(new URL(dom.window.document.getElementById("google-btn").href).searchParams.get("next"), target);
  dom.window.close();
});

test("login keeps legacy query next when no fragment is provided", () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", {
    url: "https://melpis.test/accedi/?next=%2Fapp%2Fteam%3Ftab%3Dmembers%26sort%3Dname",
    runScripts: "outside-only",
  });
  dom.window.fetch = async () => ({ ok: false });
  dom.window.eval(source);
  assert.equal(dom.window.eval('urlConNext("/registrati/")'), "/registrati/?next=%2Fapp%2Fteam%3Ftab%3Dmembers%26sort%3Dname");
  dom.window.close();
});

test("unsafe fragment next fails closed instead of using the query fallback", () => {
  for (const fragment of ["//evil.test", "/%0A/evil", "/%252f%252fevil.test"]) {
    const dom = new JSDOM("<!doctype html><html><body></body></html>", {
      url: `https://melpis.test/accedi/?next=/app/inbox#next=${fragment}`,
      runScripts: "outside-only",
    });
    dom.window.fetch = async () => ({ ok: false });
    dom.window.eval(source);
    assert.equal(dom.window.eval('urlConNext("/registrati/")'), "/registrati/?next=%2Fapp%2F", fragment);
    dom.window.close();
  }
});
