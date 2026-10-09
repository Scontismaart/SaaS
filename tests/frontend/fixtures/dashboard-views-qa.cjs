// Opt-in, loopback-only view smoke data. No DB, provider, model or credentials.
const { ORG_A, ORG_B, FIXED_TIME, readFixtures } = require("./dashboard-visual-api.cjs");
const SCENARIOS = new Set(["populated", "empty", "error", "loading", "denied"]);
function viewReply(method, pathname, scenario, organization = ORG_A) {
  if (!SCENARIOS.has(scenario)) return null;
  if (![ORG_A, ORG_B].includes(organization)) return { status: 403, body: { detail: "Organizzazione QA non autorizzata" } };
  const label = organization === ORG_B ? "B" : "A";
  const review = { id: `synthetic-review-${label}`, autore: `Cliente sintetico ${label}`, testo: `Recensione QA ${label}`, bozza_risposta: "Grazie per il feedback sintetico.", fonte: "google", valutazione_stelle: 4, sentiment: "positiva", categoria: "servizio", stato: "bozza_generata", created_at: FIXED_TIME };
  if (method === "GET" && pathname === "/api/auth/me") return { status: 200, body: { ...readFixtures[pathname], organization_id: organization } };
  if (method === "GET" && pathname === "/api/reviews/google/status") return { status: 200, body: { connected: true, operational: false, account_name: "Google QA sintetico", location_name: "Sede QA sintetica" } };
  if (method === "GET" && ["/api/dashboard", "/api/dashboard/prioritari", "/api/recensioni"].includes(pathname)) {
    if (scenario === "denied" && pathname === "/api/recensioni") return { status: 403, body: { detail: "Accesso alle recensioni QA negato" } };
    if (scenario === "error") return { status: 500, body: { detail: "Errore sintetico QA" } };
    const empty = scenario === "empty";
    const body = pathname === "/api/recensioni" ? { recensioni: empty ? [] : [review] } : empty ? [] : [{ id: review.id, testo_originale: `Attività QA ${label}`, tipo_evento: "recensione", priorita: "alta", gestito_da_ai: false, timestamp: FIXED_TIME, dettagli: { stelle: 4, autore: review.autore, fonte: "google", sentiment: "positiva" } }];
    return { status: 200, body, delayMs: scenario === "loading" ? 3000 : 0 };
  }
  // Only this explicitly synthetic action is accepted; never a generic write mock.
  if (method === "POST" && pathname === `/api/recensioni/${review.id}/approva`) return scenario === "denied" ? { status: 403, body: { detail: "Azione QA non autorizzata" } } : { status: 200, body: { stato: "approvata" } };
  return null;
}
module.exports = { SCENARIOS, viewReply };
