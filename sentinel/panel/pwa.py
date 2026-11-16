"""Static PWA metadata and the deliberately non-caching service worker."""
from __future__ import annotations

import json


MAX_DOCUMENT_AGE_SECONDS = 45

CURRENT_DOCUMENT_SCRIPT = r"""
function currentDocument(html, status) {
  if (typeof html !== "string" || html.length > 2097152) {
    throw new Error("Dashboard response exceeds its document bound");
  }
  var next = new DOMParser().parseFromString(html, "text/html");
  var nextAge = Date.now() - Date.parse(next.body.dataset.generatedAt);
  var nextBudget = Number(next.body.dataset.maxAgeSeconds) * 1000;
  if (!next.getElementById("operational-state") ||
      !["CURRENT", "PARTIAL"].includes(status) ||
      next.body.dataset.observationCurrent !== (status === "CURRENT" ? "true" : "false") ||
      next.body.dataset.refreshPending !== "false" ||
      !Number.isFinite(nextAge) || !Number.isFinite(nextBudget) ||
      nextBudget <= 0 || nextBudget > __MAX_AGE_MS__ ||
      nextAge < -5000 || nextAge > nextBudget) {
    throw new Error("Dashboard response is incomplete or expired");
  }
  return next;
}
""".replace('__MAX_AGE_MS__', str(MAX_DOCUMENT_AGE_SECONDS * 1000)).strip()


