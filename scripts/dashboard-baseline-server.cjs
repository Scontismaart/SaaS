// QA-only loopback server. Real dashboard assets + synthetic API, no credentials/DB.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { reply, FIXED_TIME } = require("../tests/frontend/fixtures/dashboard-visual-api.cjs");
const root = path.resolve(__dirname, "..", "web");
const port = Number(process.env.DASHBOARD_QA_PORT || 4190);
const csp = fs.readFileSync(path.join(root, "security-headers.conf"), "utf8").match(/Content-Security-Policy "([^"]+)"/)[1];
const requests = [];
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2", ".png": "image/png", ".webp": "image/webp", ".webmanifest": "application/manifest+json" };
const server = http.createServer((req, res) => {
  if (![`127.0.0.1:${port}`, `localhost:${port}`].includes(req.headers.host)) { res.writeHead(403).end(); return; }
  res.setHeader("Content-Security-Policy", csp);
  res.setHeader("X-Content-Type-Options", "nosniff");
  res.setHeader("Referrer-Policy", "no-referrer");
  res.setHeader("Cache-Control", "no-store");
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  if (url.pathname.startsWith("/api/")) {
    const result = reply(req.method, url.pathname);
    // Deliberately record no headers, cookies, query values or request bodies.
    requests.push({ method: req.method, path: url.pathname, status: result.status });
    req.resume();
    res.writeHead(result.status, { "Content-Type": "application/json" }).end(JSON.stringify(result.body));
    return;
  }
  if (req.method !== "GET" && req.method !== "HEAD") { res.writeHead(405).end(); return; }
  if (url.pathname === "/__qa/requests") { res.writeHead(200, { "Content-Type": "application/json" }).end(JSON.stringify(requests)); return; }
  if (url.pathname === "/__qa/bootstrap.js") {
    res.writeHead(200, { "Content-Type": "text/javascript" }).end(`
      // This test-only script is never shipped in web/ or its Docker image.
      const RealDate = Date;
      window.Date = class extends RealDate { constructor(...args) { super(...(args.length ? args : [${JSON.stringify(FIXED_TIME)}])); } static now() { return new RealDate(${JSON.stringify(FIXED_TIME)}).getTime(); } };
      localStorage.setItem('melpis_lang', 'it');
      localStorage.setItem('melpis-theme', 'dark');
      document.cookie = 'melpis_lang=it; Path=/; SameSite=Strict';
      document.cookie = 'wa_csrf=synthetic-qa-only; Path=/; SameSite=Strict';
      const nativeFetch = window.fetch.bind(window);
      let pending = 0, revision = 0;
      async function ready() {
        const visit = ++revision;
        await document.fonts.ready;
        // Wait for production entrance transitions; do not alter their CSS/rendering.
        await new Promise(resolve => requestAnimationFrame(resolve));
        // Capture the live-status pulse at frame zero, rather than a random instant.
        // This exists only in the isolated screenshot server, not shipped assets.
        document.getAnimations().filter(animation => !Number.isFinite(animation.effect.getComputedTiming().endTime))
          .forEach(animation => { animation.pause(); animation.currentTime = 0; });
        await Promise.all(document.getAnimations()
          .filter(animation => Number.isFinite(animation.effect.getComputedTiming().endTime))
          .map(animation => animation.finished.catch(() => {})));
        requestAnimationFrame(() => requestAnimationFrame(() => {
          if (!pending && revision === visit && document.body) document.body.dataset.qaReady = 'true';
        }));
      }
      window.fetch = async (...args) => {
        pending++; revision++;
        if (document.body) document.body.dataset.qaReady = 'false';
        try { return await nativeFetch(...args); }
        finally { pending--; if (!pending) ready(); }
      };
      document.addEventListener('DOMContentLoaded', ready, {once:true});
    `);
    return;
  }
  if (url.pathname === "/config.js") { res.writeHead(200, { "Content-Type": "text/javascript" }).end("window.MELPIS_API_BASE = '';\n"); return; }
  let relative;
  let dashboard = false;
  if (url.pathname === "/app" || /^\/app\/(overview|inbox|bookings|reviews|team|ai-simulator|knowledge|ai-settings|settings)\/?$/.test(url.pathname)) {
    relative = "index.html"; dashboard = true;
  } else if (url.pathname.startsWith("/app/")) { relative = url.pathname.slice(5); }
  else if (/^\/(brand|fonts|locales)\//.test(url.pathname) || url.pathname === "/i18n-client.js") { relative = url.pathname.slice(1); }
  else { res.writeHead(404).end(); return; }
  const target = path.resolve(root, relative);
  if (!target.startsWith(root + path.sep) || !fs.existsSync(target) || !fs.statSync(target).isFile()) { res.writeHead(404).end(); return; }
  res.setHeader("Content-Type", types[path.extname(target)] || "application/octet-stream");
  let content = fs.readFileSync(target);
  if (dashboard) content = content.toString().replace('<script src="/app/theme-init.js">', '<script src="/__qa/bootstrap.js"></script>\n<script src="/app/theme-init.js">');
  res.end(req.method === "HEAD" ? undefined : content);
});
if (require.main === module) server.listen(port, "127.0.0.1", () => console.log(`Synthetic dashboard QA: http://127.0.0.1:${port}/app/overview`));
module.exports = { server };
