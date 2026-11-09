// Seqnce "offline page" Worker (runs on Cloudflare, so it still works when your laptop is off).
//
// It sits in front of https://seqnce.orbitrixhq.com/*. Every visit goes through to Seqnce as usual.
// If Seqnce does not answer (the tunnel is down), visitors get a friendly Seqnce page that says when
// it is usually online, instead of Cloudflare's "Error 1033".
//
// Edit the three settings below, then paste the whole file into the Worker's code editor and Deploy.
// See docs/DEPLOY.md ("Offline page").

const OPEN_HOUR = 9; // Seqnce is usually online from this hour...
const CLOSE_HOUR = 21; // ...until this hour (24-hour clock, Philippine time)
const TZ_OFFSET_HOURS = 8; // Philippines = UTC+8, no daylight saving

const HOUR_MS = 3600 * 1000;
const DAY_MS = 24 * HOUR_MS;
// 502/503/504 and Cloudflare's own 52x/530 codes (530 = "Error 1033, tunnel not running")
const DOWN_STATUSES = new Set([502, 503, 504, 520, 521, 522, 523, 524, 525, 526, 527, 530]);

/** Next time (ms since epoch) the opening hour starts, in Philippine time. */
function nextOpening(now) {
  const local = now + TZ_OFFSET_HOURS * HOUR_MS; // pretend UTC is Philippine time
  const startOfDay = Math.floor(local / DAY_MS) * DAY_MS;
  let open = startOfDay + OPEN_HOUR * HOUR_MS;
  if (open <= local) open += DAY_MS;
  return open - TZ_OFFSET_HOURS * HOUR_MS;
}

function insideOpenHours(now) {
  const hour = Math.floor(((now + TZ_OFFSET_HOURS * HOUR_MS) % DAY_MS) / HOUR_MS);
  return hour >= OPEN_HOUR && hour < CLOSE_HOUR;
}

const clock = (hour) => `${((hour + 11) % 12) + 1}:00 ${hour % 24 < 12 ? "AM" : "PM"}`;

function page(now) {
  const inHours = insideOpenHours(now);
  const reopen = nextOpening(now);
  const hours = `${clock(OPEN_HOUR)} to ${clock(CLOSE_HOUR)} (Philippine time)`;
  const headline = inHours ? "Seqnce is taking a short break" : "Seqnce is resting";
  const detail = inHours
    ? "It should be back any minute. This page checks again by itself."
    : "It isn't online around the clock yet. It's usually up every day from " + hours + ".";
  const countdown = inHours
    ? ""
    : `<p class="count">Back in about <b id="t">...</b></p>
       <p class="small">Usually around <span id="at"></span></p>`;
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Seqnce is resting</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 24px;
         background: #0f1017; color: #e8eaf2; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  .card { width: 100%; max-width: 520px; padding: 36px 32px; border-radius: 20px;
          background: linear-gradient(160deg, #1a1b2b, #14151f); border: 1px solid #2a2c40; }
  .logo { font-weight: 700; letter-spacing: .02em; color: #a99bff; margin-bottom: 18px; }
  h1 { margin: 0 0 10px; font-size: 28px; line-height: 1.2; }
  p { margin: 0 0 14px; line-height: 1.55; color: #b9bdd0; }
  .count { font-size: 20px; color: #e8eaf2; margin-top: 22px; }
  .count b { color: #a99bff; }
  .small { font-size: 14px; color: #8b8fa6; }
</style></head>
<body><main class="card">
  <div class="logo">Seqnce</div>
  <h1>${headline}</h1>
  <p>${detail}</p>
  ${countdown}
  <p class="small">Your videos and account are safe. Nothing is lost while it's offline.</p>
</main>
<script>
  var reopen = ${reopen};
  var t = document.getElementById("t"), at = document.getElementById("at");
  function tick() {
    var ms = reopen - Date.now();
    if (t) {
      if (ms <= 0) { location.reload(); return; }
      var m = Math.round(ms / 60000), h = Math.floor(m / 60);
      t.textContent = h > 0 ? h + " h " + (m % 60) + " min" : m + " min";
    }
    if (at) at.textContent = new Date(reopen).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) + " your time";
  }
  tick(); setInterval(tick, 30000);
  setTimeout(function () { location.reload(); }, 60000);
</script></body></html>`;
}

function offline(request, now) {
  const wantsHtml = (request.headers.get("accept") || "").includes("text/html");
  const headers = { "cache-control": "no-store", "retry-after": "300" };
  if (!wantsHtml) return new Response("Seqnce is offline right now.", { status: 503, headers });
  return new Response(page(now), { status: 503, headers: { ...headers, "content-type": "text/html; charset=utf-8" } });
}

export default {
  async fetch(request) {
    const now = Date.now();
    if (new URL(request.url).pathname === "/__offline-preview") return offline(new Request(request, { headers: { accept: "text/html" } }), now);
    let response;
    try {
      response = await fetch(request); // goes on to Seqnce (the tunnel)
    } catch {
      return offline(request, now);
    }
    return DOWN_STATUSES.has(response.status) ? offline(request, now) : response;
  },
};
