# BB Desk — Airside Onward-Journey Reply SOP (DRAFT 1)

**For:** baden-baden-desk (the agent woken by lead on the Mac Mini)
**Source of truth for the grammar:** `orchestrator/airport_boarding_flow.py :: parse_desk_reply`
**Status:** DRAFT for lead to install vault-side into the baden-baden-desk orientation.
**Origin brief:** `BAKER_OS_V2_STEP2_ONWARD_JOURNEY_BLOCKS_2_4_1` (blocks 2-4).

> The parser accepts ONLY the grammar below, **verbatim**. The code and this SOP must
> stay in lock-step — if one changes, change both in the same PR. Anything the parser
> cannot resolve to exactly one command is **left un-acked and logged loudly** (never
> silently dropped, never guessed), so a malformed reply is safe but ignored until fixed.

## What you receive

When a ticket is ready for your desk, you get a bus message from `ticketing-desk` (the
boarding poster identity) on topic `boarding/<ticket_ref>`:

```
TO: baden-baden-desk
FROM: ticketing-desk
RE: WORK_PACKET airport-lounge:v1:<source_ticket_id>

WORK_PACKET v1
ticket_ref: airport-lounge:v1:<source_ticket_id>
clickup_task_id: <id>
clickup_list_id: 901524194809
matter_slug: <slug>
accept_token: claim:v1:<hash>
luggage:
<summary>

Reply grammar (reply on this thread):
  CLAIM <token>
  STATUS BLOCKED|WAITING|UPDATE_REQUIRED <token> [note]
  LANDED <token>
  <package after the LANDED line: state / evidence / asks — free text>
```

Copy the `accept_token` value exactly — every reply is authenticated by it.

## How you reply

**Reply on the same bus thread. Exactly ONE command per message.** A message containing
two commands (e.g. both `CLAIM` and `LANDED`) is rejected as ambiguous.

### 1. Claim the work — `CLAIM <token>`

```
CLAIM claim:v1:<hash>
```

- The command line must contain the command and the token **and nothing else**.
- Effect: journey advances `BOARDING_POSTED → CLAIMED`; the ClickUp task moves to
  **in progress**.
- Only valid from `BOARDING_POSTED`. A second `CLAIM` after you already claimed is a
  harmless no-op (acknowledged, no double-advance).

### 2. Mirror an in-flight status — `STATUS <STATE> <token> [note]`

```
STATUS BLOCKED claim:v1:<hash> awaiting Sosnin survey
STATUS WAITING claim:v1:<hash>
STATUS UPDATE_REQUIRED claim:v1:<hash> need Director sign-off on scope
```

- `<STATE>` is exactly one of **`BLOCKED`**, **`WAITING`**, **`UPDATE_REQUIRED`**
  (uppercase). No other word is accepted in that position.
- Optional free-text `[note]` after the token becomes a ClickUp comment.
- Effect: the ClickUp task mirrors to the matching status (`blocked` / `waiting` /
  `update required`) + your note as a comment. The journey stays at `CLAIMED` — status
  mirrors are ClickUp-surface only, you can send as many as you need.
- Only valid while `CLAIMED`.

### 3. Land the journey — `LANDED <token>` + package

```
LANDED claim:v1:<hash>
state: resolved — deposit released
evidence: SEPA confirmation 2026-07-04, ClickUp doc #123
asks: none
```

- The **first line** is `LANDED` + the token. Everything **after** that line is the
  returned **package** (free text — your state / evidence / asks), stored on the journey
  record.
- Effect: journey advances `CLAIMED → LANDED`. Baker then writes the receipt: closes the
  ClickUp task (**complete**) with a receipt comment, posts a `RECEIPT` proof back to you,
  and closes the source ticket. Journey is **Closed** only when all three land.
- Only valid from `CLAIMED`. A second `LANDED` after landing is a harmless no-op.

## Exception handling (automatic — nothing for you to do)

- If you do not `CLAIM` within the claim TTL (default 48h), Baker re-nudges you once on the
  same thread. If still unclaimed after a second TTL, the ticket escalates to the
  Controller (ClickUp status **update required**) and stops waiting on you.
- Send the reply as soon as you act — the sooner you `CLAIM`, the sooner the ClickUp
  timetable reflects reality.

## Guardrails (why a reply might appear "ignored")

- Wrong token → not authenticated → left un-acked. Re-copy the `accept_token` exactly.
- Two commands in one message → ambiguous → left un-acked. Send one command per message.
- Out-of-order command (e.g. `LANDED` before `CLAIM`) → left un-acked. Follow
  `CLAIM → STATUS* → LANDED`.
- `STATUS` with a state word other than `BLOCKED` / `WAITING` / `UPDATE_REQUIRED` → rejected.
