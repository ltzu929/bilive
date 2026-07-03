import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("manifest uses Eagle window-plugin main object", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("../manifest.json", import.meta.url), "utf8"),
  );

  assert.equal(manifest.platform, "all");
  assert.equal(manifest.arch, "all");
  assert.equal(manifest.devTools, true);
  assert.equal(typeof manifest.main, "object");
  assert.equal(manifest.main.url, "index.html");
  assert.equal(manifest.main.devTools, true);
  assert.equal(manifest.main.backgroundColor, "#f8fafc");
});
