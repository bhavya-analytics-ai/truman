// sw.js — Truman service worker (Phase 14.2)
// Handles: offline shell cache, push notifications, notification clicks
// v2: bumped cache name so old stale cache is deleted on update

const CACHE_NAME = 'truman-shell-v2';
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

// ── Activate: delete old caches, claim all clients ────────────────────────────
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => clients.claim())
  );
});

// ── Fetch: always network-first for HTML, cache fallback only if offline ──────
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = e.request.url;

  // API + SSE + audio: always bypass SW entirely
  if (url.includes('/api/') || url.includes('/stream') || url.includes('/audio')) return;

  // Dashboard HTML: force network, bypass HTTP cache — only fall back if offline
  if (url.includes('/dashboard') || url.endsWith('/')) {
    e.respondWith(
      fetch(e.request, {cache: 'no-store'})
        .catch(() => caches.match(e.request))
    );
    return;
  }

  // All other assets (icons, manifest, js): network with cache fallback
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
      tag:     'truman-push',
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
