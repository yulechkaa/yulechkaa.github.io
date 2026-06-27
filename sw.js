/* Service worker: установка как приложение + офлайн-резерв.
   ВАЖНО: network-first — всегда отдаём свежую версию (иначе обновления кода/данных
   застревали бы в кэше). Кэш используется только как запасной вариант офлайн. */
const CACHE = "yulechka-v2";
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
    if (req.method !== "GET") return;        // HEAD/POST — мимо SW (важно для проверки аудио)
    e.respondWith(
        fetch(req)
            .then((r) => {
                const cp = r.clone();
                caches.open(CACHE).then((c) => c.put(req, cp)).catch(() => {});
                return r;
            })
            .catch(() => caches.match(req))    // нет сети — отдаём из кэша
    );
});
