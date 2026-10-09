const { test } = require("node:test");
const assert = require("node:assert/strict");
const { viewReply } = require("./fixtures/dashboard-views-qa.cjs");
const { ORG_A, ORG_B } = require("./fixtures/dashboard-visual-api.cjs");

test("view QA cases are explicit, synthetic and scoped; unknown cases/writes have no reply", () => {
  assert.equal(viewReply("GET", "/api/dashboard", "unknown"), null);
  assert.equal(viewReply("POST", "/api/bookings", "populated"), null);
  assert.equal(viewReply("POST", "/api/recensioni/real-record/approva", "populated"), null);
  assert.equal(viewReply("GET", "/api/dashboard", "populated", "foreign").status, 403);
  assert.match(viewReply("GET", "/api/dashboard", "populated", ORG_A).body[0].testo_originale, /QA A/);
  assert.match(viewReply("GET", "/api/dashboard", "populated", ORG_B).body[0].testo_originale, /QA B/);
});
test("view QA supplies observable loading, empty, error, denied and non-operational provider states", () => {
  assert.equal(viewReply("GET", "/api/recensioni", "loading").delayMs, 3000);
  assert.deepEqual(viewReply("GET", "/api/recensioni", "empty").body, { recensioni: [] });
  assert.equal(viewReply("GET", "/api/recensioni", "error").status, 500);
  assert.equal(viewReply("GET", "/api/recensioni", "denied").status, 403);
  assert.deepEqual(viewReply("GET", "/api/reviews/google/status", "populated").body.operational, false);
});
