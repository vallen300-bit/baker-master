# BRIEF: Notification & Task Management Redesign

**Status:** SHIPPED (Session 30, 2026-03-20)
**Scope:** Obligation generator, morning push, mobile triage card deck, push throttling

---

## What Changed

Todoist is dead. Baker now proposes your daily actions and you triage them in 2 minutes.

### The Loop

```
06:50 UTC: Baker scans signals (deadlines, silent contacts, unanswered emails, alerts)
  → Haiku extracts 5-15 SPECIFIC task proposals
  → Stores each in proposed_actions table
  → Sends ONE morning push: "Baker has N actions for today"

You tap the push notification:
  → Opens /mobile → Actions tab
  → Swipe RIGHT = approve
  → Swipe LEFT = skip
  → Buttons: "Done" (already handled) or "Approve"
  → 2 minutes, done for the day
```

### What Baker Proposes

Each card has:
- **Source badge** — color-coded: email (blue), WhatsApp (green), meeting (purple), deadline (red), cadence (cyan)
- **Title** — specific: "Follow up with Robin on Kempinski timeline"
- **Description** — context: "18 days silent, normally responds every 5 days"
- **Suggested action** — "Send one-line check-in asking about timeline"
- **Due date** — red if overdue

### Push Throttling (new)

Baker no longer spams your phone:
- **Quiet hours:** 22:00–07:00 CET — no pushes (except T1 emergencies)
- **Daily cap:** max 8 pushes per day
- **Cooldown:** 15 min between pushes
- **T1 bypass:** urgent alerts always break through

---

## Files

| File | What |
|------|------|
| `orchestrator/obligation_generator.py` | NEW — signal gathering, Haiku extraction, storage, morning push |
| `memory/store_back.py` | Push throttling (quiet hours, cap, cooldown) |
| `outputs/dashboard.py` | 4 new API endpoints |
| `outputs/static/mobile.html` | Actions tab (4th tab) |
| `outputs/static/mobile.js` | Triage card deck with swipe |
| `outputs/static/mobile.css` | Card styles, source badges, swipe animations |
| `outputs/static/sw.js` | Morning triage push deep link |
| `triggers/embedded_scheduler.py` | 28th scheduler job (06:50 UTC) |
| `config/settings.py` | Throttle config on WebPushConfig |

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/proposed-actions?status=proposed` | List actions for triage |
| GET | `/api/proposed-actions/count` | Badge count |
| POST | `/api/proposed-actions/{id}/respond` | Approve/dismiss/done/escalated |
| POST | `/api/admin/run-obligation-generator` | Manual trigger |

## What's NOT Built (next sprint)

- **Todoist write-back** — blocked by expired API token (401)
- **Auto-completion detection** — observe if approved action was actually done
- **Dismissal learning** — stop proposing things Director always skips
- **Escalate flow** — assign to someone else (UI exists, backend ready)

## How to Test

1. `POST /api/admin/run-obligation-generator` — generates actions now
2. Open `/mobile?tab=actions` — see the card deck
3. Swipe or tap to triage
4. Tomorrow morning: push notification arrives at 08:50 CET
