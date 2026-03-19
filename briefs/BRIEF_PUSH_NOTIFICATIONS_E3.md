# BRIEF: E3 — Web Push Notifications (Service Worker)

**For:** Code Brisen (Mac Mini)
**From:** AI Head (Session 27)
**Priority:** High — T1/T2 alerts only reach the Director when the browser tab is open. He needs push when the PWA is closed.
**Branch:** `feat/push-notifications-e3`

---

## Context

Session 26 shipped **REALTIME-PUSH-1** — an SSE-based real-time alert system:
- Backend: `GET /api/alerts/stream?key=...` polls every 10s, emits `{"type":"new_alert","id":...,"tier":...,"title":...,"source":...}`
- Desktop (`app.js`): `_connectAlertStream()` at line ~4106 opens an `EventSource`, calls `_showAlertToast()` + `_sendBrowserNotification()` + `_playT1Beep()`
- Mobile (`mobile.js`): `_connectMobileAlertStream()` at line ~1035 opens an `EventSource`, calls `_showMobileToast()` + `new Notification()`
- Both pages request `Notification.requestPermission()` on load

**The problem:** All of this requires the tab to be open. When the Director closes Safari or switches apps on his iPhone, the EventSource disconnects and `new Notification()` never fires. **Web Push via a Service Worker** is the only way to reach a closed PWA.

**PWA already exists:** `mobile.html` links to `/static/manifest.json` (line 11). The manifest has `"display":"standalone"` and the Baker icon. No service worker is registered yet.

---

## Architecture

```
create_alert() [store_back.py]
  │
  ├── existing: T1 → WhatsApp push
  ├── existing: T1 → invalidate morning narrative
  │
  └── NEW: T1/T2 → send_web_push_to_all_subscribers()
         │
         └── pywebpush.webpush() per subscription
               │
               └── Push service (Apple/Google) → Service Worker
                     │
                     └── self.registration.showNotification()
                           │
                           └── Click → open Baker dashboard/mobile
```

---

## Deliverables

### 1. Service Worker (`/static/sw.js`) — NEW FILE

Create `outputs/static/sw.js`:

```js
// Baker Push Service Worker
const SW_VERSION = '1';

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

    var tier = data.tier || 2;
    var title = 'Baker T' + tier + ' Alert';
    var options = {
        body: (data.title || '').substring(0, 200),
        icon: '/static/baker-face-green.svg',
        badge: '/static/baker-face-green.svg',
        tag: 'baker-alert-' + (data.id || Date.now()),
        renotify: true,
        data: {
            url: data.url || '/mobile',
            alert_id: data.id,
        },
    };

    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// Notification click — open Baker
self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    var url = (event.notification.data && event.notification.data.url) || '/mobile';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clients) {
            // Focus existing Baker tab if found
            for (var i = 0; i < clients.length; i++) {
                if (clients[i].url.includes('/mobile') || clients[i].url.includes('/static/index')) {
                    return clients[i].focus();
                }
            }
            // Otherwise open a new tab
            return self.clients.openWindow(url);
        })
    );
});
```

### 2. Register SW + Subscribe to Push — Frontend Changes

**File: `outputs/static/mobile.html`** (line ~17, before `</head>`):
No HTML changes needed — registration happens in JS.

**File: `outputs/static/mobile.js`** — add at the end of `init()`:

```js
// Register service worker + subscribe to Web Push
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').then(function(reg) {
        console.log('SW registered:', reg.scope);
        return reg.pushManager.getSubscription().then(function(sub) {
            if (sub) return sub; // already subscribed
            // Fetch VAPID public key from server
            return fetch('/api/push/vapid-key').then(function(r) { return r.json(); }).then(function(d) {
                var vapidKey = d.public_key;
                var raw = atob(vapidKey.replace(/-/g, '+').replace(/_/g, '/'));
                var arr = new Uint8Array(raw.length);
                for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
                return reg.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: arr,
                });
            });
        });
    }).then(function(sub) {
        if (sub) {
            // Send subscription to Baker backend
            bakerFetch('/api/push/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(sub.toJSON()),
            });
        }
    }).catch(function(e) {
        console.warn('Push subscription failed (non-fatal):', e);
    });
}
```

