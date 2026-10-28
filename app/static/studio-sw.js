'use strict';
const CACHE = 'freo-studio-shell-v1';
const SHELL = ['/admin/offline', '/static/studio-192.png', '/static/studio-512.png'];
self.addEventListener('install', event => event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL))));
self.addEventListener('activate', event => event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('freo-studio-shell-') && key !== CACHE).map(key => caches.delete(key))))));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (event.request.mode === 'navigate' && url.pathname.startsWith('/admin/')) {
    event.respondWith(fetch(event.request, {cache: 'no-store'}).then(response => response.status >= 500 ? caches.match('/admin/offline') : response).catch(() => caches.match('/admin/offline')));
  } else if (SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(url.pathname).then(cached => cached || fetch(event.request)));
  }
});
