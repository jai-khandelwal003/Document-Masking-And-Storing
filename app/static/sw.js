// Service worker: caches only public static shell assets.
// It must never cache pages or API responses (masked images, identity documents, dashboard, login),
// because cached copies would outlive the login session and bypass the server's access checks.
const CACHE_NAME = "sdm-shell-v2";
const SHELL_ASSETS = [
  "/static/manifest.json",
  "/static/apple-touch-icon.svg",
  "/static/icon-192.svg",
  "/static/icon-512.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  // Deleting every older cache also purges anything an earlier version stored (pages, documents).
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isShellAsset = event.request.method === "GET"
    && url.origin === self.location.origin
    && SHELL_ASSETS.includes(url.pathname);

  // Everything else goes straight to the network and the browser's normal handling.
  if (!isShellAsset) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
