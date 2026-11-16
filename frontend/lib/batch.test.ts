import assert from "node:assert/strict";
import { test } from "node:test";
import { createBatch, isBusyMessage, isLimitMessage, makeRows, type Batch, type BatchDeps, type BatchRow, type JobPoll } from "./batch.ts";
import type { Picked } from "./pickFiles.ts";

const items = (...names: string[]): Picked[] => names.map((n) => ({ file: new File(["x"], n.split("/").pop()!), path: n }));

type Script = { uploads: (string | Error)[]; jobs: Record<string, JobPoll[]> };

/** Stand-in server: each upload returns the next scripted job id (or fails); each poll returns the next scripted state. */
function fake(script: Script) {
  const log: string[] = [];
  const deps: BatchDeps<{ seconds: number }> = {
    upload: (file, settings) => {
      const next = script.uploads.shift();
      log.push(`upload ${file.name} (${settings.seconds}s)`);
      return { promise: next instanceof Error ? Promise.reject(next) : Promise.resolve(String(next)), abort: () => log.push("abort") };
    },
    poll: async (id) => {
      const queue = script.jobs[id];
      const state = queue.length > 1 ? queue.shift()! : queue[0];
      log.push(`poll ${id} ${state.status}`);
      return state;
    },
    sleep: async () => {},
  };
  return { deps, log };
}

const run = async (names: string[], script: Script) => {
  const { deps, log } = fake(script);
  let last: BatchRow[] = [];
  const batch = createBatch(items(...names), { seconds: 45 }, deps, (r) => (last = r));
  await batch.start();
  return { rows: last, log, batch };
};

test("the rows start as waiting, with the folder cut off the name", () => {
  const rows = makeRows(items("Members/Vidal/a.mov", "b.mp4"));
  assert.deepEqual(rows.map((r) => [r.name, r.path, r.status]), [["a.mov", "Members/Vidal/a.mov", "waiting"], ["b.mp4", "b.mp4", "waiting"]]);
});

test("videos go one after another: the next is sent only after the one before is finished", async () => {
  const { rows, log } = await run(["a.mp4", "b.mov"], {
    uploads: ["job-a", "job-b"],
    jobs: { "job-a": [{ status: "running", progress: 40 }, { status: "completed", progress: 100 }], "job-b": [{ status: "completed", progress: 100 }] },
  });
  assert.deepEqual(rows.map((r) => [r.status, r.jobId]), [["done", "job-a"], ["done", "job-b"]]);
  assert.ok(log.indexOf("poll job-a completed") < log.indexOf("upload b.mov (45s)"));
  assert.ok(log.includes("upload a.mp4 (45s)")); // the settings go with every video
});

test("one broken file does not stop the others", async () => {
  const { rows } = await run(["bad.mp4", "good.mp4"], { uploads: [new Error("This doesn't look like a MP4 video file."), "job-g"], jobs: { "job-g": [{ status: "completed", progress: 100 }] } });
  assert.deepEqual(rows.map((r) => r.status), ["failed", "done"]);
  assert.match(rows[0].message ?? "", /doesn't look like/);
});

test("a video whose edit fails is marked failed with the server's reason and the queue carries on", async () => {
  const { rows } = await run(["a.mp4", "b.mp4"], {
    uploads: ["job-a", "job-b"],
    jobs: { "job-a": [{ status: "failed", progress: 30, error: "No speech found in this video." }], "job-b": [{ status: "completed", progress: 100 }] },
  });
  assert.deepEqual(rows.map((r) => r.status), ["failed", "done"]);
  assert.equal(rows[0].message, "No speech found in this video.");
});

test("when today's videos are used up the rest are not sent", async () => {
  const limit = new Error("You've used your 3 videos for the last 24 hours. More free up in about 5 hours.");
  const { rows, log } = await run(["a.mp4", "b.mp4", "c.mp4"], { uploads: ["job-a", limit], jobs: { "job-a": [{ status: "completed", progress: 100 }] } });
  assert.deepEqual(rows.map((r) => r.status), ["done", "failed", "stopped"]);
  assert.match(rows[2].message ?? "", /Not sent/);
  assert.equal(log.filter((l) => l.startsWith("upload")).length, 2); // c.mp4 was never uploaded
  assert.ok(isLimitMessage(limit.message) && !isLimitMessage("Something else"));
});

test("an earlier video still being edited makes the upload wait and try again", async () => {
  const busy = new Error("You already have a video being processed. Wait for it to finish, then upload the next one.");
  const { rows, log } = await run(["a.mp4"], { uploads: [busy, busy, "job-a"], jobs: { "job-a": [{ status: "completed", progress: 100 }] } });
  assert.equal(rows[0].status, "done");
  assert.equal(log.filter((l) => l.startsWith("upload")).length, 3);
  assert.ok(isBusyMessage(busy.message));
});

test("cancelling stops the queue but leaves the video that is being edited running on the server", async () => {
  const { deps, log } = fake({ uploads: ["job-a", "job-b"], jobs: { "job-a": [{ status: "running", progress: 10 }], "job-b": [{ status: "completed", progress: 100 }] } });
  let last: BatchRow[] = [];
  const batch: Batch = createBatch(items("a.mp4", "b.mp4", "c.mp4"), { seconds: 45 }, { ...deps, sleep: async (): Promise<void> => batch.cancel() }, (r) => (last = r));
  await batch.start();
  assert.deepEqual(last.map((r) => r.status), ["processing", "stopped", "stopped"]);
  assert.equal(last[0].jobId, "job-a"); // can still be opened
  assert.equal(log.filter((l) => l.startsWith("upload")).length, 1);
});
