const { test } = require("node:test");
const assert = require("node:assert/strict");
const { interactionReply } = require("../../scripts/dashboard-baseline-server.cjs");
const { reply } = require("./fixtures/dashboard-visual-api.cjs");

test("interaction fixtures are opt-in and leave baseline responses unchanged", () => {
  for (const path of ["/api/auth/me", "/api/auth/logout", "/api/documenti/elenco", "/api/messaggio"]) {
    for (const method of ["GET", "POST", "DELETE"]) {
      assert.deepEqual(interactionReply(method, path, "", false), reply(method, path));
    }
  }
});

test("synthetic logout denies subsequent reads/writes and unapproved mutations stay denied", () => {
  assert.equal(interactionReply("POST", "/api/auth/logout", "", true).signedOut, true);
  for (const method of ["GET", "POST", "DELETE"]) {
    assert.equal(interactionReply(method, "/api/auth/me", "dashboard_qa_signed_out=1", true).status, 401);
  }
  const doc = interactionReply("GET", "/api/documenti/elenco", "", true).body.documenti[0];
  assert.equal(doc.id, "synthetic-document-only");
  assert.equal(interactionReply("DELETE", `/api/documenti/${doc.id}`, "", true).status, 501);
  assert.equal(interactionReply("POST", "/api/bookings", "", true).status, 501);
});
