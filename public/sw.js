// FILE: public/sw.js
// MODULE: Service Worker für PWA Offline-Funktionalität und Caching

const CACHE_NAME = 'trueangels-v1';
const OFFLINE_URL = '/offline.html';

// Assets zum Cachen
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/offline.html',
  '/static/css/main.css',
  '/static/js/main.js',
  '/icon-192.png',
  '/icon-512.png'
];

// Install Event - Precaching
self.addEventListener('install', event => {
  console.log('[ServiceWorker] Install');
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('[ServiceWorker] Precaching assets');
        return cache.addAll(PRECACHE_URLS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate Event - Clean old caches
self.addEventListener('activate', event => {
  console.log('[ServiceWorker] Activate');
  
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            console.log('[ServiceWorker] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch Event - Network first with offline fallback
self.addEventListener('fetch', event => {
  console.log('[ServiceWorker] Fetch', event.request.url);
  
  // API Requests - Network only (no cache for data)
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request).catch(error => {
        console.log('[ServiceWorker] API fetch failed:', error);
        return new Response(
          JSON.stringify({ error: 'Offline - Please check your connection' }),
          { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
      })
    );
    return;
  }
  
  // Static Assets - Cache first with network fallback
  event.respondWith(
    caches.match(event.request)
      .then(cachedResponse => {
        if (cachedResponse) {
          return cachedResponse;
        }
        
        return fetch(event.request)
          .then(response => {
            // Cache new assets
            if (response.status === 200) {
              const responseToCache = response.clone();
              caches.open(CACHE_NAME)
                .then(cache => {
                  cache.put(event.request, responseToCache);
                });
            }
            return response;
          })
          .catch(error => {
            console.log('[ServiceWorker] Fetch failed:', error);
            // Return offline page for navigation requests
            if (event.request.mode === 'navigate') {
              return caches.match(OFFLINE_URL);
            }
            return new Response('Offline content not available', {
              status: 503,
              statusText: 'Service Unavailable'
            });
          });
      })
  );
});

// Background Sync für Offline Posts
self.addEventListener('sync', event => {
  console.log('[ServiceWorker] Background sync', event.tag);
  
  if (event.tag === 'sync-donations') {
    event.waitUntil(syncDonations());
  }
});

async function syncDonations() {
  // Sync pending donations from IndexedDB
  console.log('[ServiceWorker] Syncing donations...');
  
  // In Production: Implement IndexedDB sync logic
  const pendingDonations = await getPendingDonations();
  
  for (const donation of pendingDonations) {
    try {
      const response = await fetch('/api/v1/payments/create-donation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(donation)
      });
      
      if (response.ok) {
        await removePendingDonation(donation.id);
        console.log('[ServiceWorker] Donation synced:', donation.id);
      }
    } catch (error) {
      console.error('[ServiceWorker] Sync failed:', error);
    }
  }
}

// Push Notifications
self.addEventListener('push', event => {
  console.log('[ServiceWorker] Push received');
  
  let data = { title: 'TrueAngels', body: 'Neue Benachrichtigung' };
  
  if (event.data) {
    data = event.data.json();
  }
  
  const options = {
    body: data.body,
    icon: '/icon-192.png',
    badge: '/icon-72.png',
    vibrate: [200, 100, 200],
    data: {
      url: data.url || '/'
    },
    actions: [
      { action: 'open', title: 'Öffnen' },
      { action: 'close', title: 'Schließen' }
    ]
  };
  
  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

// Notification Click Handler
self.addEventListener('notificationclick', event => {
  console.log('[ServiceWorker] Notification click');
  
  event.notification.close();
  
  if (event.action === 'open') {
    event.waitUntil(
      clients.openWindow(event.notification.data.url)
    );
  }
});