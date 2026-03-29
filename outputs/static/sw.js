// Baker Push + PWA Service Worker (E3 + Baker 3.0 Digest + PWA-DESKTOP-1)
var SW_VERSION = '3';

// Install — activate immediately
self.addEventListener('install', function(event) {
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    event.waitUntil(self.clients.claim());
});

// Push event — fires even when the browser tab is closed
self.addEventListener('push', function(event) {
    var data = {};
    try {
        data = event.data.json();
    } catch (e) {
        data = { title: 'Baker Alert', body: event.data ? event.data.text() : '' };
    }

    var title = data.title || 'Baker';
    var options = {
        body: (data.body || '').substring(0, 200),
        icon: '/static/baker-face-green.svg',
        badge: '/static/baker-face-green.svg',
        tag: data.tag || 'baker-' + Date.now(),
        renotify: true,
        data: {
            url: data.url || '/mobile',
        },
    };

    // Digest notifications (morning/evening)
    if (data.type === 'digest') {
        options.actions = [
            { action: 'open', title: 'Open' },
            { action: 'dismiss', title: 'Later' }
        ];
    }

    // Legacy: alert-based push
    if (data.tier) {
        title = 'Baker T' + data.tier + ' Alert';
        options.body = (data.title || '').substring(0, 200);
        options.tag = 'baker-alert-' + (data.id || Date.now());
        options.data.alert_id = data.id;
    }

    // Morning triage override
    if (data.type === 'morning_triage') {
        title = 'Baker Morning Triage';
        options.body = data.title;
        options.tag = 'baker-morning-' + new Date().toISOString().slice(0, 10);
        options.data.url = '/mobile?tab=actions';
    }

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// PWA-DESKTOP-1: Fetch handler — network-first (required for PWA installability)
self.addEventListener('fetch', function(event) {
    // Network-first: always fetch from server, no offline caching
    // Baker is a live dashboard — stale data is worse than no data
    event.respondWith(
        fetch(event.request).catch(function() {
            // Offline fallback — only for navigation requests
            if (event.request.mode === 'navigate') {
                return new Response(
                    '<html><body style="background:#0D0F14;color:#ccc;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;">' +
                    '<div style="text-align:center;"><h1 style="color:#c9a96e;">Baker</h1><p>You are offline. Baker needs a network connection.</p></div></div></body></html>',
                    { headers: { 'Content-Type': 'text/html' } }
                );
            }
        })
    );
});

// Notification click — open Baker
self.addEventListener('notificationclick', function(event) {
    event.notification.close();

    if (event.action === 'dismiss') return;

    var url = (event.notification.data && event.notification.data.url) || '/mobile';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clients) {
            // Focus existing Baker tab if found
            for (var i = 0; i < clients.length; i++) {
                if (clients[i].url.includes('/mobile') || clients[i].url.includes('/static/index')) {
                    clients[i].navigate(url);
                    return clients[i].focus();
                }
            }
            // Otherwise open a new tab
            return self.clients.openWindow(url);
        })
    );
});
