const CACHE_NAME = "trade-radar-v1";
const ASSETS = [
  "/",
  "/static/styles.css?v=9",
  "/static/app.js?v=9",
  "/static/manifest.webmanifest?v=1",
  "/static/icon.svg?v=1"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request).then((cached) => cached || caches.match("/")))
  );
});
