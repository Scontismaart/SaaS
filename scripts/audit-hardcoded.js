const fs = require('fs');
const path = require('path');

// Advisory scan for visible dashboard strings without data-i18n. It deliberately
// reports server-/runtime-populated shell markup (and language names) as possible
// false positives; verify-i18n.js is the blocking locale-schema check.
const html = fs.readFileSync(path.join(process.cwd(), 'web', 'index.html'), 'utf8');
const lines = html.split('\n');

const untranslatedHtml = [];

lines.forEach((line, idx) => {
  const lineNum = idx + 1;
  const trimmed = line.trim();
  // Filter out scripts, styles, comments, empty lines
  if (!trimmed || trimmed.startsWith('<!--') || trimmed.startsWith('<script') || trimmed.startsWith('<style') || trimmed.startsWith('<link') || trimmed.startsWith('<meta') || trimmed.startsWith('<!DOCTYPE')) {
    return;
  }
  // Check if line contains user-visible text (Italian words or English words) and lacks data-i18n
  // Common tags: <button, <a, <span, <p, <h1, <h2, <h3, <h4, <label, <option
  const textTagMatch = line.match(/<(h[1-6]|p|span|button|a|label|option|th|td|div)[^>]*>([^<]+)<\/\1>/i);
  if (textTagMatch) {
    const fullTag = textTagMatch[0];
    const text = textTagMatch[2].trim();
    if (text && !fullTag.includes('data-i18n') && !text.match(/^[\d\s€$.,:/\-%+•—–()]+$/) && !text.match(/^(Melpis|WhatsApp|Google Calendar)$/i)) {
      untranslatedHtml.push({ lineNum, tag: textTagMatch[1], text, line: trimmed });
    }
  }

  // Check placeholder
  const placeholderMatch = line.match(/placeholder=["']([^"']+)["']/i);
  if (placeholderMatch && !line.includes('data-i18n-placeholder')) {
    untranslatedHtml.push({ lineNum, type: 'placeholder', text: placeholderMatch[1], line: trimmed });
  }

  // Check aria-label
  const ariaMatch = line.match(/aria-label=["']([^"']+)["']/i);
  if (ariaMatch && !line.includes('data-i18n-aria-label') && !ariaMatch[1].includes('Select language')) {
    untranslatedHtml.push({ lineNum, type: 'aria-label', text: ariaMatch[1], line: trimmed });
  }
});

console.log('--- Advisory untranslated elements in web/index.html ---');
console.log(`Found ${untranslatedHtml.length} potential items`);
untranslatedHtml.slice(0, 40).forEach(item => {
  console.log(`web/index.html:${item.lineNum} [${item.type || item.tag}] -> "${item.text}"`);
});
