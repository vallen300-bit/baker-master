---
brief_id: RESEARCHER_TRANCHE2_BUILD
report_type: arc-completion (light-pin)
author: b1
date: 2026-07-12
status: ARC CLOSED (lead #9741)
---

# B1 ship report — RESEARCHER_TRANCHE2_BUILD arc closed

Dispatch #9299 (deputy, Director order #9258 via lead #9297). b1 built the tranche-2
researcher capability-extension items. Codex design/build gates were in force at the
start; **codex seats suspended mid-arc (Director order #9711)** → gates rerouted to
LEAD Claude-review for the back half.

## Items shipped (all MERGED to baker-vault)

| Item | Topic | PR | Gates |
|---|---|---|---|
| 1 (#5) | Continuation queue + machine-readable deferrals + `validate_continuation.sh` | vault#175 | codex design #9312 (folded) + codex build-PASS #9433 |
| 2 (#6) | Per-type output schemas + `validate_channel_output.py` (+ self-test) | vault#179 | codex design #9456 (folded) + LEAD Claude-review #9717 (F1 fold #9631) |
| 7 | Operational recency override — method §4.3 `RECENCY-UNMET` gate + `validate_recency.sh` | vault#181 | LEAD design-PASS #9731 + LEAD line-review merge #9741 |

**Item 8 (research memory / index)** was **descoped to b2** (lead #9723). b1 handed b2
the store-landscape scouting it had already done (#9726).

## What each item added (all read-only / label-only / proposal-only — cages untouched)

- **#5** — deferrals declared machine-readably at Step 8.6; artifact `wiki/research/_continuation/<parent>-cont.md`; fail-closed `CONTINUATION-MISSING` gate.
- **#6** — every fan-out channel returns a typed JSON contract (base + 8 per-type field sets); deterministic pre-synthesis conformance check drops non-conforming channels to a §7 failure; required citation-slot keys `{claim,url,pub_date,byline,accessed,tier,confidence}` (F1 fold), `quote` optional; 13-case self-test.
- **#7** — `recency_sensitive`/`recency_window_days` declared at Step-0 intake (§4.0); at ship, a `<7-day` topic must show a native-recency channel (Grok/X) `complete` in the §4.1 ledger OR a closed-class `recency_waiver`, else `RECENCY-UNMET`; attempted-but-failed channel needs a waiver; researcher self-waiver allowed. Structured-declaration only (no regex-on-prose).

## Design discipline honoured across the arc

- Codex #9312 anti-prose ruling carried into every gate — validators read structured declarations, never sniff report prose.
- Fail-closed on the honest path; no cage / skill / MCP surface touched; no self-merge (Director rule #9255).
- Each validator exercised (5 / 9→13 / 12 paths) with literal runs; `py_compile` / `bash -n` clean.

## Housekeeping

- Deleted stale local branch `b1/researcher-tranche2-item1` (remote ref gone post-#175 merge; never rebased/forced — flagged to lead).
- Removed the item-6 and item-7 baker-vault worktrees.
- **Flag for lead:** two older b1 baker-vault worktrees remain from prior arcs —
  `~/bm-b1-vault-cage-close` (`b1/researcher-git-wrapper-cage-close`) and
  `~/bm-b1-vault-researcher-cage` (`b1/researcher-harness-retrofit`). Left in place
  (may hold state); lead to decide cleanup.

Researcher upgrade now 11/13 (lead #9741). b1 idle — awaiting fresh dispatch.
