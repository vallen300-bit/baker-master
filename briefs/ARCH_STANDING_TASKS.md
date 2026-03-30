# Standing Tasks Architecture — Baker Autonomous Goal Pursuit

**Status:** Designed, not yet implemented
**Designed:** Session 40, March 30 2026
**Estimated effort:** 5 batches, ~15 hours coding

## Concept

Director tells Baker: "Reschedule Sandra to after 12:00. Stay in contact until resolved."

Baker: stores goal → drafts email (Director approves) → monitors for reply → Haiku evaluates against criteria → auto-confirms if met / escalates if not → notifies Director when done.

## Database

### `standing_tasks` table
- id, title, goal, success_criteria (JSONB), contact_name, contact_email, contact_whatsapp_id, contact_channel
- auto_reply_allowed, auto_reply_constraints, escalation_triggers (JSONB), max_auto_replies (default 5)
- status: draft → active → waiting_reply → criteria_met/escalated → resolved/expired/cancelled
- last_outbound_at, last_inbound_at, reply_count, auto_reply_count
- gmail_thread_id (track the email thread)
- ttl_hours (default 48), expires_at, created_at, resolved_at, resolution_summary

### `standing_task_events` table
- id, task_id (FK), event_type, direction (inbound/outbound), channel, content_summary, full_content, evaluation_result (JSONB), source_id

### success_criteria JSONB structure
```json
{
  "description": "Meeting rescheduled to any time after 12:00",
  "conditions": [{"type": "time_constraint", "operator": "after", "value": "12:00"}],
  "acceptable_outcomes": ["Sandra confirms a time after 12:00"],
  "unacceptable_outcomes": ["Meeting cancelled", "Time before 12:00"]
}
```

## Safety Model

| Action | Auto? | Condition |
|--------|-------|-----------|
| Initial email | NO | Director approves draft first |
| Auto-reply (criteria met, confirm) | YES | Haiku confidence >= 0.85 |
| Auto-reply (scheduling question) | YES | Within scope + rate limit + count limit |
| Reply when criteria NOT met | NO | Escalate to Director |
| Anything outside task scope | NO | Escalate |

**Rate limit:** Max 1 outbound per 12h unless contact replied first. Max 5 auto-replies per task.

## Evaluation Engine

Single Haiku call per inbound message (~EUR 0.002). Returns:
- criteria_met (bool), confidence (0-1), reasoning
- proposed_action: auto_confirm / auto_reply / escalate / wait
- auto_reply_draft (if applicable)
- extracted_proposal ("14:00 on Monday")

**Thresholds:** auto_confirm >= 0.85 confidence, auto_reply >= 0.70, else escalate.

## Integration Points

1. **Email trigger** (`triggers/email_trigger.py`): After `_check_reply_match()`, add `check_standing_task_match()` — matches sender_email or gmail_thread_id against active tasks
2. **WhatsApp webhook** (`triggers/waha_webhook.py`): Same pattern for non-Director messages matching contact_whatsapp_id
3. **Intent classifier** (`orchestrator/action_handler.py`): New intent type `standing_task_create` — "stay in contact with X until Y"
4. **Scheduler** (`triggers/embedded_scheduler.py`): New job `standing_task_ttl_check` every 30 min — expire old tasks, send reminders
5. **Draft approval flow**: Existing `pending_drafts` pattern reused — on confirmation, activate the standing task

## New Module

`orchestrator/standing_task_engine.py` — single file with:
- create_standing_task(), activate_standing_task()
- check_standing_task_match(), evaluate_reply()
- execute_auto_reply(), execute_auto_confirm()
- escalate_to_director(), handle_director_override()
- run_ttl_check(), cancel_standing_task()

## Implementation Batches

- **Batch 0:** DB schema + engine core (4h)
- **Batch 1:** Intent classification + creation flow (3h)
- **Batch 2:** Inbound matching + Haiku evaluation (3h)
- **Batch 3:** Director notifications + override commands (2h)
- **Batch 4:** API + dashboard cards (2h)
- **Batch 5:** Testing + hardening (2h)

## API Endpoints

- POST /api/standing-tasks — create
- GET /api/standing-tasks — list (filter by status)
- GET /api/standing-tasks/{id} — detail + events
- POST /api/standing-tasks/{id}/approve — approve initial email, activate
- POST /api/standing-tasks/{id}/override — Director manual reply/extend/update
- POST /api/standing-tasks/{id}/cancel — cancel task

## Edge Cases Handled

- Contact replies to different thread → match by sender_email, not just thread_id
- Contact calls instead of emails → Fireflies transcript check → prompt Director
- Director changes mind → intent classifier detects "cancel standing task" / "change criteria"
- Two tasks same contact → allowed, but warn Director; Haiku routes replies to correct task
- Robotic tone → auto-replies use full conversation context, match Director's initial tone

## Cost

~EUR 0.03/day total. All on Haiku. Negligible.
