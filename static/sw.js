// TRACE Service Worker - Required for Installation & Share Target
self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim());
});

// This "fetch" handler is the secret key to the "Install" button
self.addEventListener('fetch', (event) => {
  // We don't need to cache anything yet, just acknowledging the request
  event.respondWith(fetch(event.request));
});