LAUNCH_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark"><meta name="theme-color" content="#16111f">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.webmanifest"><title>Caesar's Palace</title>
<style>
html,body{margin:0;min-height:100%;background:#16111f;color:#e5dfeb;font:18px/1.5 system-ui}
body{padding:max(28px,env(safe-area-inset-top)) max(20px,env(safe-area-inset-right)) max(28px,env(safe-area-inset-bottom)) max(20px,env(safe-area-inset-left));box-sizing:border-box}
main{max-width:38rem;margin:8vh auto}h1{color:#f7d78c;font-size:1.65rem}
section{border:2px solid #756b7b;border-radius:16px;padding:22px}p{color:#c2b7c8}
button,a{color:#f7d78c}button{font:inherit;padding:10px 20px;border:1px solid #756b7b;border-radius:10px;background:transparent}
button:disabled{opacity:.6}
</style></head><body data-panel-launch="true"><main>
<h1>Caesar's Palace</h1><section aria-live="polite">
<strong id="launch-status">Connecting to current status…</strong>
<p id="launch-detail">Current system health has not been checked yet.</p>
<button id="launch-retry" type="button">Retry</button>
<noscript><p>JavaScript is disabled. <a href="/?document=1">Open the read-only status page</a>.</p></noscript>
</section></main><script>
(function(){
  "use strict";
  __CURRENT_DOCUMENT_SCRIPT__
  var busy = false, controller = null, again = false, away = false;
  var status = document.getElementById("launch-status");
  var detail = document.getElementById("launch-detail");
  var retry = document.getElementById("launch-retry");
  function visible() { return !away && document.visibilityState === "visible"; }
  function offline() {
    status.textContent = "STATUS NOT CURRENT — OFFLINE";
    detail.textContent = "This device cannot check system health while offline. Reconnect and retry.";
  }
  async function load() {
    if (document.body.dataset.panelLaunch !== "true" || !visible()) { return; }
    if (busy) { again = true; return; }
    if (!navigator.onLine) { offline(); return; }
    busy = true; retry.disabled = true;
    status.textContent = "Connecting to current status…";
    detail.textContent = "Current system health has not been checked yet.";
    controller = new AbortController();
    var active = controller;
    var deadline = setTimeout(function(){ active.abort(); }, 15000);
    try {
      var response = await fetch(location.href, {cache:"no-store", credentials:"same-origin", signal:active.signal});
      var documentStatus = response.headers.get("X-Sentinel-Panel-Status");
      if (!response.ok || !["CURRENT", "PARTIAL"].includes(documentStatus) ||
          new URL(response.url || location.href, location.href).origin !== location.origin) {
        throw new Error("Current status is not available");
      }
      var html = await response.text();
      currentDocument(html, documentStatus);
      if (active.signal.aborted || !visible()) { return; }
      document.open(); document.write(html); document.close();
    } catch (_error) {
      if (visible()) {
        if (!navigator.onLine) { offline(); }
        else {
          status.textContent = "STATUS NOT CURRENT — CONNECTION DELAYED";
          detail.textContent = "Current status could not be loaded. Retry when the connection is ready.";
        }
      }
    } finally {
      clearTimeout(deadline); busy = false; controller = null; retry.disabled = false;
      if (again && visible()) { again = false; load(); }
    }
  }
  retry.addEventListener("click", load);
  document.addEventListener("visibilitychange", function(){
    away = document.visibilityState !== "visible";
    if (away && controller) { controller.abort(); }
    if (!away) { load(); }
  });
  window.addEventListener("pagehide", function(){ away = true; if (controller) { controller.abort(); } });
  window.addEventListener("pageshow", function(event){ if (event.persisted) { away = false; load(); } });
  window.addEventListener("online", load);
  window.addEventListener("offline", function(){ if (controller) { controller.abort(); } offline(); });
  // Commit a painted neutral document before beginning the status round trip.
  requestAnimationFrame(function(){ requestAnimationFrame(load); });
})();
</script></body></html>""".replace('__CURRENT_DOCUMENT_SCRIPT__', CURRENT_DOCUMENT_SCRIPT)


MANIFEST = {
    "id": "/",
    "name": "Caesar's Palace",
    "short_name": "Caesar's",
    "description": "Private Sentinel operational monitoring",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#0e1116",
    "theme_color": "#b3261e",
    "icons": [
        {"src": "/static/caesars-palace-192.png", "sizes": "192x192",
         "type": "image/png", "purpose": "any"},
        {"src": "/static/caesars-palace-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "any maskable"},
    ],
}


SERVICE_WORKER = r"""
"use strict";
const LAUNCH_DOCUMENT = __LAUNCH_DOCUMENT__;
self.addEventListener("install", function(event) {
  event.waitUntil(self.skipWaiting());
});
self.addEventListener("activate", function(event) {
  event.waitUntil((async function() {
    var names = await caches.keys();
    await Promise.all(names.map(function(name) { return caches.delete(name); }));
    await self.clients.claim();
  })());
});
self.addEventListener("fetch", function(event) {
  if (event.request.mode !== "navigate") { return; }
  var url = new URL(event.request.url);
  if (event.request.method === "GET" && url.origin === self.location.origin &&
      url.pathname === "/" && url.searchParams.get("document") !== "1") {
    event.respondWith(Promise.resolve(new Response(LAUNCH_DOCUMENT, {
      status: 200, headers: {"Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store", "X-Sentinel-Panel-Status": "CONNECTING",
        "X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'"}
    })));
    return;
  }
  event.respondWith(fetch(event.request, {cache: "no-store"}).catch(function() {
    return new Response(
      "<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name=color-scheme content='light dark'><title>Caesar's Palace — offline</title><style>body{margin:0;padding:max(24px,env(safe-area-inset-top)) max(18px,env(safe-area-inset-right)) max(24px,env(safe-area-inset-bottom)) max(18px,env(safe-area-inset-left));background:#16111f;color:#c2b7c8;font:600 18px/1.5 system-ui}main{max-width:38rem;margin:auto;border:2px solid #756b7b;border-radius:16px;padding:20px}small{display:block;margin-top:12px;font-weight:400}</style></head><body><main>STATUS NOT CURRENT — OFFLINE<small>This browser is offline. System health cannot be checked from this device; this notice does not record a system incident. Reconnect to the private Tailscale HTTPS origin.</small></main></body></html>",
      {status: 503, headers: {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}}
    );
  }));
});
self.addEventListener("push", function(event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (_) {}
  var title = data.title || "Caesar's Palace — action required";
  var options = {
    body: data.body || "Open the operator panel for current evidence.",
    tag: data.tag || data.alert_id || "caesars-palace-unknown-alert",
    icon: data.icon || "/static/caesars-palace-192.png",
    badge: data.badge || "/static/caesars-palace-192.png",
    data: {url: data.url || "/", alert_id: data.alert_id || null}
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener("pushsubscriptionchange", function(event) {
  event.waitUntil((async function() {
    var subscription = event.newSubscription || null;
    if (!subscription) {
      var response = await fetch("/push/config", {
        credentials: "same-origin", cache: "no-store"
      });
      if (!response.ok) { throw new Error("Push configuration is unavailable."); }
      var config = await response.json();
      var value = config.applicationServerKey;
      var padding = "=".repeat((4 - value.length % 4) % 4);
      var binary = atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
      var key = Uint8Array.from(binary, function(ch) { return ch.charCodeAt(0); });
      subscription = await self.registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: key
      });
    }
    var replaced = await fetch("/push/subscriptions/refresh", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        subscription: subscription.toJSON(),
        previous_endpoint: event.oldSubscription
          ? event.oldSubscription.endpoint : null
      })
    });
    if (!replaced.ok) { throw new Error("Push subscription refresh failed."); }
  })());
});
self.addEventListener("notificationclick", function(event) {
  event.notification.close();
  var requested = (event.notification.data && event.notification.data.url) || "/";
  var target = new URL(requested, self.location.origin).href;
  if (new URL(target).origin !== self.location.origin) {
    target = new URL("/", self.location.origin).href;
  }
  event.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true})
    .then(function(windows) {
      for (var i = 0; i < windows.length; i += 1) {
        if (new URL(windows[i].url).origin === self.location.origin) {
          return windows[i].navigate(target).then(function(client) { return client.focus(); });
        }
      }
      return self.clients.openWindow(target);
    }));
});
""".replace('__LAUNCH_DOCUMENT__', json.dumps(LAUNCH_HTML)).strip()


__all__ = ["MANIFEST", "SERVICE_WORKER", "LAUNCH_HTML", "CURRENT_DOCUMENT_SCRIPT",
           "MAX_DOCUMENT_AGE_SECONDS"]
