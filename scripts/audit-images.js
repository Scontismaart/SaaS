const fs = require('fs');
const path = require('path');

const landingDir = path.join(process.cwd(), 'web', 'landing');

function findFiles(dir, exts) {
  let res = [];
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const e of entries) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      res = res.concat(findFiles(p, exts));
    } else if (exts.some(ext => e.name.endsWith(ext))) {
      res.push(p);
    }
  }
  return res;
}

const htmlAndCss = findFiles(landingDir, ['.html', '.css']);
const imageMap = {};

for (const file of htmlAndCss) {
  const content = fs.readFileSync(file, 'utf8');
  const relFile = path.relative(process.cwd(), file).replace(/\\/g, '/');
  
  // Find img src
  const imgRegex = /<img[^>]+src=["']([^"']+)["']/gi;
  let m;
  while ((m = imgRegex.exec(content)) !== null) {
    const src = m[1];
    if (!imageMap[src]) imageMap[src] = new Set();
    imageMap[src].add(relFile);
  }

  // Find background url()
  const bgRegex = /url\(["']?([^"')]+)["']?\)/gi;
  while ((m = bgRegex.exec(content)) !== null) {
    const src = m[1];
    if (src.match(/\.(webp|png|jpg|jpeg|svg)$/i)) {
      if (!imageMap[src]) imageMap[src] = new Set();
      imageMap[src].add(relFile);
    }
  }
}

console.log(JSON.stringify(
  Object.fromEntries(
    Object.entries(imageMap).map(([k, v]) => [k, Array.from(v).slice(0, 5)])
  ),
  null,
  2
));
