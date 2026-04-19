# BRIEF: MORNING-DIGEST-FANOUT-1 — Multi-channel morning & evening push

> **🅿️ PARKED** — 2026-04-19 by AI Head. Reason: competes with Cortex T3 ship-first priority per Director ratification. Unpark after T3 in production. See `README.md` in this folder for the parking convention.
>
> **Attribution note:** brief header self-attributes to "AI Head" but was actually authored by R (Code Research agent) in a separate Cowork session. Current live AI Head did not draft this brief. Flag for clarity when unparking.

**Author:** AI Head (per header; actual author: Code Research agent R)
**Date:** 2026-04-19
**For:** Code Brisen
**Status:** PARKED (was: Ready for review)
**Complexity:** Low
**Estimated time:** ~2-3h

---

## Context

Morning + evening digests exist and ship on schedule (07:00 / 18:00 UTC) but only reach **Web Push**. Director uses Slack and WhatsApp throughout the day; a digest on one channel is easily missed. Classic Chief-of-Staff pattern requires the brief to land where Director actually looks.

Also: the current push body is a 3-line title preview (`_format_preview`). The Gemini-generated narrative that powers the dashboard landing page is **not** included. It should be the core of the WhatsApp and Slack digests.

Email is out-of-scope by policy (`.claude/rules/api-safety.md`: "Proactive emails DISABLED — draft-only").

---

## Problem

1. `send_morning_digest()` and `send_evening_digest()` only call `send_push()` (Web Push via pywebpush). On iOS with PWA not installed, this is invisible.
2. Narrative from `_get_morning_narrative()` is never delivered — only surfaced when Director opens the dashboard.
3. No Slack / WhatsApp output path for digests, despite both senders being battle-tested for alerts.

---

## Current State

**Files already in place — do not re-implement:**

| What | Where |
|------|-------|
| `send_morning_digest()` scheduled job | `outputs/push_sender.py:239` |
| `send_evening_digest()` scheduled job | `outputs/push_sender.py:263` |
| `gather_morning_items()` → `list[dict]` | `outputs/push_sender.py:79` |
| `gather_evening_items()` → `list[dict]` | `outputs/push_sender.py:167` |
| `send_push(title, body, url, tag)` | `outputs/push_sender.py:20` |
| `send_whatsapp(text, chat_id=DIRECTOR_WHATSAPP)` | `outputs/whatsapp_sender.py:19` |
| `SlackNotifier().post_briefing(briefing_text, date_str)` | `outputs/slack_notifier.py:151` |
| `_get_morning_narrative(fire_count, deadline_count, processed, top_fires, deadlines=None, silent_contacts=None)` — returns dict `{"narrative": str, "proposals": list}` OR cached str if cache hit | `outputs/dashboard.py:3547` |
| APScheduler registration | `triggers/embedded_scheduler.py:492-511` (cron `hour=7, minute=0` UTC and `hour=18, minute=0` UTC) |

**Cache quirk (must handle):** `_morning_narrative_cache["text"]` stores the raw result. Recent calls return a `dict {"narrative":..., "proposals":...}`; older cached entries may be a bare string. Handle both.

**Director WhatsApp filter (must respect):** `send_whatsapp()` suppresses messages to `DIRECTOR_WHATSAPP` containing keywords `cost alert`, `budget exceeded`, `daily spend`, `circuit breaker`. Our digest must avoid those phrases — already safe because the narrative prompt doesn't produce them, but document it.

---

## Implementation

### Fix 1 — Add `compose_digest_text(kind, items, narrative)` helper

**File:** `outputs/push_sender.py`

Add just above `send_morning_digest` (around line 236):

