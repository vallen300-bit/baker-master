# BRIEF: Baker 3.0 — Item 1: Push Notifications (Two Daily Digests)

**Author:** AI Head
**Date:** 2026-03-22
**Priority:** HIGH — makes Baker always-present
**Effort:** 1 session
**Assigned to:** Code 300
**Depends on:** None (independent of other items)

---

## What We're Building

Baker sends exactly 2 consolidated push notifications per day to the Director's phone. Each notification opens the mobile PWA to a digest screen where items have action buttons.

- **Morning push:** 07:00 UTC — new items needing attention
- **Evening push:** 18:00 UTC — end-of-day wrap-up

Plus: T1 crisis breakthrough (rare, max 1-2/week).

---

## Architecture

```
Baker scheduled jobs (07:00 + 18:00 UTC)
    ↓
Gather items for digest (from alerts, proposed_actions, deadlines, etc.)
    ↓
Web Push API → sends notification to Director's phone
    "6 items need attention" [Open]
    ↓
Director taps notification → opens /mobile?tab=digest
    ↓
Digest screen shows all items with per-item action buttons
```

---

## Backend: New Endpoints + Scheduler Jobs

### `outputs/dashboard.py` — New endpoints

```python
# Push subscription management
@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    """Store push subscription from client (endpoint, keys)."""
    # Save to push_subscriptions table (NEW)

@app.delete("/api/push/subscribe")
async def push_unsubscribe(request: Request):
    """Remove push subscription."""

# Digest data
@app.get("/api/digest/morning")
async def morning_digest():
    """Gather items for morning digest."""
    # Sources:
    # - Pending alerts (T1/T2 from overnight)
    # - Proposed actions (from obligation generator)
    # - Deadlines approaching (next 3 days)
    # - Unanswered VIP messages (>4h)
    # - Completed dossiers
    # - signal_extractions highlights (from Item 0a, when available)
    return {"items": [...], "count": N}

@app.get("/api/digest/evening")
async def evening_digest():
    """Gather items for evening digest."""
    # Sources:
    # - Unfulfilled commitments from today
    # - Tomorrow's meetings + prep status
    # - Actions completed today (confirmation)
    # - Items deferred from morning still pending
    return {"items": [...], "count": N}
```

### Database: `push_subscriptions` table (NEW)

```sql
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id SERIAL PRIMARY KEY,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Scheduler Jobs: `triggers/embedded_scheduler.py`

Add 2 new jobs:

```python
# Job 30: Morning push digest
scheduler.add_job(
    send_morning_digest, 'cron',
    hour=7, minute=0,  # 07:00 UTC
    id='morning_push_digest',
    misfire_grace_time=300
)

# Job 31: Evening push digest
scheduler.add_job(
    send_evening_digest, 'cron',
    hour=18, minute=0,  # 18:00 UTC
    id='evening_push_digest',
    misfire_grace_time=300
)
```

### Push Sending Logic: `outputs/push_sender.py` (NEW)

```python
from pywebpush import webpush, WebPushException
import json, os

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS = {"sub": "mailto:baker@brisengroup.com"}

def send_push(title: str, body: str, url: str = "/mobile?tab=digest", tag: str = "digest"):
    """Send push notification to all subscribed devices."""
    # Query push_subscriptions table
    # For each subscription: webpush(subscription, data, vapid)

def send_morning_digest():
    """Scheduled job: gather morning items + send push."""
    items = _gather_morning_items()
    if not items:
        return
    count = len(items)
    send_push(
        title=f"Good morning. {count} items need attention.",
        body=_format_preview(items[:3]),  # First 3 items as preview text
        url="/mobile?tab=digest&type=morning"
    )

def send_evening_digest():
    """Scheduled job: gather evening items + send push."""
    items = _gather_evening_items()
    if not items:
        return
    count = len(items)
    send_push(
        title=f"End of day. {count} items.",
        body=_format_preview(items[:3]),
        url="/mobile?tab=digest&type=evening"
    )

def send_crisis_push(title: str, body: str):
    """T1 breakthrough push — only for genuine crises."""
    # Check quiet hours (22:00-07:00 UTC) — skip unless T1
    # Check daily cap — max 1 crisis push per day
    send_push(title=title, body=body, url="/mobile?tab=fires", tag="crisis")
```

---

## Frontend: Service Worker + Digest Screen

### `outputs/static/sw.js` (NEW — Service Worker)

```javascript
// Service Worker for push notifications

