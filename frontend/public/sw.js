// Seqnce service worker. It exists so phones treat the site as an installable app, and to show a friendly page when
// there is no connection. It never stores anything about people or their videos: only the offline page itself.
// Everything else (pages, the API on another address, video files) always goes straight to the network.
const OFFLINE = "/offline.html";
const CACHE = "seqnce-shell-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.add(OFFLINE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.mode !== "navigate") return; // only page loads: the browser handles everything else as usual
  event.respondWith(fetch(request).catch(() => caches.match(OFFLINE)));
});
