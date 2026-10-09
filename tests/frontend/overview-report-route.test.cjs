const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(path.resolve(__dirname, "../../web/app.js"), "utf8");

test("report initially loads only when Overview is activated", () => {
  const overview = source.match(/if \(viewName === "panoramica"\) \{([\s\S]*?)\n  \} else \{/);
  assert.ok(overview, "Overview activation block exists");
  assert.match(overview[1], /\baggiornaReport\(\)/);

  const boot = source.match(/dashboardRouter\.start\(\);([\s\S]*?)\n\}\)\(\);/);
  assert.ok(boot, "authenticated bootstrap exists");
  assert.doesNotMatch(boot[1], /\baggiornaReport\(\)/);
});

test("simulator still refreshes the report after sending a message", () => {
  const simulatorSource = fs.readFileSync(path.resolve(__dirname, "../../web/dashboard-ai-simulator.js"), "utf8");
  const simulator = simulatorSource.match(/async function inviaMessaggio\(testo\) \{([\s\S]*?)\n {6}\}/);
  assert.ok(simulator, "simulator send handler exists");
  assert.match(simulator[1], /await aggiornaReport\(\)/);
});
