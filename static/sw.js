// static/sw.js
const CACHE_NAME = 'hide-and-seek-cache-v1';
const CORE_ASSETS = [
  '/', // Die index.html
  '/static/index.html', // Explizit, falls '/' nicht reicht oder anders geroutet wird
  '/static/offline.html', // Unsere Offline-Fallback-Seite
  // Wichtige CSS/JS-Dateien, die index.html benötigt (falls separat)
  // '/static/css/style.css',
  // '/static/js/main.js',
  // Wichtige Icons, die auch offline angezeigt werden sollen (z.B. im Manifest referenziert)
  '/static/icons/icon-192x192.png',
  '/static/icons/icon-512x512.png',
  '/static/manifest.json' // Das Manifest selbst cachen
];

self.addEventListener('install', (event) => {
  console.log('Service Worker: Installiere Version:', CACHE_NAME);
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Service Worker: Caching core assets...');
        return cache.addAll(CORE_ASSETS.map(url => new Request(url, { cache: 'reload' }))); // 'reload' um sicherzustellen, dass frische Versionen gecacht werden
      })
      .then(() => {
        console.log('Service Worker: Core assets erfolgreich gecacht.');
        return self.skipWaiting(); // Aktiviere den neuen SW sofort
      })
      .catch(error => {
        console.error('Service Worker: Fehler beim Caching der core assets:', error);
      })
  );
});

self.addEventListener('activate', (event) => {
  console.log('Service Worker: Aktiviere Version:', CACHE_NAME);
  // Alte Caches löschen
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cache => {
          if (cache !== CACHE_NAME) {
            console.log('Service Worker: Alter Cache wird gelöscht:', cache);
            return caches.delete(cache);
          }
        })
      );
    }).then(() => {
        console.log('Service Worker: Clients werden übernommen.');
        return self.clients.claim(); // Übernimmt Kontrolle über offene Clients sofort
    })
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // Nur GET-Requests behandeln
  if (request.method !== 'GET') {
    event.respondWith(fetch(request));
    return;
  }

  // Strategie: Netzwerk zuerst, dann Cache, dann Offline-Fallback für HTML
  event.respondWith(
    fetch(request)
      .then(networkResponse => {
        // Wenn vom Netzwerk erfolgreich, Antwort zurückgeben und ggf. in Cache legen
        // (optional, für dynamische Inhalte wie /status nicht unbedingt sinnvoll, aber für statische Assets schon)
        // if (request.url.includes('/static/') || request.url.endsWith('/')) { // Nur statische Dinge oder index
        //   const responseToCache = networkResponse.clone();
        //   caches.open(CACHE_NAME).then(cache => cache.put(request, responseToCache));
        // }
        return networkResponse;
      })
      .catch(error => {
        // Netzwerkfehler -> Versuche aus dem Cache
        console.warn('Service Worker: Netzwerkfehler für', request.url, error.message, '- Versuche Cache...');
        return caches.match(request)
          .then(cachedResponse => {
            if (cachedResponse) {
              console.log('Service Worker: Antwort aus Cache für', request.url);
              return cachedResponse;
            }

            // Wenn nicht im Cache UND es eine Navigationsanfrage ist (HTML-Seite) -> Fallback
            if (request.mode === 'navigate' || (request.method === 'GET' && request.headers.get('accept').includes('text/html'))) {
              console.log('Service Worker: Navigationsanfrage fehlgeschlagen und nicht im Cache. Zeige Offline-Seite für', request.url);
              return caches.match('/static/offline.html');
            }

            // Für andere Ressourcen (Bilder, etc.), die nicht im Cache sind, einfach fehlschlagen lassen
            console.warn('Service Worker: Ressource nicht im Cache und kein HTML-Fallback:', request.url);
            return new Response("Ressource nicht verfügbar und nicht im Cache.", { status: 404, statusText: "Not Found" });
          });
      })
  );
});