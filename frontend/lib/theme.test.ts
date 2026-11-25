import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";
import { BAR_COLOR, DEFAULT_THEME, THEME_SCRIPT, parseTheme } from "./theme.ts";

function run(stored: string | null | Error) {
  const attrs: Record<string, string> = {};
  const meta: Record<string, string> = { content: BAR_COLOR.dark };
  vm.runInNewContext(THEME_SCRIPT, {
    localStorage: {
      getItem: () => {
        if (stored instanceof Error) throw stored;
        return stored;
      },
    },
    document: {
      documentElement: { setAttribute: (k: string, v: string) => (attrs[k] = v) },
      querySelector: () => ({ setAttribute: (k: string, v: string) => (meta[k] = v) }),
    },
  });
  return { theme: attrs["data-theme"], bar: meta.content };
}

test("only light and dark are themes; anything else is the default", () => {
  assert.equal(parseTheme("light"), "light");
  assert.equal(parseTheme("dark"), "dark");
  assert.equal(parseTheme("purple"), DEFAULT_THEME);
  assert.equal(parseTheme(null), DEFAULT_THEME);
});

test("the head script applies the saved choice before the page draws", () => {
  assert.deepEqual(run("light"), { theme: "light", bar: BAR_COLOR.light });
  assert.deepEqual(run("dark"), { theme: "dark", bar: BAR_COLOR.dark });
  assert.deepEqual(run(null), { theme: DEFAULT_THEME, bar: BAR_COLOR.dark });
  assert.deepEqual(run("<script>"), { theme: DEFAULT_THEME, bar: BAR_COLOR.dark });
});

test("blocked storage falls back to the default instead of breaking the page", () => {
  assert.equal(run(new Error("blocked")).theme, DEFAULT_THEME);
});
