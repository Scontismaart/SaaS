const fs = require('fs');
const path = require('path');

const LANGS = ['en', 'es', 'fr', 'de'];
const DIRS = [
  path.join(process.cwd(), 'web'),
  path.join(process.cwd(), 'web', 'landing')
];

function findHtmlFiles(dir) {
  let results = [];
  if (!fs.existsSync(dir)) return results;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results = results.concat(findHtmlFiles(full));
    } else if (entry.name.endsWith('.html')) {
      results.push(full);
    }
  }
  return results;
}

const itRoutes = [
  '/prezzi/',
  '/settori/ristoranti/',
  '/settori/saloni-bellezza/',
  '/settori/studi-medici/',
  '/settori/hotel/',
  '/documentazione/',
  '/accedi/',
  '/registrati/',
  '/privacy/',
  '/termini/',
  '/cookie/'
];

let issues = [];

for (const base of DIRS) {
  for (const lang of LANGS) {
    const langDir = path.join(base, lang);
    const files = findHtmlFiles(langDir);

    for (const file of files) {
      const content = fs.readFileSync(file, 'utf8');
      // Strip language selector, hreflangs, and courtesy disclaimer
      const noLangSel = content
        .replace(/<div[^>]*class="[^"]*lang-selector-wrap[^"]*"[\s\S]*?<\/div>\s*<\/div>/gi, '')
        .replace(/<div[^>]*class="[^"]*mobile-lang-section[^"]*"[\s\S]*?<\/div>\s*<\/div>/gi, '')
        .replace(/<link[^>]*hreflang[\s\S]*?>/gi, '')
        .replace(/<div[^>]*class="legal-disclaimer-callout"[\s\S]*?<\/div>/gi, '');

      // Check for links to Italian pages
      for (const itRoute of itRoutes) {
        const regex = new RegExp(`href=["']${itRoute}["']`, 'gi');
        let match;
        while ((match = regex.exec(noLangSel)) !== null) {
          issues.push({
            file: path.relative(process.cwd(), file).replace(/\\/g, '/'),
            lang,
            itRoute
          });
        }
      }

      // Also check for href="/" (should be /${lang}/)
      const homeRegex = /href=["']\/["']/gi;
      let homeMatch;
      while ((homeMatch = homeRegex.exec(noLangSel)) !== null) {
        issues.push({
          file: path.relative(process.cwd(), file).replace(/\\/g, '/'),
          lang,
          itRoute: 'href="/"'
        });
      }
    }
  }
}

console.log('Total link bleed issues found:', issues.length);
if (issues.length > 0) {
  console.log(JSON.stringify(issues, null, 2));
}