```python
def _normalize_narrative(narrative_obj) -> str:
    """_get_morning_narrative returns dict now, str historically. Normalize."""
    if isinstance(narrative_obj, dict):
        return (narrative_obj.get("narrative") or "").strip()
    if isinstance(narrative_obj, str):
        return narrative_obj.strip()
    return ""


def compose_digest_text(kind: str, items: list, narrative: str = "") -> str:
    """
    Compose the digest body for WhatsApp / Slack.
    kind: 'morning' or 'evening'.
    narrative: optional Gemini-generated prose (morning only).
    Items come from gather_morning_items / gather_evening_items.
    """
    header = "Good morning." if kind == "morning" else "End of day."
    lines: list[str] = []
    if narrative:
        lines.append(narrative)
        lines.append("")

    # Group items by type for scan-friendly output
    alerts = [i for i in items if i.get("type") == "alert"]
    deadlines = [i for i in items if i.get("type") == "deadline"]
    unanswered = [i for i in items if i.get("type") == "unanswered"]

    if alerts:
        lines.append(f"*Fires ({len(alerts)})*")
        for a in alerts[:5]:
            title = (a.get("title") or "").strip()[:100]
            desc = (a.get("description") or "").strip()[:60]
            lines.append(f"• {title} — {desc}" if desc else f"• {title}")
        lines.append("")

    if deadlines:
        lines.append(f"*Deadlines ({len(deadlines)})*")
        for d in deadlines[:5]:
            title = (d.get("title") or "").strip()[:100]
            desc = (d.get("description") or "").strip()[:60]
            lines.append(f"• {title} — {desc}" if desc else f"• {title}")
        lines.append("")

    if unanswered:
        lines.append(f"*Unanswered VIPs ({len(unanswered)})*")
        for u in unanswered[:5]:
            title = (u.get("title") or "").strip()[:100]
            lines.append(f"• {title}")
        lines.append("")

    body = "\n".join(lines).strip()
    # Header only if nothing else
    return body if body else header
```

### Fix 2 — Extend `send_morning_digest()` with Slack + WhatsApp fan-out

**File:** `outputs/push_sender.py:239`

Replace the entire `send_morning_digest` body with:

```python
def send_morning_digest():
    """Scheduled job (07:00 UTC): gather morning items + send Web Push + WhatsApp + Slack."""
    from triggers.sentinel_health import report_success, report_failure
    try:
        items = gather_morning_items()
        if not items:
            logger.info("Morning digest: no items to push")
            report_success("morning_digest")
            return

        # Narrative (reuse dashboard generator) — non-fatal on failure
        narrative = ""
        try:
            fire_count = sum(1 for i in items if i.get("type") == "alert")
            deadline_count = sum(1 for i in items if i.get("type") == "deadline")
            top_fires = [i for i in items if i.get("type") == "alert"][:3]
            from outputs.dashboard import _get_morning_narrative  # lazy import to avoid cycles
            narrative = _normalize_narrative(
                _get_morning_narrative(fire_count, deadline_count, 0, top_fires)
            )
        except Exception as e:
            logger.warning(f"Morning digest narrative fetch failed (continuing): {e}")

        count = len(items)
        digest_text = compose_digest_text("morning", items, narrative)

        # 1) Web Push (existing)
        send_push(
            title=f"Good morning. {count} item{'s' if count != 1 else ''} need attention.",
            body=(narrative or _format_preview(items))[:200],
            url="/mobile?tab=digest&type=morning",
            tag="baker-morning-" + datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

        # 2) WhatsApp (Director only) — non-fatal
        try:
            from outputs.whatsapp_sender import send_whatsapp
            send_whatsapp(f"*Baker morning digest*\n\n{digest_text}")
        except Exception as e:
            logger.warning(f"Morning digest WhatsApp failed (continuing): {e}")

        # 3) Slack #cockpit — non-fatal
        try:
            from outputs.slack_notifier import SlackNotifier
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            SlackNotifier().post_briefing(digest_text, date_str)
        except Exception as e:
            logger.warning(f"Morning digest Slack failed (continuing): {e}")

        report_success("morning_digest")
        logger.info(f"Morning digest fan-out sent: {count} items")
    except Exception as e:
        report_failure("morning_digest", str(e))
        logger.error(f"Morning digest failed: {e}")
```

### Fix 3 — Same fan-out for evening digest

**File:** `outputs/push_sender.py:263`

Mirror the pattern in `send_evening_digest()`. Evening has **no narrative** generation today — skip the narrative block, pass empty string to `compose_digest_text("evening", items, "")`. Do NOT try to generate an evening narrative in this brief — out of scope.

```python
def send_evening_digest():
    """Scheduled job (18:00 UTC): gather evening items + send Web Push + WhatsApp + Slack."""
    from triggers.sentinel_health import report_success, report_failure
    try:
        items = gather_evening_items()
        if not items:
            logger.info("Evening digest: no items to push")
            report_success("evening_digest")
            return

        count = len(items)
        digest_text = compose_digest_text("evening", items, "")

        send_push(
            title=f"End of day. {count} item{'s' if count != 1 else ''}.",
            body=_format_preview(items),
            url="/mobile?tab=digest&type=evening",
            tag="baker-evening-" + datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        )

        try:
            from outputs.whatsapp_sender import send_whatsapp
            send_whatsapp(f"*Baker evening digest*\n\n{digest_text}")
        except Exception as e:
            logger.warning(f"Evening digest WhatsApp failed (continuing): {e}")

        try:
            from outputs.slack_notifier import SlackNotifier
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            SlackNotifier().post_briefing(digest_text, date_str)
        except Exception as e:
            logger.warning(f"Evening digest Slack failed (continuing): {e}")

        report_success("evening_digest")
        logger.info(f"Evening digest fan-out sent: {count} items")
    except Exception as e:
        report_failure("evening_digest", str(e))
        logger.error(f"Evening digest failed: {e}")
```

