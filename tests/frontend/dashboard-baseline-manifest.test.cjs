const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");

const baselineRoot = path.join(__dirname, "baselines", "dashboard-01");
const manifestPath = path.join(baselineRoot, "manifest.json");

function jpegDimensions(buffer) {
  assert.equal(buffer[0], 0xff, "JPEG starts with SOI marker prefix");
  assert.equal(buffer[1], 0xd8, "JPEG starts with SOI marker");
  const startOfFrameMarkers = new Set([
    0xc0, 0xc1, 0xc2, 0xc3,
    0xc5, 0xc6, 0xc7,
    0xc9, 0xca, 0xcb,
    0xcd, 0xce, 0xcf,
  ]);

  let offset = 2;
  while (offset < buffer.length) {
    assert.equal(buffer[offset], 0xff, `expected JPEG marker at byte ${offset}`);
    while (buffer[offset] === 0xff) offset += 1;
    const marker = buffer[offset];
    offset += 1;

    if (marker === 0xd9 || marker === 0xda) break;
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;

    assert.ok(offset + 1 < buffer.length, "JPEG segment has a length field");
    const length = buffer.readUInt16BE(offset);
    assert.ok(length >= 2 && offset + length <= buffer.length, "JPEG segment length is valid");
    if (startOfFrameMarkers.has(marker)) {
      assert.ok(length >= 7, "JPEG frame header includes dimensions");
      const data = offset + 2;
      return {
        width: buffer.readUInt16BE(data + 3),
        height: buffer.readUInt16BE(data + 1),
      };
    }
    offset += length;
  }
  throw new Error("JPEG has no supported Start Of Frame marker");
}

test("dashboard visual baseline manifest maps twelve correctly sized JPEGs", () => {
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  assert.equal(manifest.schema_version, 1);
  assert.equal(manifest.baseline_set, "dashboard-01");
  assert.equal(manifest.capture.locale, "it");
  assert.equal(manifest.capture.theme, "dark");
  assert.equal(manifest.capture.fixed_time, "2026-10-08T10:00:00.000Z");
  assert.equal(manifest.capture.identity.role, "owner");
  assert.match(manifest.capture.identity.email, /@dashboard-qa\.invalid$/);
  assert.equal(manifest.capture.dataset_profile, "empty");
  assert.deepEqual(manifest.capture.viewports, {
    desktop: { width: 1440, height: 900 },
    mobile: { width: 375, height: 812 },
  });

  assert.deepEqual(manifest.cases.map(({ id }) => id), [
    "overview", "inbox", "bookings", "settings", "simulator", "sidebar",
  ]);
  const entries = manifest.cases.flatMap((captureCase) => Object.entries(captureCase.images)
    .map(([viewport, filename]) => ({ captureCase, viewport, filename })));
  assert.equal(entries.length, 12);
  assert.equal(new Set(entries.map(({ filename }) => filename)).size, 12);

  for (const { captureCase, viewport, filename } of entries) {
    assert.ok(["desktop", "mobile"].includes(viewport));
    assert.match(filename, new RegExp(`^${viewport}-${captureCase.id}\\.jpg$`));
    const target = path.resolve(baselineRoot, filename);
    assert.ok(target.startsWith(`${baselineRoot}${path.sep}`), "manifest file stays inside its baseline directory");
    assert.ok(fs.existsSync(target), `${filename} exists`);
    assert.equal(createHash("sha256").update(fs.readFileSync(target)).digest("hex"), manifest.image_sha256[filename],
      `${filename} matches the reviewed immutable artifact`);
    const expected = manifest.capture.viewports[viewport];
    assert.deepEqual(jpegDimensions(fs.readFileSync(target)), {
      width: expected.width,
      height: expected.height,
    }, `${filename} dimensions match ${viewport} capture metadata`);
  }
});
