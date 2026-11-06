import assert from "node:assert/strict";
import { test } from "node:test";
import {
  addRange,
  clipsEqual,
  cutIndexAtOut,
  isKept,
  mergeClips,
  outToSource,
  pageAt,
  rulerStep,
  setEdge,
  snapToWords,
  sourceToOut,
  subtractRange,
  toggleRange,
  type DraftClip,
} from "./timeline.ts";

const clip = (start: number, end: number): DraftClip => ({ start, end, purpose: "main_content", reason: "" });
const span = (cs: DraftClip[]) => cs.map((c) => [c.start, c.end]);

test("mergeClips sorts and merges overlapping or touching clips", () => {
  assert.deepEqual(span(mergeClips([clip(20, 30), clip(2, 8), clip(8.03, 12)])), [[2, 12], [20, 30]]);
  assert.deepEqual(span(mergeClips([clip(0, 10), clip(2, 4)])), [[0, 10]]);
});

test("subtractRange splits a clip and drops pieces that are too short", () => {
  assert.deepEqual(span(subtractRange([clip(0, 20)], 8, 12)), [[0, 8], [12, 20]]);
  assert.deepEqual(span(subtractRange([clip(0, 20)], 0.5, 12)), [[12, 20]]); // 0.5 s leftover is dropped
  assert.deepEqual(span(subtractRange([clip(0, 20)], 0, 20)), []);
  assert.deepEqual(span(subtractRange([clip(0, 5), clip(10, 15)], 6, 9)), [[0, 5], [10, 15]]); // untouched
});

test("addRange merges with neighbours and grows tiny sentences to a valid clip", () => {
  assert.deepEqual(span(addRange([clip(0, 5)], 5.02, 9, 60)), [[0, 9]]);
  const grown = addRange([], 10, 10.4, 60);
  assert.equal(grown.length, 1);
  assert.ok(grown[0].end - grown[0].start >= 1);
  assert.deepEqual(span(addRange([], -3, 70, 60)), [[0, 60]]);
});

test("toggleRange keeps a cut sentence and cuts a kept one", () => {
  const clips = [clip(0, 20)];
  const cut = toggleRange(clips, { start: 8, end: 12 }, 60);
  assert.equal(isKept(cut, { start: 8, end: 12 }), false);
  const back = toggleRange(cut, { start: 8, end: 12 }, 60);
  assert.deepEqual(span(back), [[0, 20]]);
});

test("setEdge respects neighbours, the video and the minimum length", () => {
  const clips = [clip(2, 10), clip(14, 20)];
  assert.equal(setEdge(clips, 0, "end", 99, 60)[0].end, 13.95); // stops before the next clip
  assert.equal(setEdge(clips, 0, "end", 2.2, 60)[0].end, 3); // keeps >= 1 s
  assert.equal(setEdge(clips, 1, "start", 0, 60)[1].start, 10.05); // stops after the previous clip
  assert.equal(setEdge(clips, 0, "start", -4, 60)[0].start, 0);
  assert.equal(setEdge(clips, 1, "end", 99, 30)[1].end, 30);
  assert.equal(setEdge(clips, 5, "end", 1, 60), clips); // unknown index: unchanged
});

test("snapToWords only snaps within tolerance", () => {
  assert.equal(snapToWords(5.04, [4, 5, 6], 0.1), 5);
  assert.equal(snapToWords(5.3, [4, 5, 6], 0.1), 5.3);
});

test("clipsEqual ignores tiny float noise", () => {
  assert.ok(clipsEqual([clip(1, 2)], [clip(1.001, 2)]));
  assert.ok(!clipsEqual([clip(1, 2)], [clip(1, 2), clip(3, 4)]));
});

const cuts = [
  { start: 2, end: 6, out_start: 0 },
  { start: 10, end: 13, out_start: 4 },
];

test("output <-> source time mapping", () => {
  assert.equal(cutIndexAtOut(cuts, 3.9), 0);
  assert.equal(cutIndexAtOut(cuts, 4), 1);
  assert.equal(outToSource(cuts, 1), 3);
  assert.equal(outToSource(cuts, 5.5), 11.5);
  assert.equal(outToSource(cuts, 99), 13); // clamped to the end of the last cut
  assert.equal(sourceToOut(cuts, 3), 1);
  assert.equal(sourceToOut(cuts, 8), 4); // between cuts -> start of the next one
  assert.equal(sourceToOut(cuts, 50), 7); // past the end -> total length
  assert.equal(sourceToOut([], 3), 0);
});

test("pageAt and rulerStep", () => {
  const pages = [{ start: 0, end: 1, text: "a" }, { start: 1, end: 2, text: "b" }];
  assert.equal(pageAt(pages, 1)?.text, "b");
  assert.equal(pageAt(pages, 5), null);
  assert.equal(rulerStep(100), 1); // zoomed in: 1 s labels would be 100 px apart
  assert.equal(rulerStep(2), 60); // zoomed out
});

import { PURPOSE_LABEL, contextWindow, niceStep, snippetFor } from "./timeline.ts";

test("snippetFor joins the sentences inside a range and truncates", () => {
  const segs = [
    { start: 0, end: 4, text: " Hello there." },
    { start: 5, end: 9, text: "General Kenobi." },
    { start: 20, end: 24, text: "Elsewhere." },
  ];
  assert.equal(snippetFor(segs, { start: 0, end: 10 }), "Hello there. General Kenobi.");
  assert.equal(snippetFor(segs, { start: 0, end: 10 }, 12), "Hello there…");
  assert.equal(snippetFor(segs, { start: 12, end: 15 }), "");
});

test("contextWindow pads the clip and stays inside the video", () => {
  assert.deepEqual(contextWindow({ start: 100, end: 110 }, 500), { start: 94, end: 116 }); // pad = max(6, 3.5)
  assert.deepEqual(contextWindow({ start: 2, end: 10 }, 12), { start: 0, end: 12 });
  const w = contextWindow({ start: 100, end: 400 }, 500); // pad capped at 30 s
  assert.deepEqual(w, { start: 70, end: 430 });
});

test("niceStep and labels", () => {
  assert.equal(niceStep(12), 2);
  assert.equal(niceStep(300), 60);
  assert.equal(PURPOSE_LABEL.hook, "Opening hook");
});
