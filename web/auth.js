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
