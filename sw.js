/* Service worker: установка как приложение + офлайн-резерв.
   ВАЖНО: network-first — всегда отдаём свежую версию (иначе обновления кода/данных
   застревали бы в кэше). Кэш используется только как запасной вариант офлайн. */
const CACHE = "yulechka-v4";
const CORE = ["./", "./index.html", "./styles.css", "./app.js", "./manifest.webmanifest",
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
    const url = new URL(req.url);
    if (url.origin !== self.location.origin || req.headers.has("range")) return;
    url.search = "";
    const key = url.href;
    e.respondWith(
        fetch(req)
            .then((r) => {
                const cp = r.clone();
                if (!r.ok) throw new Error("HTTP " + r.status);
                e.waitUntil(caches.open(CACHE).then(async (c) => {
                    await c.put(key, cp);
                    const keys = await c.keys();
                    const media = keys.filter(k => /\/(art|audio)\//.test(new URL(k.url).pathname));
                    await Promise.all(media.slice(0, Math.max(0, media.length - 24)).map(k => c.delete(k)));
                }).catch(() => {}));
                return r;
            })
            .catch(async () => (await caches.match(key)) || (req.mode === "navigate" && await caches.match(new URL("./index.html", self.location).href)) || Response.error())
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
