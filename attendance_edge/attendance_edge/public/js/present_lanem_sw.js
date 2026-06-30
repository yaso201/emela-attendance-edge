const CACHE_NAME = "present-lanem-v1";
const CORE_ASSETS = [
    "/present-lanem",
    "/assets/attendance_edge/css/attendance_ui.css",
    "/assets/attendance_edge/js/present_lanem.js",
    "/assets/attendance_edge/img/present-lanem.svg",
];

self.addEventListener("install", (event) => {
    event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).catch(() => null));
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
    );
    self.clients.claim();
});

self.addEventListener("fetch", (event) => {
    if (event.request.method !== "GET") {
        return;
    }
    event.respondWith(
        fetch(event.request)
            .then((response) => {
                const clone = response.clone();
                caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone)).catch(() => null);
                return response;
            })
            .catch(() => caches.match(event.request))
    );
});
