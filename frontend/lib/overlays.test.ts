import assert from "node:assert/strict";
import { test } from "node:test";
import { charsPerLine, clamp01, newText, snapCenter, visibleAt, wrapText } from "./overlays.ts";

test("charsPerLine matches the backend estimate", () => {
  assert.equal(charsPerLine(7), 22); // floor(90 / (7 * 0.56))
  assert.equal(charsPerLine(25), 6);
  assert.equal(charsPerLine(2), 80);
});

test("wrapText breaks on the estimated width, keeps explicit breaks and splits long words", () => {
  const wrapped = wrapText("one two three four five six seven eight nine ten", 7);
  assert.ok(wrapped.split("\n").every((l) => l.length <= 22));
  assert.ok(wrapped.split("\n").length >= 3);
  assert.equal(wrapText("a\nb", 7), "a\nb");
  assert.ok(wrapText("x".repeat(60), 7).includes("\n"));
  assert.equal(wrapText("short", 7), "short");
});

test("visibleAt and snapCenter and clamp01", () => {
  assert.ok(visibleAt({ start: 1, end: 3 }, 2, 10));
  assert.ok(!visibleAt({ start: 1, end: 3 }, 3.5, 10));
  assert.ok(visibleAt({ start: 0, end: null }, 9.9, 10));
  assert.ok(!visibleAt({ start: 0, end: null }, 11, 10));
  assert.equal(snapCenter(0.51), 0.5);
  assert.equal(snapCenter(0.6), 0.6);
  assert.equal(clamp01(-1), 0);
  assert.equal(clamp01(2), 1);
});

test("newText gives unique ids and sensible defaults", () => {
  const a = newText();
  const b = newText({ text: "Hi", y: 0.8 });
  assert.notEqual(a.id, b.id);
  assert.equal(b.text, "Hi");
  assert.equal(b.y, 0.8);
  assert.equal(a.end, null);
});