**File: `outputs/static/app.js`** — add identical SW registration block in `init()` after the `_connectAlertStream()` call (line ~4924). Adjust the notification click URL to `'/'` instead of `'/mobile'`.

**File: `outputs/static/index.html`** — no HTML changes needed (SW registers via JS).

Bump cache versions:
- `app.js?v=42` -> `app.js?v=43` in `index.html` line 295
- `mobile.js` — add `?v=N` bump in `mobile.html` line (currently no version param on mobile.js — add `?v=1`)
- `mobile.css?v=9` -> `mobile.css?v=10` in `mobile.html` line 17

### 3. Backend: Push Subscription Storage

**File: `memory/store_back.py`**

Add table initialization in `__init__()` (after the existing `_ensure_*` calls):

```python
self._ensure_push_subscriptions_table()
```

Add the method:

```python
def _ensure_push_subscriptions_table(self):
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id SERIAL PRIMARY KEY,
                endpoint TEXT NOT NULL UNIQUE,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_used_at TIMESTAMPTZ
            )
        """)
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.warning(f"push_subscriptions table init failed: {e}")
    finally:
        self._put_conn(conn)

def store_push_subscription(self, endpoint: str, p256dh: str, auth: str) -> bool:
    """Upsert a Web Push subscription."""
    conn = self._get_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO push_subscriptions (endpoint, p256dh, auth)
            VALUES (%s, %s, %s)
            ON CONFLICT (endpoint) DO UPDATE SET
                p256dh = EXCLUDED.p256dh,
                auth = EXCLUDED.auth,
                last_used_at = NOW()
        """, (endpoint, p256dh, auth))
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"store_push_subscription failed: {e}")
        return False
    finally:
        self._put_conn(conn)

def get_all_push_subscriptions(self) -> list:
    """Return all active push subscriptions."""
    conn = self._get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions")
        rows = cur.fetchall()
        cur.close()
        return [{"endpoint": r[0], "p256dh": r[1], "auth": r[2]} for r in rows]
    except Exception as e:
        logger.error(f"get_all_push_subscriptions failed: {e}")
        return []
    finally:
        self._put_conn(conn)

def remove_push_subscription(self, endpoint: str):
    """Remove a stale subscription (410 Gone from push service)."""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
        conn.commit()
        cur.close()
    except Exception as e:
        conn.rollback()
        logger.error(f"remove_push_subscription failed: {e}")
    finally:
        self._put_conn(conn)
```

### 4. Backend: Web Push Sending in `create_alert()`

**File: `memory/store_back.py`** — inside `create_alert()`, after the existing WhatsApp push block (line ~3296), add:

```python
# Web Push to all subscribers (T1 + T2)
if tier <= 2:
    try:
        self._send_web_push_all(alert_id, tier, title)
    except Exception as e:
        logger.warning(f"Web Push failed (non-fatal): {e}")
```

Add the helper method:

```python
def _send_web_push_all(self, alert_id: int, tier: int, title: str):
    """Send Web Push notification to all registered subscriptions."""
    import json as _json
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush not installed — skipping Web Push")
        return

    vapid_private = config.get("VAPID_PRIVATE_KEY", "")
    vapid_email = config.get("VAPID_CONTACT_EMAIL", "")
    if not vapid_private or not vapid_email:
        logger.debug("VAPID keys not configured — skipping Web Push")
        return

    subs = self.get_all_push_subscriptions()
    if not subs:
        return

    payload = _json.dumps({
        "id": alert_id,
        "tier": tier,
        "title": title[:200],
        "url": "/mobile",
    })

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims={"sub": f"mailto:{vapid_email}"},
                timeout=5,
            )
        except WebPushException as e:
            if "410" in str(e) or "404" in str(e):
                # Subscription expired — remove it
                self.remove_push_subscription(sub["endpoint"])
                logger.info(f"Removed expired push subscription: {sub['endpoint'][:60]}...")
            else:
                logger.warning(f"Web Push failed for {sub['endpoint'][:60]}: {e}")
        except Exception as e:
            logger.warning(f"Web Push error: {e}")
```

**Important:** Access VAPID keys from config. In `config/settings.py`, add:

```python
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_CONTACT_EMAIL = os.environ.get("VAPID_CONTACT_EMAIL", "")
```

Then reference via `config.VAPID_PRIVATE_KEY` etc. (check how other env vars are accessed in `config/settings.py` and follow the same pattern).

