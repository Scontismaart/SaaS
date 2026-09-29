const fs = require("fs");
const path = require("path");

const root = path.join(process.cwd(), "web");
const excluded = new Set([
  path.join(root, "landing", "hero-glassmorphism.html"),
  path.join(root, "landing", "knowledge-hero.html"),
]);
const assetExtension = /\.(?:avif|css|gif|ico|jpe?g|js|mjs|png|svg|webp|woff2?)(?:[?#].*)?$/i;
const missing = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if ((entry.name.endsWith(".html") || entry.name.endsWith(".css")) && !excluded.has(file)) check(file);
  }
}

function check(file) {
  const text = fs.readFileSync(file, "utf8");
  const values = [];
  for (const match of text.matchAll(/(?:src|href)=["']([^"']+)["']/gi)) values.push(match[1]);
  for (const match of text.matchAll(/url\(["']?([^"')]+)["']?\)/gi)) values.push(match[1]);
  for (const value of values) {
    if (!assetExtension.test(value) || /^(?:data:|https?:|\/\/)/i.test(value)) continue;
    const clean = value.replace(/[?#].*$/, "");
    // Dockerfile publishes web/landing as the document root, while dashboard
    // files remain under /app. Resolve absolute landing references accordingly.
    const landingDocumentRoot = file.startsWith(path.join(root, "landing") + path.sep)
      || file.startsWith(path.join(root, "inline-assets") + path.sep);
    const landingRootAsset = /^\/brand\//.test(clean);
    const documentRoot = landingDocumentRoot || landingRootAsset
      ? path.join(root, "landing")
      : root;
    // A few landing routes intentionally share dashboard/auth root assets and
    // the content-addressed CSP assets; Dockerfile publishes those from web/.
    const sharedRootAsset = /^\/(?:inline-assets\/|auth(?:\.css|\.js)|login\.js|register\.js|config\.js|design-tokens\.css)/.test(clean);
    let candidate = clean.startsWith("/")
      ? path.join(sharedRootAsset ? root : documentRoot, clean.slice(1))
      : path.resolve(path.dirname(file), clean);
    if (clean === "/config.js") candidate = path.join(root, "config.template.js");
    // The same shared token file is copied to /app/ by the web Dockerfile.
    if (clean === "/app/design-tokens.css") candidate = path.join(root, "design-tokens.css");
    if (!(sharedRootAsset ? candidate.startsWith(root) : candidate.startsWith(documentRoot)) || !fs.existsSync(candidate)) {
      missing.push(`${path.relative(process.cwd(), file)} -> ${value}`);
    }
  }
}

walk(root);
if (missing.length) {
  console.error(`Missing referenced local assets (${missing.length}):\n${missing.join("\n")}`);
  process.exit(1);
}
console.log("Referenced local asset audit passed.");
