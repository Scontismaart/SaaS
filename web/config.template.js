// Generato a build-time dall'entrypoint nginx (envsubst). In produzione
// same-origin il valore è vuoto: le chiamate API vanno a "/api/*" sullo
// stesso dominio (via Traefik), quindi niente CORS e cookie same-site.
// In dev locale (senza Docker) il fallback in app.js resta localhost:8000.
window.MELPIS_API_BASE = "${MELPIS_API_BASE}";