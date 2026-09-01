/* Service worker: установка как приложение + офлайн-резерв.
   ВАЖНО: network-first — всегда отдаём свежую версию (иначе обновления кода/данных
   застревали бы в кэше). Кэш используется только как запасной вариант офлайн. */
const CACHE = "yulechka-v3";
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

/* Пуш-уведомление об открытке дня (шлёт notify.py из GitHub Actions в 12:00 МСК) */
self.addEventListener("push", (e) => {
    let d = {};
    try { d = e.data ? e.data.json() : {}; } catch (err) {}
    e.waitUntil(self.registration.showNotification(d.title || "Для Юлечки 💌", {
        body: d.body || "Новая открытка дня ждёт тебя",
        icon: "./icon-192.png",
        badge: "./icon-192.png",
        data: { url: d.url || "./" },
    }));
});

self.addEventListener("notificationclick", (e) => {
    e.notification.close();
    const url = (e.notification.data && e.notification.data.url) || "./";
    e.waitUntil(
        clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
            for (const c of list) { if ("focus" in c) return c.focus(); }
            return clients.openWindow(url);
        })
    );
});
