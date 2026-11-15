import test from "node:test";
import assert from "node:assert/strict";
import {
  creditsScene,
  duplicateScene,
  emptyScene,
  formatMegabytes,
  formatSeconds,
  gridScene,
  moveItem,
  newCell,
  newOverlay,
  newShape,
  newVisual,
  textCardScene,
  uid,
  withoutAsset,
  type Asset,
  type StudioDoc,
} from "./studioDoc.ts";

const asset = (kind: Asset["kind"], id = "a".repeat(16)): Asset => ({ id, kind, name: "x", width: 1, height: 1, duration: 3, has_audio: true, size_bytes: 1 });

test("moveItem moves one item and leaves bad moves alone", () => {
  assert.deepEqual(moveItem([1, 2, 3, 4], 0, 2), [2, 3, 1, 4]);
  assert.deepEqual(moveItem([1, 2, 3, 4], 3, 0), [4, 1, 2, 3]);
  const list = [1, 2, 3];
  assert.equal(moveItem(list, 1, 1), list);
  assert.equal(moveItem(list, -1, 1), list);
  assert.equal(moveItem(list, 0, 3), list);
  assert.deepEqual(list, [1, 2, 3]); // never changes the original
});

test("ids are unique and use only the characters the server allows", () => {
  const ids = new Set(Array.from({ length: 500 }, () => uid("s")));
  assert.equal(ids.size, 500);
  for (const id of ids) assert.match(id, /^[A-Za-z0-9_-]{1,40}$/);
});

test("a text card is a black scene with one centred text", () => {
  const card = textCardScene(2);
  assert.equal(card.visuals.length, 0);
  assert.equal(card.min_duration, 4);
  assert.equal(card.texts.length, 1);
  assert.equal(card.texts[0].x, 0.5);
  assert.equal(card.texts[0].y, 0.5);
  assert.equal(card.name, "Text card 2");
});

test("a new clip keeps its sound, a new picture has none to keep", () => {
  assert.equal(newVisual(asset("video")).volume, 1);
  assert.equal(newVisual(asset("image")).volume, 0);
  assert.equal(newVisual(asset("video")).length, null);
});

test("duplicating a scene gives it and everything inside it new ids", () => {
  const scene = { ...textCardScene(1), visuals: [newVisual(asset("video"))] };
  const copy = duplicateScene(scene, 2);
  assert.notEqual(copy.id, scene.id);
  assert.notEqual(copy.visuals[0].id, scene.visuals[0].id);
  assert.notEqual(copy.texts[0].id, scene.texts[0].id);
  assert.equal(copy.visuals[0].asset_id, scene.visuals[0].asset_id);
  assert.ok(copy.name.length <= 80);
});

test("removing a file removes every use of it", () => {
  const a = "a".repeat(16);
  const b = "b".repeat(16);
  const doc: StudioDoc = {
    title: "t",
    shape: "landscape",
    normalize_loudness: true,
    bed_music: { asset_id: a, start: 0, volume: 0.2, fade_out: 2, duck: true },
    scenes: [
      {
        ...emptyScene(1),
        visuals: [newVisual(asset("video", a)), newVisual(asset("image", b))],
        voiceover: { asset_id: a, volume: 1, offset: 0 },
        music: { asset_id: b, start: 0, volume: 0.5, fade_in: 0, fade_out: 0, duck: true },
      },
    ],
  };
  const out = withoutAsset(doc, a);
  assert.deepEqual(out.scenes[0].visuals.map((v) => v.asset_id), [b]);
  assert.equal(out.scenes[0].voiceover, null);
  assert.equal(out.bed_music, null);
  assert.equal(out.scenes[0].music?.asset_id, b);
  assert.equal(doc.scenes[0].visuals.length, 2); // the original is untouched
});

test("the new scene kinds start with sensible contents", () => {
  const grid = gridScene(3);
  assert.deepEqual([grid.grid?.cols, grid.grid?.rows, grid.grid?.cells.length], [3, 2, 0]);
  const credits = creditsScene(4);
  assert.ok(credits.credits && credits.credits.lines.length >= 2 && credits.credits.seconds === null);
  assert.equal(emptyScene(1).open_effect, "none");
  const pin = newShape("pin");
  assert.equal(pin.anim, "drop"); // a pin falls in
  assert.ok(pin.y > pin.h); // and points at its (x, y): it needs room above
  assert.equal(newShape("rect").fill, 0.3); // a box is a highlighter by default
  assert.deepEqual([newOverlay(asset("image")).x, newOverlay(asset("image")).end], [0.5, null]);
  const cell = newCell(asset("video"));
  assert.deepEqual([cell.fit, cell.volume], ["crop", 0]); // grid cells are cut to fill and silent
});

test("duplicating and removing files also reach pictures over the scene and grid cells", () => {
  const a = "a".repeat(16);
  const b = "b".repeat(16);
  const scene = { ...gridScene(1), overlays: [newOverlay(asset("image", a)), newOverlay(asset("image", b))], shapes: [newShape("rect")] };
  scene.grid = { cols: 3, rows: 2, gap: 8, delay: 0, cells: [newCell(asset("video", a)), newCell(asset("video", b))] };
  const copy = duplicateScene(scene, 2);
  assert.notEqual(copy.overlays[0].id, scene.overlays[0].id);
  assert.notEqual(copy.shapes[0].id, scene.shapes[0].id);
  assert.notEqual(copy.grid?.cells[0].id, scene.grid!.cells[0].id);
  const doc: StudioDoc = { title: "t", shape: "landscape", normalize_loudness: true, bed_music: null, scenes: [scene] };
  const out = withoutAsset(doc, a);
  assert.deepEqual(out.scenes[0].overlays.map((o) => o.asset_id), [b]);
  assert.deepEqual(out.scenes[0].grid?.cells.map((c) => c.asset_id), [b]);
  assert.equal(doc.scenes[0].overlays.length, 2);
});

test("time and size are shown in plain words", () => {
  assert.equal(formatSeconds(4.04), "4.0 s");
  assert.equal(formatSeconds(75.3), "1:15.3");
  assert.equal(formatSeconds(60), "1:00.0");
  assert.equal(formatMegabytes(1536 * 1024), "1.5 MB");
  assert.equal(formatMegabytes(250 * 1024 * 1024), "250 MB");
});