### 5. Backend: API Endpoints

**File: `outputs/dashboard.py`** — add two new endpoints:

```python
@app.get("/api/push/vapid-key", tags=["push"])
async def get_vapid_key():
    """Return the VAPID public key for Web Push subscription."""
    import os as _os
    pub = _os.environ.get("VAPID_PUBLIC_KEY", "")
    if not pub:
        raise HTTPException(status_code=503, detail="VAPID not configured")
    return {"public_key": pub}

@app.post("/api/push/subscribe", tags=["push"], dependencies=[Depends(verify_api_key)])
async def push_subscribe(request: Request):
    """Store a Web Push subscription from the client."""
    body = await request.json()
    endpoint = body.get("endpoint", "")
    keys = body.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=400, detail="Missing subscription fields")
    store = _get_store()
    ok = store.store_push_subscription(endpoint, p256dh, auth)
    return {"status": "ok" if ok else "error"}
```

Note: `/api/push/vapid-key` does NOT require auth (the SW needs the key before the user is "logged in"). `/api/push/subscribe` DOES require auth.

### 6. Dependencies

**File: `requirements.txt`** — add:

```
# Web Push (E3)
pywebpush>=2.0.0             # Web Push notifications via VAPID
```

---

## Env Vars (Director must add to Render)

| Var | Purpose |
|-----|---------|
| `VAPID_PRIVATE_KEY` | VAPID private key (base64url encoded) |
| `VAPID_PUBLIC_KEY` | VAPID public key (base64url encoded) |
| `VAPID_CONTACT_EMAIL` | Contact email for push service (e.g., `dimitry@brisengroup.com`) |

**Generate keys** (run locally):

```bash
pip install pywebpush
python3 -c "
from py_vapid import Vapid
v = Vapid()
v.generate_keys()
import base64
print('VAPID_PRIVATE_KEY:', base64.urlsafe_b64encode(v.private_key.private_bytes_raw()).decode())
print('VAPID_PUBLIC_KEY:', base64.urlsafe_b64encode(v.public_key.public_bytes_raw()).decode())
"
```

Alternatively use: `npx web-push generate-vapid-keys`

---

## Sequence

1. Add `pywebpush` to `requirements.txt`
2. Add VAPID config to `config/settings.py`
3. Add `push_subscriptions` table + CRUD methods to `store_back.py`
4. Add `_send_web_push_all()` to `store_back.py` (called from `create_alert()`)
5. Add `/api/push/vapid-key` + `/api/push/subscribe` to `dashboard.py`
6. Create `outputs/static/sw.js`
7. Add SW registration + push subscription to `mobile.js` (in `init()`)
8. Add SW registration + push subscription to `app.js` (in `init()`)
9. Bump cache versions
10. Push, test

---

## DO NOT Touch

- `orchestrator/*.py` — AI Head area
- `triggers/*.py` — AI Head area
- `tools/*.py` — AI Head area
- Do not modify the existing SSE alert stream logic — it stays as fallback for when the tab IS open

---

## Testing

1. Deploy to Render with VAPID env vars set
2. Open `/mobile` on iPhone, add to home screen
3. Allow notifications when prompted
4. Verify: Network tab shows `sw.js` fetched, `POST /api/push/subscribe` succeeds
5. Close the PWA entirely (swipe up in app switcher)
6. Wait for a T1 or T2 alert (or create one: ask Baker "test alert" which triggers a T2)
7. Verify: push notification arrives on the lock screen
8. Tap notification -> Baker opens to `/mobile`
9. Repeat on desktop Chrome/Safari

**iOS caveat:** Web Push on iOS requires iOS 16.4+ and the page must be added to home screen (PWA). Safari-only tabs do not support Web Push. This is fine — the Director already uses it as a PWA.

---

## Acceptance Criteria

- [ ] Service worker registers on both desktop and mobile pages
- [ ] Push subscription is stored in `push_subscriptions` table
- [ ] T1/T2 alerts trigger Web Push to all subscribers
- [ ] Notification appears even when the browser/PWA is closed
- [ ] Clicking the notification opens Baker
- [ ] Expired subscriptions (410) are auto-removed
- [ ] Existing SSE real-time alerts still work (not broken)
- [ ] VAPID keys are env vars, not hardcoded
