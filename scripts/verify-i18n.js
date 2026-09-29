#!/usr/bin/env node
/**
 * Melpis — i18n Translation Keys Parity & Structural Verifier
 * Validates that all target locales (en, es, fr, de) strictly match the
 * schema and key structure of the source locale (it).
 */

const fs = require('fs');
const path = require('path');

const LOCALES_DIR = path.resolve(__dirname, '../locales');
const SOURCE_LANG = 'it';
const TARGET_LANGS = ['en', 'es', 'fr', 'de'];

function getJsonFiles(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir)
    .filter(file => file.endsWith('.json') && file !== 'glossary.json');
}

function flattenKeys(obj, prefix = '') {
  let keys = {};
  for (const key of Object.keys(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (obj[key] !== null && typeof obj[key] === 'object' && !Array.isArray(obj[key])) {
      Object.assign(keys, flattenKeys(obj[key], fullKey));
    } else {
      keys[fullKey] = obj[key];
    }
  }
  return keys;
}

let hasError = false;
let totalChecks = 0;

console.log('🔍 [Melpis i18n Verifier] Starting schema and key integrity check...\n');

const sourceDir = path.join(LOCALES_DIR, SOURCE_LANG);
if (!fs.existsSync(sourceDir)) {
  console.error(`❌ Source locale directory not found: ${sourceDir}`);
  process.exit(1);
}

const sourceFiles = getJsonFiles(sourceDir);
if (sourceFiles.length === 0) {
  console.error(`❌ No namespace files found in source locale: ${sourceDir}`);
  process.exit(1);
}

console.log(`Source locale (${SOURCE_LANG}): found ${sourceFiles.length} namespaces: ${sourceFiles.join(', ')}`);

// Optional filter if user passes single language as arg: node scripts/verify-i18n.js en
const targetLangsToCheck = process.argv[2]
  ? [process.argv[2]]
  : TARGET_LANGS;

for (const lang of targetLangsToCheck) {
  console.log(`\nChecking locale: [${lang.toUpperCase()}]`);
  const langDir = path.join(LOCALES_DIR, lang);

  if (!fs.existsSync(langDir)) {
    console.warn(`⚠️  Directory missing for locale: ${langDir}`);
    hasError = true;
    continue;
  }

  const langFiles = getJsonFiles(langDir);

  // 1. Check for missing namespaces
  for (const file of sourceFiles) {
    if (!langFiles.includes(file)) {
      console.error(`  ❌ Missing namespace file: ${lang}/${file}`);
      hasError = true;
      continue;
    }

    const sourceContent = JSON.parse(fs.readFileSync(path.join(sourceDir, file), 'utf8'));
    let targetContent;
    try {
      targetContent = JSON.parse(fs.readFileSync(path.join(langDir, file), 'utf8'));
    } catch (e) {
      console.error(`  ❌ Malformed JSON syntax in: ${lang}/${file} - ${e.message}`);
      hasError = true;
      continue;
    }

    const sourceFlat = flattenKeys(sourceContent);
    const targetFlat = flattenKeys(targetContent);

    const missingKeys = [];
    const extraKeys = [];

    for (const key of Object.keys(sourceFlat)) {
      totalChecks++;
      if (!(key in targetFlat)) {
        missingKeys.push(key);
      } else if (typeof sourceFlat[key] !== typeof targetFlat[key]) {
        console.error(`  ❌ Type mismatch at ${lang}/${file} [${key}]: expected ${typeof sourceFlat[key]}, got ${typeof targetFlat[key]}`);
        hasError = true;
      }
    }

    for (const key of Object.keys(targetFlat)) {
      if (!(key in sourceFlat)) {
        extraKeys.push(key);
      }
    }

    if (missingKeys.length > 0) {
      console.error(`  ❌ [${lang}/${file}] Missing ${missingKeys.length} keys:`);
      missingKeys.forEach(k => console.error(`      - ${k}`));
      hasError = true;
    }

    if (extraKeys.length > 0) {
      console.warn(`  ⚠️  [${lang}/${file}] Extra / orphan ${extraKeys.length} keys:`);
      extraKeys.forEach(k => console.warn(`      + ${k}`));
      // Extra keys are warned but can fail if strict
      hasError = true;
    }

    if (missingKeys.length === 0 && extraKeys.length === 0) {
      console.log(`  ✓ ${file} (${Object.keys(sourceFlat).length} keys verified)`);
    }
  }

  // 2. Check for extra namespace files in target
  for (const file of langFiles) {
    if (!sourceFiles.includes(file)) {
      console.warn(`  ⚠️  Extra namespace file found in ${lang}: ${file}`);
      hasError = true;
    }
  }
}

console.log('\n────────────────────────────────────────────────────────────');
if (hasError) {
  console.error(`❌ i18n Verification FAILED. Please resolve missing keys or structure issues above.\n`);
  process.exit(1);
} else {
  console.log(`✅ i18n Verification PASSED! ${totalChecks} keys verified across checked locales.\n`);
  process.exit(0);
}
