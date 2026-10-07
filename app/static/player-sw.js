const CACHE='freo-player-shell-v1';
const SHELL=['/player/offline.html','/static/studio-192.png','/static/studio-512.png'];
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil(Promise.all([self.clients.claim(),caches.keys().then(keys=>Promise.all(keys.filter(key=>key.startsWith('freo-player-shell-')&&key!==CACHE).map(key=>caches.delete(key))))])));
self.addEventListener('fetch',event=>{
  const url=new URL(event.request.url);
  if(event.request.method!=='GET'||url.origin!==location.origin)return;
  if(event.request.mode==='navigate' && url.pathname.startsWith('/player/'))event.respondWith(fetch(event.request,{cache:'no-store'}).catch(()=>caches.match('/player/offline.html')));
});
