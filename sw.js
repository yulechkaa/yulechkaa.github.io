/* Service worker: нужен для установки как приложения + офлайн-доступ.
   data.json и audio.mp3 берём из сети (всегда свежие), остальное — из кэша. */
const CACHE = "yulechka-v1";
const CORE = ["./", "./index.html", "./manifest.webmanifest",
              "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
    e.waitUntil(
        caches.open(CACHE)
            .then((c) => Promise.allSettled(CORE.map((u) => c.add(u))))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (e) => {
    e.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (e) => {
    const req = e.request;
    if (req.method !== "GET") return;
    const url = new URL(req.url);

    // Свежие данные дня и аудио — сеть, с откатом на кэш
    if (url.pathname.endsWith("data.json") || url.pathname.endsWith("audio.mp3")) {
        e.respondWith(
            fetch(req).then((r) => {
                const cp = r.clone();
                caches.open(CACHE).then((c) => c.put(req, cp));
                return r;
            }).catch(() => caches.match(req))
        );
        return;
    }

    // Остальное — из кэша, иначе сеть (и докэшируем)
    e.respondWith(
        caches.match(req).then((c) => c || fetch(req).then((r) => {
            const cp = r.clone();
            caches.open(CACHE).then((ch) => ch.put(req, cp));
            return r;
        }).catch(() => c))
    );
});
