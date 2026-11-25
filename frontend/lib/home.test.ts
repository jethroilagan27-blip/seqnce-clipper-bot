import assert from "node:assert/strict";
import { test } from "node:test";
import { onHomeRequest, requestHome, takeHomeRequest } from "./home.ts";

test("a request is waiting until somebody takes it, once", () => {
  assert.equal(takeHomeRequest(), false);
  requestHome();
  assert.equal(takeHomeRequest(), true);
  assert.equal(takeHomeRequest(), false);
});

test("a page that is already showing hears it, and stops hearing after it leaves", () => {
  let heard = 0;
  const stop = onHomeRequest(() => {
    if (takeHomeRequest()) heard += 1;
  });
  requestHome();
  assert.equal(heard, 1);
  assert.equal(takeHomeRequest(), false);
  stop();
  requestHome();
  assert.equal(heard, 1);
  assert.equal(takeHomeRequest(), true); // still waiting for the next page that looks
});
