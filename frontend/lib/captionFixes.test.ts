import assert from "node:assert/strict";
import { test } from "node:test";
import { MAX_FIX_CHARS, captionText, fixFor, setFix } from "./captionFixes.ts";

const a = { start: 1, end: 3.5, text: " My name is Huan." };
const b = { start: 4, end: 6, text: "Welcome back." };

test("a correction replaces what the captions say for that sentence only", () => {
  const fixes = setFix([], a, "My name is Juan.");
  assert.deepEqual(fixes, [{ start: 1, end: 3.5, text: "My name is Juan." }]);
  assert.equal(captionText(fixes, a), "My name is Juan.");
  assert.equal(captionText(fixes, b), "Welcome back.");
  assert.equal(fixFor(fixes, b), undefined);
});

test("correcting again replaces, and typing back what was heard removes it", () => {
  let fixes = setFix(setFix([], b, "Welcome back!"), a, "x");
  assert.deepEqual(fixes.map((f) => f.start), [1, 4]); // in time order
  fixes = setFix(fixes, a, "My name is Juan Dela Cruz.");
  assert.equal(fixes.length, 2);
  fixes = setFix(fixes, a, "  My name   is Huan. ");
  assert.deepEqual(fixes, [{ start: 4, end: 6, text: "Welcome back!" }]);
});

test("empty text hides the caption, and very long text is cut to the limit", () => {
  assert.deepEqual(setFix([], b, "   "), [{ start: 4, end: 6, text: "" }]);
  assert.equal(captionText(setFix([], b, ""), b), "");
  assert.equal(setFix([], b, "a".repeat(2000))[0].text.length, MAX_FIX_CHARS);
});