---

## Key Constraints

- **Non-fatal fan-out:** each of Web Push / WhatsApp / Slack is wrapped in its own try/except. One failing channel must NOT block the others. This matches Baker's existing fault-tolerant-writes pattern (`.claude/rules/python-backend.md`).
- **Lazy import `_get_morning_narrative`** (`from outputs.dashboard import ...` inside function body) to avoid a circular import at module load. `outputs.dashboard` already imports from other `outputs.*` modules.
- **Do not change the schedule.** Time-zone discussion (e.g. move 07:00 UTC → 05:30 UTC for 7:30 CEST) is a separate decision. Default behaviour preserved.
- **Do not add a new Director approval step.** Both WhatsApp (Director only) and Slack #cockpit are internal channels — auto-send is allowed per existing policy. Email remains draft-only and is out of scope.
- **Do not broadcast WhatsApp beyond `DIRECTOR_WHATSAPP`.** The brief only sends to Director; no contact-list iteration.
- **Do not introduce a new LLM call for evening** — evening digest stays as-is for now. Narrative-for-evening is a follow-up brief.
- **Verify `_normalize_narrative` handles the str-vs-dict cache quirk** — the cache was populated with bare strings historically and dicts from Phase 3B onwards. Must not crash on either.

---

## Files Modified

- `outputs/push_sender.py` — add `_normalize_narrative`, `compose_digest_text`, modify `send_morning_digest` + `send_evening_digest`

## Do NOT Touch

- `outputs/dashboard.py` — do not refactor `_get_morning_narrative`. Lazy-import only.
- `outputs/whatsapp_sender.py` — do not alter the cost-alert keyword filter.
- `outputs/slack_notifier.py` — reuse `post_briefing` as-is (Block Kit formatting lives there).
- `triggers/embedded_scheduler.py` — schedule stays on 07:00 / 18:00 UTC.

## Quality Checkpoints

1. Python syntax check: `python3 -c "import py_compile; py_compile.compile('outputs/push_sender.py', doraise=True)"`
2. Restart Render; confirm logs show `Registered: morning_push_digest (daily 07:00 UTC)` on boot.
3. Manual trigger locally: `python -c "from outputs.push_sender import send_morning_digest; send_morning_digest()"` with DB + env vars set. Check:
   - Director's WhatsApp receives "Baker morning digest"
   - `#cockpit` receives a Block Kit briefing
   - Web Push is still delivered (unchanged path)
4. Force one channel to fail (e.g. kill `WHATSAPP_API_KEY` temporarily) and confirm the other two still deliver (fault isolation).
5. Check Slack mobile rendering (iPhone) — `post_briefing` uses Block Kit so it should already render well, but verify. Reference `lessons.md` #8 on desktop-only-testing pitfall.
6. Confirm cached narrative path is exercised (call `send_morning_digest` twice within 30 min; second call should reuse cache, WhatsApp still receives the text).

## Verification SQL

```sql
-- After next 07:00 UTC tick, confirm sentinel health recorded success
SELECT sentinel, last_success_at, last_failure_at, failure_count
FROM sentinel_health
WHERE sentinel IN ('morning_digest', 'evening_digest')
ORDER BY sentinel
LIMIT 2;

-- Confirm alerts feeding the digest are present
SELECT COUNT(*) AS pending_t1_t2
FROM alerts
WHERE status = 'pending' AND tier <= 2;

-- Confirm Slack delivery succeeded (if slack_messages table exists, otherwise skip)
SELECT sent_at, channel_id, substring(text, 1, 80) AS preview
FROM slack_messages
WHERE sent_at > NOW() - INTERVAL '2 hours'
  AND text ILIKE '%morning digest%'
ORDER BY sent_at DESC
LIMIT 5;
```

## Rollback

Revert the one file: `git revert <commit>` on `outputs/push_sender.py`. Schedule and signatures unchanged elsewhere, so revert is clean.

## Out of Scope (follow-ups)

- Evening narrative generation via Gemini (mirror of `_get_morning_narrative`)
- Time-zone shift to 7:30 CET (policy decision required)
- V2 interactive action cards on dashboard — already briefed in `briefs/BRIEF_MORNING_BRIEF_V2.md`; separate frontend work
- Email digest — blocked by policy (draft-only)
- Per-matter opt-in/out routing
