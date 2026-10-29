/* Service worker Santimanos. Версія: {{ version }} */
var CACHE = 'santimanos-{{ version }}';
var OFFLINE = '{{ precache[0] }}';
var PRECACHE = {{ precache|tojson }};

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(PRECACHE); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k.indexOf('santimanos-') === 0 && k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;

  // Сторінки — завжди з мережі (там особисті дані); без мережі — сторінка «Немає з'єднання».
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(function () { return caches.match(OFFLINE); }));
    return;
  }

  // Статика (крім фото користувачів) — з кешу, з оновленням у фоні.
  if (url.pathname.indexOf('/static/') === 0 && url.pathname.indexOf('/static/uploads/') !== 0) {
    e.respondWith(caches.open(CACHE).then(function (cache) {
      return cache.match(req).then(function (hit) {
        var net = fetch(req).then(function (resp) {
          if (resp.ok) cache.put(req, resp.clone());
          return resp;
        }).catch(function () { return hit; });
        return hit || net;
      });
    }));
  }
});
