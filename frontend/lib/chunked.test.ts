import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_UPLOAD_CONFIG, PieceError, isRetryable, parseUploadConfig, planPieces, sendPieces, shouldChunk } from "./chunked.ts";

const MB = 1024 * 1024;

test("your own computer never sends in pieces", () => {
  const local = parseUploadConfig({ max_mb: 500, chunk_mb: null });
  assert.equal(local.chunkMb, null);
  assert.equal(shouldChunk(5 * 1024 * MB, local), false); // however big the file
  assert.equal(shouldChunk(1, local), false);
  assert.equal(shouldChunk(900 * MB, DEFAULT_UPLOAD_CONFIG), false);
});

test("an older server without the upload block counts as your own computer", () => {
  assert.deepEqual(parseUploadConfig(undefined), { maxMb: 500, chunkMb: null });
  assert.deepEqual(parseUploadConfig({}), { maxMb: 500, chunkMb: null });
  assert.deepEqual(parseUploadConfig({ max_mb: "x", chunk_mb: -3 }), { maxMb: 500, chunkMb: null });
});

test("the public setup sends only files bigger than one piece in pieces", () => {
  const pub = parseUploadConfig({ max_mb: 2048, chunk_mb: 50 });
  assert.deepEqual(pub, { maxMb: 2048, chunkMb: 50 });
  assert.equal(shouldChunk(50 * MB, pub), false); // exactly one piece: a normal upload is fine
  assert.equal(shouldChunk(50 * MB + 1, pub), true);
  assert.equal(shouldChunk(10 * MB, pub), false);
});

test("pieces cover the file exactly", () => {
  const pieces = planPieces(120, 50);
  assert.deepEqual(pieces, [
    { index: 0, start: 0, end: 50 },
    { index: 1, start: 50, end: 100 },
    { index: 2, start: 100, end: 120 },
  ]);
  assert.deepEqual(planPieces(100, 50).map((p) => p.end - p.start), [50, 50]);
  assert.deepEqual(planPieces(0, 50), []);
});

test("which errors are worth trying again", () => {
  assert.equal(isRetryable(new PieceError("offline")), true);
  assert.equal(isRetryable(new PieceError("busy", 503)), true);
  assert.equal(isRetryable(new PieceError("slow", 429)), true);
  assert.equal(isRetryable(new PieceError("no", 413)), false);
  assert.equal(isRetryable(new PieceError("sign in", 401)), false);
  assert.equal(isRetryable(new Error("other")), false);
});

test("sending skips pieces the server has and reports progress up to 1", async () => {
  const sent: number[] = [];
  const progress: number[] = [];
  await sendPieces({
    size: 100,
    chunkBytes: 40,
    received: [1],
    putPiece: async (p, onBytes) => {
      onBytes(p.end - p.start);
      sent.push(p.index);
    },
    onProgress: (f) => progress.push(f),
  });
  assert.deepEqual(sent, [0, 2]);
  assert.equal(progress[0], 40 / 100); // what the server already had
  assert.equal(progress.at(-1), 1);
  assert.ok(progress.every((f, i) => i === 0 || f >= progress[i - 1]));
});

test("a dropped connection is retried and then carries on", async () => {
  let calls = 0;
  const waits: number[] = [];
  await sendPieces({
    size: 10,
    chunkBytes: 10,
    putPiece: async () => {
      calls += 1;
      if (calls < 3) throw new PieceError("offline");
    },
    onProgress: () => {},
    pause: async (ms) => void waits.push(ms),
  });
  assert.equal(calls, 3);
  assert.equal(waits.length, 2);
});

test("a refusal is not retried, and giving up throws the last error", async () => {
  let calls = 0;
  await assert.rejects(
    sendPieces({
      size: 10, chunkBytes: 10, onProgress: () => {}, pause: async () => {},
      putPiece: async () => { calls += 1; throw new PieceError("too big", 413); },
    }),
    /too big/,
  );
  assert.equal(calls, 1);
  calls = 0;
  await assert.rejects(
    sendPieces({
      size: 10, chunkBytes: 10, tries: 3, onProgress: () => {}, pause: async () => {},
      putPiece: async () => { calls += 1; throw new PieceError("offline"); },
    }),
    /offline/,
  );
  assert.equal(calls, 3);
});

test("cancelling stops before the next piece", async () => {
  let cancelled = false;
  const sent: number[] = [];
  await assert.rejects(
    sendPieces({
      size: 90, chunkBytes: 30, onProgress: () => {}, isCancelled: () => cancelled,
      putPiece: async (p) => { sent.push(p.index); cancelled = true; },
    }),
    /cancelled/,
  );
  assert.deepEqual(sent, [0]);
});
