// Run: node --test cloudflare/seqnce-offline/worker.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.js";

const realFetch = globalThis.fetch;
const realNow = Date.now;
const at = (iso) => (Date.now = () => new Date(iso).getTime());
const stub = (fn) => (globalThis.fetch = fn);
test.afterEach(() => {
  globalThis.fetch = realFetch;
  Date.now = realNow;
});

const nav = (path = "/") => new Request("https://seqnce.orbitrixhq.com" + path, { headers: { accept: "text/html" } });

test("a healthy site passes through untouched", async () => {
  stub(async () => new Response("hello", { status: 200 }));
  const res = await worker.fetch(nav());
  assert.equal(res.status, 200);
  assert.equal(await res.text(), "hello");
});

test("the site's own 404 and 500 are not treated as down", async () => {
  for (const status of [301, 401, 404, 500]) {
    stub(async () => new Response("x", { status }));
    assert.equal((await worker.fetch(nav())).status, status);
  }
});

test("tunnel down (530) shows the offline page with the hours", async () => {
  at("2026-11-10T16:00:00Z"); // midnight in the Philippines
  stub(async () => new Response("error code: 1033", { status: 530 }));
  const res = await worker.fetch(nav());
  assert.equal(res.status, 503);
  assert.match(res.headers.get("content-type"), /text\/html/);
  const html = await res.text();
  assert.match(html, /Seqnce is resting/);
  assert.match(html, /9:00 AM to 9:00 PM/);
  // next opening = 9 AM Philippine time = 01:00 UTC on 2026-11-11
  assert.ok(html.includes(`var reopen = ${Date.parse("2026-11-11T01:00:00Z")};`));
});

test("a thrown fetch also shows the offline page", async () => {
  stub(async () => {
    throw new Error("network");
  });
  assert.equal((await worker.fetch(nav())).status, 503);
});

test("during opening hours the page asks visitors to notify Levin, with no countdown", async () => {
  at("2026-11-10T06:00:00Z"); // 2 PM in the Philippines
  stub(async () => new Response("", { status: 530 }));
  const html = await (await worker.fetch(nav())).text();
  assert.match(html, /Seqnce is switched off right now/);
  assert.match(html, /Please notify Levin to turn the server on so you can use it\./);
  assert.match(html, /opens Seqnce by itself/);
  assert.ok(!html.includes("Back in about"));
  assert.ok(!html.includes("any minute"));
  assert.ok(!html.includes("usually up every day"));
});

test("outside opening hours it still shows the resting page and does not ask anyone to turn it on", async () => {
  at("2026-11-10T16:00:00Z"); // midnight in the Philippines
  stub(async () => new Response("", { status: 530 }));
  const html = await (await worker.fetch(nav())).text();
  assert.match(html, /Seqnce is resting/);
  assert.ok(!html.includes("Please notify"));
});

test("the opening hour itself (9 AM) already counts as opening hours, 9 PM does not", async () => {
  stub(async () => new Response("", { status: 530 }));
  at("2026-11-11T01:00:00Z"); // 9:00 AM in the Philippines
  assert.match(await (await worker.fetch(nav())).text(), /Please notify Levin/);
  at("2026-11-10T12:59:00Z"); // 8:59 PM
  assert.match(await (await worker.fetch(nav())).text(), /Please notify Levin/);
  at("2026-11-10T13:00:00Z"); // 9:00 PM
  assert.match(await (await worker.fetch(nav())).text(), /Seqnce is resting/);
});

test("preview can force either version of the page", async () => {
  at("2026-11-10T16:00:00Z"); // night, so the default would be "resting"
  const open = await (await worker.fetch(nav("/__offline-preview?state=open"))).text();
  assert.match(open, /Please notify Levin/);
  const closed = await (await worker.fetch(nav("/__offline-preview?state=closed"))).text();
  assert.match(closed, /Seqnce is resting/);
});

test("after closing time the next opening is tomorrow morning", async () => {
  at("2026-11-10T14:30:00Z"); // 10:30 PM in the Philippines
  stub(async () => new Response("", { status: 530 }));
  const html = await (await worker.fetch(nav())).text();
  assert.ok(html.includes(`var reopen = ${Date.parse("2026-11-11T01:00:00Z")};`));
});

test("early morning opens the same day", async () => {
  at("2026-11-10T21:00:00Z"); // 5 AM on 11 Nov in the Philippines
  stub(async () => new Response("", { status: 530 }));
  const html = await (await worker.fetch(nav())).text();
  assert.ok(html.includes(`var reopen = ${Date.parse("2026-11-11T01:00:00Z")};`));
});

test("non-page requests get a plain 503, not HTML", async () => {
  stub(async () => new Response("", { status: 530 }));
  const res = await worker.fetch(new Request("https://seqnce.orbitrixhq.com/_next/static/x.js", { headers: { accept: "*/*" } }));
  assert.equal(res.status, 503);
  assert.ok(!(res.headers.get("content-type") || "").includes("html"));
});

test("/__offline-preview shows the page without calling the site", async () => {
  let called = false;
  stub(async () => {
    called = true;
    return new Response("", { status: 200 });
  });
  const res = await worker.fetch(nav("/__offline-preview"));
  assert.equal(res.status, 503);
  assert.equal(called, false);
});
