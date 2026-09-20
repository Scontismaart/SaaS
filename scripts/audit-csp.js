const fs = require("fs");
const path = require("path");
const { isExecutableScript } = require("./extract-inline-assets");

const root = path.join(process.cwd(), "web");
const excluded = new Set([
  path.join(root, "landing", "hero-glassmorphism.html"),
  path.join(root, "landing", "knowledge-hero.html"),
]);
const findings = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(file);
    else if (entry.name.endsWith(".html") && !excluded.has(file)) {
      const content = fs.readFileSync(file, "utf8");
      if (/<style\b[^>]*>[\s\S]*?<\/style>/i.test(content)) findings.push(`${file}: inline style block`);
      for (const match of content.matchAll(/<script\b([^>]*)>[\s\S]*?<\/script>/gi)) {
        if (isExecutableScript(match[1])) findings.push(`${file}: executable inline script`);
      }
      if (/https:\/\/(?:images\.unsplash\.com|source\.unsplash\.com|picsum\.photos)/i.test(content)) {
        findings.push(`${file}: remote demo image`);
      }
      if (/https:\/\/fonts\.(?:googleapis|gstatic)\.com/i.test(content)) {
        findings.push(`${file}: remote font dependency`);
      }
    }
  }
}

walk(root);
const headers = fs.readFileSync(path.join(root, "security-headers.conf"), "utf8");
for (const directive of ["script-src", "style-src"]) {
  const match = headers.match(new RegExp(`${directive} ([^;]+)`));
  if (!match || match[1].includes("'unsafe-inline'")) findings.push(`security-headers.conf: unsafe ${directive}`);
}
if (findings.length) {
  console.error(findings.join("\n"));
  process.exit(1);
}
console.log("CSP audit passed: no executable inline code, style blocks, remote demo images, or broad unsafe-inline directives.");
