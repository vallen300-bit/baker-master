---
brief_id: BUS_READ_PATH_FIX
dispatch: "#9755 (lead, HIGH — unblocks a deaf matter desk; ao-desk clean-env test #9747)"
owner: b1
attempt: 1
checkpoint_reason: built + PR brisen-lab#119 at lead Claude-review
created: 2026-07-12
updated: 2026-07-12
status: at-review
---

# Checkpoint — bus read-path fix micro-arc

## Scope
brisen-lab bus.py READ path only. Two defects (#9755):
1. No single-message route — `GET /msg/9695` → RECIPIENT_OF_TERMINAL 403.
2. List returns body_preview only.
Do NOT touch ack path (b4's E1 lane). No schema change. Rails: build → LEAD Claude-review → lead merge (no codex, seats suspended #9711).

## What's done — BUILT + PR OPEN
- Repo/checkout: `~/bm-b1-brisen-lab`, branch `b1/bus-read-path-fix` (off origin/main).
- bus.py: (1) new `GET /msg/{terminal}/{msg_id}` (full body by id; recipient-or-'*'-or-Director; else 403); (2) `?full=true` on `get_msg` list (adds `body`, cap FULL_MAX_LIMIT=50).
- Tests: `tests/test_bus_read_path_fix.py` — 10 cases, ALL PASS on live PG (local `brisen_lab_test`, `TEST_DATABASE_URL=postgresql://localhost:5432/brisen_lab_test?host=/tmp`). Regression: test_inbox_read_authz + test_bus_ack_list_projection + test_bus_recipient_validation = 26 green. py_compile clean.
- **PR brisen-lab#119.** Ship posted to lead #9780. Coordinated: cowork-ah1 #9782 (app.py/static, no overlap), b4 #9783 (ack_msg, separate region).
- Reviewer flag in PR: by-id route allows '*' broadcast fetch by any terminal (matches drain delivery set); drop the '*' clause if strict recipient-only wanted.

## NEXT CONCRETE STEP
Await LEAD Claude-review on #119. On PASS → lead merges → ping cowork-ah1 + b4 to sequence their rebases → then start QUEUED item #14 (below). On CHANGES → fold in `~/bm-b1-brisen-lab` on same branch, re-run pytest (local PG), re-push, re-post.

## QUEUED behind (do NOT start until #119 merges) — RESEARCHER ITEM #14 (lead #9764, Director GO)
- Native YouTube **SEARCH** channel (discovery, not just transcript-analyze). Extends the researcher capability-extension brief. **DESIGN-FIRST.**
- Design decision to settle in the doc + recommend one, surface the conflict:
  - (a) YouTube Data API v3 — needs a Google API key; if chosen, **lead procures the key** (flag it; do NOT create accounts).
  - (b) keyless yt-dlp `ytsearch` / equivalent — no key, but scraping-fragility tradeoff.
- Shape: cage-safe vetted wrapper mirroring `auth_source_fetch.sh` (script + tests in **baker-master** `scripts/`, method.md §2 channel-landscape wiring as a small **baker-vault** PR). Read-only, no cage change.
- Rails: design → lead review → build → lead Claude-review → lead merge.

## Claim discipline
Successor claims via the `attempt:` bump on THIS checkpoint (not bus ack). If already bumped, stand down. At attempt>=3, escalate to lead with checkpoint path + last state.
