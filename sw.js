/* AirNavFLOW service worker
   - App shell: cache-first (works offline after first visit)
   - Pages: network-first, falls back to cached shell when offline
   - Province borders / fonts: stale-while-revalidate
   - map/*.pmtiles is NOT handled here: the app stores it in its own cache ('fp-offline-map-v1') */
var APP_CACHE='fp-app-v5';
var RUNTIME_CACHE='fp-runtime-v1';
var SHELL=['airnavflow.html'];
var OPTIONAL=['./','manifest.webmanifest','icons/icon-192.png','icons/icon-512.png'];
var RUNTIME_HOSTS=['cdn.jsdelivr.net','raw.githubusercontent.com','fonts.googleapis.com','fonts.gstatic.com'];

self.addEventListener('install',function(e){
  e.waitUntil(caches.open(APP_CACHE).then(function(c){
    return c.addAll(SHELL).then(function(){
      return Promise.all(OPTIONAL.map(function(u){return c.add(u).catch(function(){});}));
    });
  }).then(function(){return self.skipWaiting();}));
});

self.addEventListener('activate',function(e){
  e.waitUntil(caches.keys().then(function(keys){
    return Promise.all(keys.filter(function(k){
      return (k.indexOf('fp-app-')===0&&k!==APP_CACHE)||(k.indexOf('fp-runtime-')===0&&k!==RUNTIME_CACHE);
    }).map(function(k){return caches.delete(k);}));
  }).then(function(){return self.clients.claim();}));
});

self.addEventListener('fetch',function(e){
  var req=e.request;
  if(req.method!=='GET')return;
  var url=new URL(req.url);

  if(url.origin===self.location.origin){
    if(/\.pmtiles$/i.test(url.pathname))return;
    if(/\/notam\//.test(url.pathname))return;   // daily NOTAM file: always from network (app keeps its own offline copy)
    if(req.mode==='navigate'){
      e.respondWith(fetch(req).then(function(res){
        var copy=res.clone();
        caches.open(APP_CACHE).then(function(c){if(/airnavflow\.html$/.test(url.pathname))c.put('airnavflow.html',copy);});
        return res;
      }).catch(function(){return caches.match(req,{ignoreSearch:true}).then(function(hit){return hit||caches.match('airnavflow.html');});}));
      return;
    }
    e.respondWith(caches.match(req,{ignoreSearch:true}).then(function(hit){return hit||fetch(req);}));
    return;
  }

  if(RUNTIME_HOSTS.indexOf(url.hostname)!==-1){
    e.respondWith(caches.open(RUNTIME_CACHE).then(function(c){
      return c.match(req).then(function(hit){
        var net=fetch(req).then(function(res){if(res&&(res.ok||res.type==='opaque'))c.put(req,res.clone());return res;});
        return hit||net;
      });
    }));
  }
});
