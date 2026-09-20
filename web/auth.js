const AUTH_API_BASE =
  typeof window !== "undefined" && typeof window.MELPIS_API_BASE === "string"
    ? window.MELPIS_API_BASE
    : "";

if (typeof window !== "undefined" && window.MELPIS_API_BASE === undefined) {
  console.warn("[Auth] window.MELPIS_API_BASE non definita, fallback sicuro su same-origin ('')");
}

const AUTH_PARAMS = new URLSearchParams(window.location.search);
const NEXT_PATH = safeNext(AUTH_PARAMS.get("next"));

function safeNext(raw) {
  if (
    raw &&
    raw.startsWith("/") &&
    !raw.startsWith("//") &&
    !raw.includes("\\") &&
    !raw.includes("://")
  ) {
    return raw;
  }
  return "/app/";
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
