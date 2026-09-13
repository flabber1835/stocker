"""Static PWA metadata and the deliberately non-caching service worker."""
from __future__ import annotations


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
  event.respondWith(fetch(event.request, {cache: "no-store"}).catch(function() {
    return new Response(
      "<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'><meta name=color-scheme content='light dark'><title>Caesar's Palace — offline</title><style>body{margin:0;padding:max(24px,env(safe-area-inset-top)) max(18px,env(safe-area-inset-right)) max(24px,env(safe-area-inset-bottom)) max(18px,env(safe-area-inset-left));background:#170b0b;color:#ffb4ab;font:600 18px/1.5 system-ui}main{max-width:38rem;margin:auto;border:2px solid #ff7b72;border-radius:16px;padding:20px}small{display:block;margin-top:12px;font-weight:400}</style></head><body><main>OPERATIONAL RED — OFFLINE<small>Current Sentinel evidence cannot be read. Reconnect to the private Tailscale HTTPS origin.</small></main></body></html>",
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
""".strip()


__all__ = ["MANIFEST", "SERVICE_WORKER"]