self.addEventListener('push', function(event) {
    var data = event.data ? event.data.json() : {};
    event.waitUntil(
        self.registration.showNotification(data.title || 'Baker', {
            body: data.body || '',
            icon: '/static/baker-icon-192.png',
            badge: '/static/baker-badge-72.png',
            tag: data.tag || 'digest',
            data: { url: data.url || '/mobile?tab=digest' },
            // Max 2 actions on mobile (Cowork pushback #3)
            actions: [
                { action: 'open', title: 'Open' },
                { action: 'dismiss', title: 'Dismiss' }
            ]
        })
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    var url = event.notification.data.url || '/mobile?tab=digest';
    event.waitUntil(clients.openWindow(url));
});
```

### `outputs/static/mobile.html` — Modify

Add Service Worker registration:
```javascript
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js');
}
```

Add push subscription button in settings/header area.

### `outputs/static/mobile.js` — Modify

Add new tab: `digest`

```javascript
async function loadDigestTab(type) {
    // type = 'morning' or 'evening'
    var endpoint = '/api/digest/' + (type || 'morning');
    var data = await bakerFetch(endpoint).then(r => r.json());
    var items = data.items || [];

    // Render each item as a card with action buttons
    items.forEach(function(item) {
        // Each item gets:
        // - Title + description
        // - Source badge (email, meeting, deadline, etc.)
        // - Positive action button (Run, Draft, Open, Download, View)
        // - Negative action button (Skip, Dismiss, Defer)
        renderDigestItem(item);
    });
}

function renderDigestItem(item) {
    // Card with:
    // - item.title
    // - item.description
    // - item.source (badge)
    // - item.positive_action → {label: "Run", endpoint: "/api/...", method: "POST"}
    // - item.negative_action → {label: "Skip", endpoint: "/api/...", method: "POST"}
}

// Push subscription
async function subscribePush() {
    var reg = await navigator.serviceWorker.ready;
    var sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: VAPID_PUBLIC_KEY
    });
    await bakerFetch('/api/push/subscribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sub.toJSON())
    });
}
```

### `outputs/static/mobile.css` — Modify

Add digest card styles (similar to existing action cards).

---

## Push Notification UX (Cowork Pushback #3 — Resolved)

Push notification itself is simple:
- **Title:** "Good morning. 6 items need attention."
- **Body:** Preview of first 2-3 items
- **Actions:** [Open] [Dismiss] (max 2 buttons on mobile Web Push)
- **Tap:** Opens `/mobile?tab=digest` with full interactive list

The rich interactive buttons (Run, Draft, Skip, etc.) live in the **digest screen**, not in the push notification itself.

---

## T1 Crisis Breakthrough

```python
# In pipeline.py or alert creation, when T1 alert is created:
if tier == 1 and _is_outside_digest_window():
    from outputs.push_sender import send_crisis_push
    send_crisis_push(
        title=f"URGENT: {alert_title}",
        body=alert_body[:200]
    )
```

Rules:
- Only during non-quiet hours (07:00-22:00 UTC) unless genuine T1
- Max 1 crisis push per day
- T1 = VIP SLA breach, compounding risk, legal deadline today

---

## Requirements

- `pywebpush` package (add to requirements.txt)
- VAPID keys already generated (Session 28) — need to add to Render env vars:
  - `VAPID_PRIVATE_KEY`
  - `VAPID_PUBLIC_KEY`

---

## Testing

1. **Service Worker:** Open /mobile → verify SW registered in DevTools
2. **Push subscription:** Click "Enable notifications" → verify subscription saved in DB
3. **Morning digest:** Call `/api/digest/morning` → verify items gathered correctly
4. **Push send:** Trigger `send_morning_digest()` → verify notification arrives on phone
5. **Tap to open:** Tap notification → verify /mobile?tab=digest opens with items
6. **Action buttons:** Tap Run/Skip on digest items → verify API calls work
7. **Crisis push:** Create T1 alert → verify breakthrough notification arrives
8. **Quiet hours:** Create T1 alert at 23:00 → verify no push (unless genuine T1)

---

## Files Created/Modified

| File | Change |
|------|--------|
| `outputs/push_sender.py` | NEW — push sending logic + digest gathering |
| `outputs/static/sw.js` | NEW — Service Worker |
| `outputs/dashboard.py` | New endpoints: push subscribe, morning/evening digest |
| `outputs/static/mobile.html` | SW registration + push subscribe UI |
| `outputs/static/mobile.js` | Digest tab + push subscription logic |
| `outputs/static/mobile.css` | Digest card styles |
| `triggers/embedded_scheduler.py` | 2 new jobs: morning + evening push |
| `requirements.txt` | Add pywebpush |
