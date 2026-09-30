const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const source = fs.readFileSync(path.resolve(__dirname, "../../web/register.js"), "utf8");
const GOOD_PASSWORD = "Strong-pass-2026!";

async function signupRequest(search, password = GOOD_PASSWORD) {
  const dom = new JSDOM(`<!doctype html><html><body>
    <a id="link-accedi" href="/accedi/"></a>
    <a id="success-login-link" href="/accedi/"></a>
    <form id="form-register">
      <input id="reg-nome" value="Studio Nuovo">
      <input id="reg-email" value="new@example.test">
      <input id="reg-password" value="${password ?? ""}">
      <div id="password-rules">
        <li data-check="len"></li><li data-check="special"></li>
        <li data-check="upper"></li><li data-check="num"></li>
      </div>
      <div id="pw-bar"></div>
      <input id="reg-termini" type="checkbox" checked>
      <button id="register-save"></button>
    </form>
    <p id="register-error"></p>
    <p id="register-success" tabindex="-1" hidden></p>
  </body></html>`, {
    url: `https://app.example.test/registrati/${search}`,
    runScripts: "outside-only",
  });
  let body;
  let calls = 0;
  const win = dom.window;
  win.AUTH_API_BASE = "";
  win.urlConNext = (base) => base;
  win.collegaGoogle = () => {};
  win.clearAuthFieldError = () => {};
  win.showAuthFieldError = () => {};
  win.getAuthMessage = (key) => key;
  win.fetch = async (_url, options) => {
    calls += 1;
    body = JSON.parse(options.body);
    return { ok: true, json: async () => ({ ok: true }) };
  };
  win.eval(source);
  win.document.getElementById("form-register").dispatchEvent(
    new win.Event("submit", { bubbles: true, cancelable: true }),
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  dom.window.close();
  return { body, calls };
}

async function signupBody(search) {
  return (await signupRequest(search)).body;
}

test("signup forwards one URL-decoded next value", async () => {
  const body = await signupBody("?next=%2Farea%2Fsettings%2F");
  assert.equal(body.next, "/area/settings/");
});

test("signup omits ambiguous duplicate next values", async () => {
  const body = await signupBody("?next=%2Farea%2F&next=%2Fbilling%2F");
  assert.equal(Object.hasOwn(body, "next"), false);
});

test("signup requires all password rules before sending the request", async () => {
  for (const password of ["", "short", "lowercase-only!", "NoNumber!!", "nonumber2026!"]) {
    const result = await signupRequest("", password);
    assert.equal(result.calls, 0, `unexpected request for password: ${password}`);
  }
});

test("signup sends the chosen password only in the BFF request body", async () => {
  const result = await signupRequest("");
  assert.equal(result.calls, 1);
  assert.equal(result.body.password, GOOD_PASSWORD);
  assert.doesNotMatch(source, /localStorage|sessionStorage|console\.(?:log|warn|error)/);
});

test("every served signup page has the password rules and confirmation-then-login copy", () => {
  const root = path.resolve(__dirname, "../../web");
  const pages = [
    "register.html",
    "registrati/index.html",
    "landing/en/signup/index.html",
    "landing/es/registro/index.html",
    "landing/fr/inscription/index.html",
    "landing/de/registrieren/index.html",
  ];
  const dockerfile = fs.readFileSync(path.join(root, "Dockerfile"), "utf8");
  const nginx = fs.readFileSync(path.join(root, "nginx.conf"), "utf8");
  assert.match(dockerfile, /COPY login\.html login\.js register\.html register\.js auth\.js auth\.css/);
  assert.match(nginx, /location = \/registrati\/\s*\{\s*try_files \/register\.html =404;/);
  for (const relative of pages) {
    const html = fs.readFileSync(path.join(root, relative), "utf8");
    assert.match(html, /id="reg-password" type="password" autocomplete="new-password" minlength="10" maxlength="256"/);
    for (const rule of ["len", "special", "upper", "num"]) {
      assert.match(html, new RegExp(`data-check="${rule}"`));
    }
    assert.match(html, /success-login-link/);
    assert.doesNotMatch(html, /name="confirm_password"/);
  }
});
