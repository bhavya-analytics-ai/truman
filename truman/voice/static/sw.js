// sw.js — Truman service worker (Phase 14)
// Handles: offline shell cache, push notifications, notification clicks

const CACHE_NAME = 'truman-shell-v1';
const SHELL_URLS = ['/dashboard'];

// ── Install: cache dashboard shell ────────────────────────────────────────────
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(c => c.addAll(SHELL_URLS))
      .catch(() => {})   // fail silently if offline at install time
  );
  self.skipWaiting();
});

// ── Activate: claim all clients ───────────────────────────────────────────────
self.addEventListener('activate', e => {
  // clean up old caches
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

// ── Fetch: network-first, fallback to cache for shell only ────────────────────
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  // API + SSE calls: always go to network — never cache
  const url = e.request.url;
  if (url.includes('/api/') || url.includes('/stream') || url.includes('/audio')) return;

  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});

// ── Push: show iOS/Android notification ───────────────────────────────────────
self.addEventListener('push', e => {
  if (!e.data) return;
  let payload = { title: 'Truman', body: '', url: '/dashboard' };
  try { payload = { ...payload, ...e.data.json() }; } catch(_) {}

  e.waitUntil(
    self.registration.showNotification(payload.title, {
      body:    payload.body,
      icon:    '/static/icon-192.png',
      badge:   '/static/icon-192.png',
      data:    { url: payload.url },
      vibrate: [200, 100, 200],
      tag:     'truman-push',          // replaces previous notification of same tag
      renotify: true,
    })
  );
});

// ── Notification click: open / focus dashboard tab ────────────────────────────
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = e.notification.data?.url || '/dashboard';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cls => {
      for (const c of cls) {
        if (c.url.includes('/dashboard') && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});
