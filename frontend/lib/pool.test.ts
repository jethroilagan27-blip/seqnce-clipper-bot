import assert from "node:assert/strict";
import { test } from "node:test";
import { runPool } from "./pool.ts";

const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 5));

test("every item is done, and never more than the limit at once", async () => {
  let running = 0;
  let peak = 0;
  const done: number[] = [];
  await runPool([1, 2, 3, 4, 5, 6, 7], 3, async (n) => {
    running++;
    peak = Math.max(peak, running);
    await tick();
    done.push(n);
    running--;
  });
  assert.deepEqual(done.slice().sort(), [1, 2, 3, 4, 5, 6, 7]);
  assert.equal(peak, 3);
});

test("items start in list order", async () => {
  const started: number[] = [];
  await runPool(["a", "b", "c", "d"], 2, async (_item, i) => {
    started.push(i);
    await tick();
  });
  assert.deepEqual(started, [0, 1, 2, 3]);
});

test("a short list, an empty list and a silly limit all work", async () => {
  let count = 0;
  await runPool([1, 2], 10, async () => void count++);
  assert.equal(count, 2);
  await runPool([], 3, async () => void count++);
  assert.equal(count, 2);
  await runPool([1, 2, 3], 0, async () => void count++); // a limit of 0 still gets the work done, one at a time
  assert.equal(count, 5);
});

test("a slow item does not hold up the others", async () => {
  const order: string[] = [];
  await runPool(["slow", "fast1", "fast2"], 2, async (name) => {
    await new Promise<void>((resolve) => setTimeout(resolve, name === "slow" ? 40 : 5));
    order.push(name);
  });
  assert.deepEqual(order, ["fast1", "fast2", "slow"]);
});
