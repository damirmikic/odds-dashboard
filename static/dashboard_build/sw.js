/* Pinnacle Board service worker.
 *
 * - App shell (index.html, manifest, icons) is precached; hashed /assets/* are cached on first use.
 * - Navigations: network first, cached shell when offline.
 * - GET /api/*: network first; the last good response is kept and served offline with
 *   an "X-PB-Cache: <time saved>" header so the page can say the odds are not live.
 * - Everything else (POST /api/config, other origins) passes through untouched.
 */
const VERSION = "pb-v1";
const SHELL_CACHE = `${VERSION}-shell`;
const ASSET_CACHE = `${VERSION}-assets`;
const API_CACHE = `${VERSION}-api`;
const SHELL = [
  "/",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
  "/icons/favicon-32.png",
];

// The bundle file names are hashed, so read them from the current index.html.
async function precacheBuild() {
  const shell = await caches.open(SHELL_CACHE);
  await shell.addAll(SHELL);
  const html = await (await shell.match("/")).text();
  const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
  if (assets.length) await (await caches.open(ASSET_CACHE)).addAll(assets);
}

// The first visit loads its data before this worker controls the page; keep a copy now so the
// board can open offline right away. Plain /api/board serves the server's snapshot and costs
// no PinnWire request.
async function warmApi() {
  await Promise.all(["/api/status", "/api/board"].map((path) =>
    networkFirstApi(new Request(path)).catch(() => null)));
}

self.addEventListener("install", (event) => {
  event.waitUntil(precacheBuild());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
      .then(warmApi),
  );
});

async function networkFirstApi(request) {
  const cache = await caches.open(API_CACHE);
  // keyed by path only: a ?refresh=1 / ?full=1 response is also the offline copy of the plain URL
  const key = new URL(request.url).pathname;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const headers = new Headers(response.headers);
      headers.set("X-PB-Saved", new Date().toISOString());
      const body = await response.clone().arrayBuffer();
      await cache.put(key, new Response(body, { status: response.status, headers }));
    }
    return response;
  } catch (error) {
    const fallback = await cache.match(key);
    if (!fallback) throw error;
    const headers = new Headers(fallback.headers);
    headers.set("X-PB-Cache", fallback.headers.get("X-PB-Saved") || "1");
    return new Response(await fallback.arrayBuffer(), { status: 200, headers });
  }
}

async function networkFirstPage(request) {
  try {
    const response = await fetch(request);
    if (response.ok) (await caches.open(SHELL_CACHE)).put("/", response.clone());
    return response;
  } catch (error) {
    const cached = await caches.match("/");
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) (await caches.open(ASSET_CACHE)).put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirstApi(request));
  } else if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request));
  } else if (url.pathname.startsWith("/assets/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(cacheFirst(request));
  }
});
