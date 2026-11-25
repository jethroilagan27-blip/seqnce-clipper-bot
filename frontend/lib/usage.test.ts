import assert from "node:assert/strict";
import { test } from "node:test";
import { aiRequests, dayLabel, edits, labelledDays, niceTicks, parseLimit } from "./usage.ts";

test("video edits count new videos and changes; AI requests count both kinds of key", () => {
  const c = { videos: 2, changes: 3, ai: 4, ai_own: 1 };
  assert.equal(edits(c), 5);
  assert.equal(aiRequests(c), 5);
});

test("gridlines are whole, round numbers that reach the highest value", () => {
  assert.deepEqual(niceTicks(0), [0, 1]);
  assert.deepEqual(niceTicks(3), [0, 1, 2, 3]);
  assert.deepEqual(niceTicks(18), [0, 5, 10, 15, 20]);
  assert.deepEqual(niceTicks(230), [0, 100, 200, 300]);
  for (const max of [1, 7, 11, 99, 1001]) assert.ok(niceTicks(max).at(-1)! >= max && niceTicks(max).length <= 6, String(max));
});

test("days are calendar days, and the first and last are always labelled", () => {
  assert.equal(dayLabel("2026-11-05", "en-US"), "Nov 5");
  assert.deepEqual(labelledDays(30, 4), [0, 10, 19, 29]);
  assert.deepEqual(labelledDays(3, 8), [0, 1, 2]);
  assert.deepEqual(labelledDays(1, 4), [0]);
  assert.deepEqual(labelledDays(0, 4), []);
});

test("an empty limit follows the plan; anything but a whole number in range is refused", () => {
  assert.equal(parseLimit("  "), null);
  assert.equal(parseLimit("0"), 0);
  assert.equal(parseLimit("25"), 25);
  for (const bad of ["-1", "2.5", "ten", "10001", "1e3"]) assert.equal(parseLimit(bad), undefined, bad);
});
