import assert from "node:assert/strict";
import { test } from "node:test";
import {
  VIDEO_EXTENSIONS,
  baseName,
  describePath,
  extensionOf,
  folderOf,
  fromFileList,
  isJunk,
  mergePicked,
  naturalCompare,
  sortPicked,
  splitByExtension,
  type Picked,
} from "./pickFiles.ts";

const pick = (path: string, size = 10): Picked => ({ file: new File([new Uint8Array(size)], baseName(path)), path });

test("paths split into the folder and the name", () => {
  assert.equal(folderOf("Members/Vidal/wide.mov"), "Members/Vidal");
  assert.equal(baseName("Members/Vidal/wide.mov"), "wide.mov");
  assert.equal(folderOf("loose.mp4"), "");
  assert.equal(baseName("loose.mp4"), "loose.mp4");
  assert.deepEqual(describePath("A/b.mp4"), { folder: "A", name: "b.mp4" });
});

test("extensions are read in lower case and only from the last dot", () => {
  assert.equal(extensionOf("Clip.MOV"), ".mov");
  assert.equal(extensionOf("my.holiday.mp4"), ".mp4");
  assert.equal(extensionOf("noextension"), "");
  assert.ok(VIDEO_EXTENSIONS.includes(".mov") && VIDEO_EXTENSIONS.includes(".mp4"));
});

test("natural order puts VO 2 before VO 10 and ignores case", () => {
  const names = ["VO 10.mp3", "vo 2.mp3", "VO 1.mp3"];
  assert.deepEqual(names.slice().sort(naturalCompare), ["VO 1.mp3", "vo 2.mp3", "VO 10.mp3"]);
});

test("sorting goes folder by folder, then by name", () => {
  const sorted = sortPicked([pick("B/z.mp4"), pick("A/y.mp4"), pick("A/x.mp4"), pick("loose.mp4")]);
  assert.deepEqual(sorted.map((p) => p.path), ["loose.mp4", "A/x.mp4", "A/y.mp4", "B/z.mp4"]);
});

test("files the computer makes itself are dropped quietly, other types are reported as skipped", () => {
  const { accepted, skipped } = splitByExtension(
    [pick("A/clip.MOV"), pick("A/notes.txt"), pick("A/.DS_Store"), pick("Thumbs.db"), pick("a.webm"), pick("b.avi")],
    VIDEO_EXTENSIONS,
  );
  assert.deepEqual(accepted.map((p) => p.path), ["A/clip.MOV", "a.webm"]);
  assert.deepEqual(skipped.map((p) => p.path), ["A/notes.txt", "b.avi"]);
  assert.ok(isJunk("x/.hidden") && isJunk("desktop.ini") && !isJunk("holiday.mp4"));
});

test("picking the same file twice does not list it twice, but a different file with the same name does", () => {
  const first = [pick("A/a.mp4", 5)];
  const merged = mergePicked(first, [pick("A/a.mp4", 5), pick("A/a.mp4", 9), pick("A/b.mp4", 5)]);
  assert.deepEqual(merged.map((p) => `${p.path}:${p.file.size}`), ["A/a.mp4:5", "A/a.mp4:9", "A/b.mp4:5"]);
  assert.equal(first.length, 1); // the list it was given is not changed
});

test("files from a folder input keep their place inside the folder", () => {
  const inside = new File(["x"], "wide.mov");
  Object.defineProperty(inside, "webkitRelativePath", { value: "Members/Vidal/wide.mov" });
  const loose = new File(["y"], "solo.mp4");
  assert.deepEqual(fromFileList([inside, loose]).map((p) => p.path), ["Members/Vidal/wide.mov", "solo.mp4"]);
});
