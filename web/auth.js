const AUTH_API_BASE =
  typeof window !== "undefined" && typeof window.MELPIS_API_BASE === "string"
    ? window.MELPIS_API_BASE
    : "";

if (typeof window !== "undefined" && window.MELPIS_API_BASE === undefined) {
  console.warn("[Auth] window.MELPIS_API_BASE non definita, fallback sicuro su same-origin ('')");
}

const AUTH_PARAMS = new URLSearchParams(window.location.search);
// Nginx places the complete, still-encoded request URI in a fragment because an
// unescaped '&' in a query-valued next would otherwise become a login parameter.
const HASH_NEXT = window.location.hash.startsWith("#next=")
  ? window.location.hash.slice("#next=".length)
  : null;
const NEXT_PATH = safeNext(HASH_NEXT ?? AUTH_PARAMS.get("next"));

function safeNext(raw) {
  if (typeof raw !== "string" || !raw.startsWith("/") || raw.startsWith("//")
    || raw.includes("\\") || /[\u0000-\u001f\u007f]/.test(raw)) return "/app/";

  try {
    const parsed = new URL(raw, window.location.origin);
    if (parsed.origin !== window.location.origin || parsed.username || parsed.password) return "/app/";
    // Avoid browser/server disagreement after percent-decoding path separators,
    // backslashes, or control bytes (including repeatedly encoded forms).
    if (/%(?:25)*(?:0[0-9a-f]|1[0-9a-f]|7f|2f|5c)/i.test(parsed.pathname)) return "/app/";
  } catch {
    return "/app/";
  }
  return raw;
}

function vaiADestinazione() {
  window.location.href = NEXT_PATH;
}

function urlConNext(pathBase) {
  return `${pathBase}?next=${encodeURIComponent(NEXT_PATH)}`;
}

function mostraErrorePagina(msg) {
  const el = document.getElementById("accedi-error");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("visible");
}

function showAuthFieldError(errorElement, message, field) {
  if (!errorElement) return;
  errorElement.textContent = message;
  if (field) {
    field.setAttribute('aria-invalid', 'true');
    field.focus();
  } else {
    errorElement.setAttribute('tabindex', '-1');
    errorElement.focus();
  }
}

function clearAuthFieldError(form, errorElement) {
  if (errorElement) errorElement.textContent = '';
  form?.querySelectorAll('[aria-invalid="true"]').forEach((field) => field.removeAttribute('aria-invalid'));
}

/* Pulsante Google: il round-trip OAuth è gestito dal backend (PKCE). */
function collegaGoogle(elementId = "google-btn") {
  const btn = document.getElementById(elementId);
  if (btn) {
    btn.href = `${AUTH_API_BASE}/api/auth/google/start?next=${encodeURIComponent(NEXT_PATH)}`;
  }
}

/* Localized auth messages loaded dynamically from central i18n bundle */
let _authMessagesCache = null;

function getAuthMessagesBundle() {
  if (_authMessagesCache) return _authMessagesCache;

  // 1. Check for pre-rendered inline JSON bundle injected at build time
  if (typeof document !== 'undefined') {
    const el = document.getElementById('auth-translations');
    if (el && el.textContent) {
      try {
        _authMessagesCache = JSON.parse(el.textContent);
        return _authMessagesCache;
      } catch (e) {
        console.warn('[Auth] Failed to parse #auth-translations', e);
      }
    }
  }

  // 2. Global window object fallback if exposed
  if (typeof window !== 'undefined' && window.__MELPIS_AUTH_MESSAGES__) {
    _authMessagesCache = window.__MELPIS_AUTH_MESSAGES__;
    return _authMessagesCache;
  }

  return null;
}

function getAuthMessage(key) {
  const bundle = getAuthMessagesBundle();
  if (bundle && bundle[key]) {
    return bundle[key];
  }
  return key;
}

// Background prefetch if not inlined
(function prefetchAuthMessages() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return;
  if (document.getElementById('auth-translations')) return;
  const currentLang = document.documentElement.lang || 'it';
  fetch(`/locales/${encodeURIComponent(currentLang)}/auth.json`)
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (data && data.messages) {
        _authMessagesCache = data.messages;
      }
    })
    .catch(() => {});
})();

/* Sync language preference to localStorage and cookie for dashboard continuity */
(function syncAuthLang() {
  if (typeof document === 'undefined') return;
  const currentLang = document.documentElement.lang || 'it';
  if (currentLang && ['it', 'en', 'es', 'fr', 'de'].includes(currentLang)) {
    try { localStorage.setItem('melpis_lang', currentLang); } catch (e) {}
    document.cookie = `melpis_lang=${currentLang}; path=/; max-age=31536000; SameSite=Lax`;
  }
})();
