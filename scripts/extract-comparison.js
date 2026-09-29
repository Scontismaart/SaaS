const fs = require('fs');
const path = require('path');

const locales = ['it', 'en', 'es', 'fr', 'de'];
const data = {};

for (const lang of locales) {
  const dir = path.join(process.cwd(), 'locales', lang);
  data[lang] = {
    landing: JSON.parse(fs.readFileSync(path.join(dir, 'landing.json'), 'utf8')),
    pricing: JSON.parse(fs.readFileSync(path.join(dir, 'pricing.json'), 'utf8')),
    sectors: JSON.parse(fs.readFileSync(path.join(dir, 'sectors.json'), 'utf8')),
    common: JSON.parse(fs.readFileSync(path.join(dir, 'common.json'), 'utf8'))
  };
}

console.log('=== HOMEPAGE HERO ===');
locales.forEach(l => {
  console.log(`[${l.toUpperCase()}] H1: ${data[l].landing.hero.title}`);
  console.log(`[${l.toUpperCase()}] Sub: ${data[l].landing.hero.subtitle}`);
  console.log(`[${l.toUpperCase()}] CTA Primary: ${data[l].landing.hero.cta_primary}`);
  console.log(`[${l.toUpperCase()}] CTA Secondary: ${data[l].landing.hero.cta_secondary}`);
  console.log('---');
});

console.log('\n=== PRICING HERO & PLANS ===');
locales.forEach(l => {
  console.log(`[${l.toUpperCase()}] Title: ${data[l].pricing.hero.title}`);
  console.log(`[${l.toUpperCase()}] Sub: ${data[l].pricing.hero.subtitle}`);
  console.log(`[${l.toUpperCase()}] Plan Essential: ${data[l].pricing.plans.essential.name} -> ${data[l].pricing.plans.essential.description}`);
  console.log(`[${l.toUpperCase()}] Plan Growth: ${data[l].pricing.plans.growth.name} -> ${data[l].pricing.plans.growth.description}`);
  console.log(`[${l.toUpperCase()}] Plan Scale: ${data[l].pricing.plans.scale.name} -> ${data[l].pricing.plans.scale.description}`);
  console.log('---');
});

console.log('\n=== SECTORS HEROES ===');
locales.forEach(l => {
  console.log(`[${l.toUpperCase()}] Restaurants: ${data[l].sectors.restaurants.page_title}`);
  console.log(`[${l.toUpperCase()}] Salons: ${data[l].sectors.beauty.page_title}`);
  console.log(`[${l.toUpperCase()}] Medical: ${data[l].sectors.medical.page_title}`);
  console.log(`[${l.toUpperCase()}] Hotels: ${data[l].sectors.hotels.page_title}`);
  console.log('---');
});

console.log('\n=== FINAL CTAS ===');
locales.forEach(l => {
  console.log(`[${l.toUpperCase()}] Title: ${data[l].landing.final_cta.title}`);
  console.log(`[${l.toUpperCase()}] Sub: ${data[l].landing.final_cta.subtitle}`);
  console.log(`[${l.toUpperCase()}] Button: ${data[l].landing.final_cta.button}`);
  console.log('---');
});
