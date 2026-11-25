import assert from "node:assert/strict";
import { test } from "node:test";
import { LENGTHS, framingStyle, lengthLabel, lengthStep, lettering, ratioOf } from "./shape.ts";

test("lengths read as seconds up to 90 and as minutes above", () => {
  assert.deepEqual([15, 90, 120, 150, 600].map(lengthLabel), ["15s", "90s", "2 min", "2 min 30s", "10 min"]);
  assert.equal(LENGTHS[lengthStep(45)], 45);
  assert.equal(LENGTHS[lengthStep(100)], 90);
  assert.equal(LENGTHS[lengthStep(5000)], 600);
});

test("lettering follows the short side of the frame", () => {
  assert.equal(lettering("9:16").scale, 1);
  assert.equal(lettering(undefined).scale, 1);
  assert.ok(Math.abs(lettering("16:9").scale - 9 / 16) < 1e-9);
  assert.equal(lettering("16:9").captionBottom, "8%");
});

test("a wide video is cropped around the action in an upright frame, and never past its edges", () => {
  const style = framingStyle(16 / 9, ratioOf("9:16"), 1, false);
  assert.equal(style.height, "100%");
  assert.ok(Math.abs(parseFloat(String(style.left)) + (256 / 81 - 1) * 100) < 1e-6);
});

test("an upright video in a landscape frame can be shown whole, full height and centred", () => {
  const style = framingStyle(9 / 16, ratioOf("16:9"), 0.5, true);
  assert.equal(style.height, "100%");
  assert.equal(style.transform, "translateX(-50%)");
  assert.equal(style.width, undefined);
});
