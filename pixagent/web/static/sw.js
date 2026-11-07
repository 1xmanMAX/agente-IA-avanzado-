/* Service worker de PixAgent: guarda la interfaz en caché para que abra al instante (y sin red
   muestre al menos la app). Nunca guarda en caché la API, los archivos ni el WebSocket. */
const CACHE = "pixagent-{{V}}";
const SHELL = ["/", "/static/style.css?v={{V}}", "/static/app.js?v={{V}}", "/static/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname === "/") { // red primero (versiones nuevas), caché si no hay conexión
    e.respondWith(fetch(e.request).then((r) => { const cp = r.clone(); caches.open(CACHE).then((c) => c.put("/", cp)); return r; })
      .catch(() => caches.match("/")));
    return;
  }
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
});
