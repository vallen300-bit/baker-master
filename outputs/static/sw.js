// Baker Push Service Worker (E3 + Baker 3.0 Digest)
var SW_VERSION = '2';

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
