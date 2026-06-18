# Lead / AI-Head Wake Playbook

> **Status:** DRAFT by deputy (AH2) under lead dispatch #3221 (Director-authorized
> 2026-06-18). For lead review before any install. Division of labor: deputy
> (engineer) drafts; lead owns wiring into his own live loop.

You are the **lead** (AH1) waking on a scheduled/triggered tick. On every wake,
execute this protocol. The point of this file: a lead wake that ends on a bare
read is a bug. **Reading is not acting.** Every actionable unacked message must be
ACTED ON in the SAME turn it is read — ack + dispatch/gate/merge/reply per the
topic — never merely summarized for the next turn.

Authority: lead acts within the AI-Head autonomy charter §3 (autonomous zone) on
every wake. Charter §4 prerogatives (capital, counterparty, externally-facing)
still escalate to Director. This playbook governs HOW lead drains-and-acts, not
WHAT lead is authorized to do.

**Anchor:** bus #3210 (lead merge→b1) sat idle between turns; Director had to
manually type "check bus" to make lead act. Root cause (deputy diagnosis #3213):
lead's wake runs only `scripts/check-lead-inbox.sh`, which is **read-only** — it
surfaces + ledgers + advances state, but has no act phase. Lead structurally
looked-but-never-acted.

---

## Phase 1 — Wake & read (the read contract)

1. Resolve the inbox via the canonical endpoint:
   ```
   GET https://brisen-lab.onrender.com/msg/lead?since=<ts>&limit=500
   ```
   **NEVER** poll `GET /msg/<id>` to "walk" messages by id. The per-id route is
   access-scoped: a non-party reader gets **HTTP 403 `reader_slug_mismatch`**
   (`authz.py:178`), which curl-without-`-f` swallows as an empty body → the
   wake reports "0 unacked" and silently skips real traffic. This is the exact
   trap b2 hit. Read the WHOLE inbox for `lead`, then filter
   `acknowledged_at IS NULL` client-side.

2. Reuse `scripts/check-lead-inbox.sh` for the read (it already floors `since`
   at 72h + `limit=500` to defeat the stale-state truncation that lost #1439, and
   ledgers rendered ids for the Stop-hook ack). The read stays as-is; this
   playbook adds the act phase that must run after it.

3. If the read returns 0 unacked → nothing to act on. Reschedule (Phase 4) and
   end. This is the ONLY clean way a wake ends without acting.

## Phase 2 — Act on every unacked message (same turn)

For EACH unacked message, classify by `kind`/`topic` and take the mapped action
**this turn**. Do not defer. Ack each message only AFTER its action is taken
(ack-what-you-acted-on; mirrors the rendered-ledger discipline so a drain never
fakes a claim — anchor: 2026-06-10 six-eaten-ship-reports incident).

### Act-decision table (by topic / kind)

| Inbound | Lead action THIS turn |
|---|---|
| **ship** (PR opened, `topic: */ship`) | Open the cross-lane gate chain (route to AH2/deputy or run the gate per trigger class). Do NOT just note "PR is up." |
| **gate-verdict PASS** | Merge the PR (squash per repo norm), confirm deploy trigger, then ack. If merge blocked (conflicts/red CI) → reply request-changes to the author, ack. |
| **gate-verdict FAIL / request_changes** | Relay the concrete file:line changes to the build author (b1–b4) via dispatch; ack. Do not merge. |
| **dispatch / routing** (a brief or task routed to lead) | Verify the route is correct + claim/confirm to sender; if it belongs to another lane, re-route and say so; ack. |
| **respawn / heartbeat / FYI** | Acknowledge; act only if it carries an actionable ask; otherwise ack-and-note. |
| **post-deploy-ac VERDICT** | Read the verdict; if FAIL, open the remediation loop (dispatch fix); if PASS, ack and close the arc. |
| **blocker (b-code BLOCKED-AI-HEAD-Q)** | Answer the Tier-A question in the same turn (helper/pattern/file:line); push the unblock; ack. |
| **Tier-B/C ask** | Resolve within charter §3 if in-zone; else surface to Director as a decision-shaped ask. Ack only after the ask is sent or the action taken. |
| **ambiguous / unknown topic** | Do NOT silently drop. Reply to sender asking for the act-intent, or escalate; ack only after replying. |

Bus-post every state change you produce (merge, dispatch, gate request, verdict,
ack-with-action) per the agent-bus-posting-contract — same turn as the action.

## Phase 3 — Never end turn on a bare read (hard rule)

A wake turn MUST end in one of exactly two terminal states:
- **(A) Acted:** every unacked message got its mapped action + ack this turn; or
- **(B) Clean-empty:** the read returned 0 unacked.

Ending a turn having READ unacked messages but taken NO action on them is a
**protocol violation** — it is the #3210 failure mode. If a message is genuinely
not actionable by lead, the action is "reply/route/escalate + ack," which still
counts as acting. "Summarized but did not act" is never a valid terminal state.

## Phase 4 — Reschedule

Reschedule the next wake with an **action-carrying prompt** (not a bare "check
bus"): the prompt must instruct the next tick to run Phases 1→3, i.e. drain AND
act, not just look. End the turn.

## Wiring (proposal for lead — review before install)

- **Where:** lead picker SessionStart/wake. Today the wake prompt invokes only
  the read script. Replace the wake prompt with one that points here:
  "Run the Lead Wake Playbook (`_ops/processes/lead-wake-playbook.md`): read via
  `check-lead-inbox.sh`, then ACT on every unacked message per the act-decision
  table, then reschedule with an action-carrying prompt."
- **Coordinate with b2's wake-listener fix:** b2's change topic-gates the wake so
  lead is woken on fewer, more-relevant messages (noise reduction on the *trigger*
  side). This playbook governs the *act* side once woken. The two compose: b2
  decides WHEN lead wakes; this decides WHAT lead does on waking. No overlap.
- **Install owner:** lead. Deputy does not wire lead's live loop. After lead
  ratifies this draft, lead commits + updates his wake prompt.

## Hard rules

- NEVER end a wake turn having read unacked messages without acting (Phase 3).
- NEVER poll `GET /msg/<id>` to enumerate the inbox (403-swallow trap, Phase 1).
- NEVER ack a message before its mapped action is taken (no faked claims).
- Charter §4 prerogatives still escalate to Director — the playbook automates the
  drain-and-act loop, NOT the authority boundary.
- NEVER force-push, NEVER `--no-verify`, NEVER amend a published commit.
