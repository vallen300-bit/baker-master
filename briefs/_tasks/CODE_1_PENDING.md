---
status: PENDING
brief_id: BACKFILL_STALL_RESUME_1
to: b1
from: lead
dispatched_by: lead
dispatched: 2026-06-15
task_class: ops/data-recovery
harness_v2: "N/A — operational backfill resume, no code change unless a wrapper bug surfaces"
---

# CODE_1_PENDING — BACKFILL_STALL_RESUME_1

**RACI:** accountable=lead, responsible=b1 (you own these partitions), consulted=aid (Neon limits).

## Context
The cursor-stall sentinel you shipped this arc (PRs #363/#364) fired its first 3 *real* alerts to lead — it works. Three backfill partitions have not advanced in ~94–116h:

| job_id | partition | last cursor | stalled | last progress |
|---|---|---|---|---|
| `graph_sentitems_backfill` | `graph:SentItems` | 100 | 116.2h | 2026-06-10 09:35Z |
| `bluewin_inbox_backfill` | `bluewin:INBOX` | 32834 | 94.5h | 2026-06-11 07:20Z |
| `bluewin_sentitems_backfill` | `bluewin:Sent Items` | 5743 | 94.3h | 2026-06-11 07:27Z |

PINNED claims graph "resumed ~14:10Z" but that was the **Inbox** partition (different job); these three are still flagged. **Do not trust state files — verify live.**

## Live state (lead-verified, do not re-trust — re-check)
- graph **Inbox** backfill is RUNNING NOW: pid 38813 (`scripts/backfill_graph.py`) under retry wrapper pid 38653 (`run_backfill_graph_with_retry.sh`), started 04:39 local.
- The SentItems partition is the stalled one, not Inbox.
- Bluewin residual was ~960 msgs short at last arc close (INBOX 97.4% / Sent 98.4%).

## Cursor source of truth
`email_backfill_progress` table — `done_count` (cursor) vs `total_estimate` (total), keyed by `source` column. RUNNING ⇔ `done_count < total_estimate`; DONE ⇔ `done_count >= total_estimate`. This is the same source the sentinel reads (`config/long_running_jobs.yml`).

## Resume mechanism
- Graph: `scripts/run_backfill_graph_with_retry.sh` (wraps `backfill_graph.py`, has folder arg / resumes from cursor).
- Bluewin: `scripts/run_backfill_bluewin_with_retry.sh` (wraps `backfill_bluewin.py`).
- Confirm the exact folder/partition arg each wrapper takes before launching — read the script, don't guess.

## HARD constraint — SERIALIZE (Lesson #from autonomous-orchestration arc, do NOT violate)
Never run two historical backfills concurrently — Neon throws "Too many connections attempts" and froze prod ingestion 18.7h once. Graph Inbox is live NOW. **Wait for pid 38813 to finish before starting any other partition. Run partitions strictly one at a time.**

## Acceptance criteria
1. **Verify live** — query `email_backfill_progress` for all 4 keys (`graph:Inbox`, `graph:SentItems`, `bluewin:INBOX`, `bluewin:Sent Items`): report actual `done_count` / `total_estimate` + whether advancing. Confirm pid 38813 alive or finished. Bound every query with a LIMIT.
2. **Resume serialized** — after graph Inbox completes: resume `graph:SentItems`, then `bluewin:INBOX`, then `bluewin:Sent Items` — one at a time, each to completion before the next.
3. **Prove advancement** — for each resumed partition show the cursor (`done_count`) actually moving, not just "process started".
4. **Sentinel clears** — confirm `job_heartbeats` / sentinel sees progress and the stall alerts stop re-firing.
5. **If a partition is actually complete** (`done_count >= total_estimate`, sentinel mis-flagging) — say so with the row as evidence; that's a sentinel-threshold finding to surface, not a resume.

## Do NOT touch
- Don't start a second concurrent backfill (serialize — see HARD constraint).
- Don't edit `config/long_running_jobs.yml` or the sentinel code unless a real bug surfaces (then surface as a follow-up, separate PR).

## Report
Bus-post to lead at each milestone (per agent-bus-posting-contract): live-state verdict, each partition resumed + completed, final all-clear. Surface any wrapper bug or new stall as a follow-up to lead.
