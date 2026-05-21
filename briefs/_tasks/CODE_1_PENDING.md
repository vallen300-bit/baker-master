---
status: PENDING
brief: briefs/BRIEF_HAGENAUER_DESK_ON_BUS_1.md
brief_id: HAGENAUER_DESK_ON_BUS_1
target_repo: baker-master + baker-vault + filesystem
matter_slug: baker-internal
dispatched_at: 2026-05-21T14:15:00Z
dispatched_by: lead
target: b1
working_branch: b1/hagenauer-desk-on-bus-1
reply_to: lead
deadline: 2026-05-22T18:00:00Z
priority: tier-b
---

# CODE_1_PENDING — HAGENAUER_DESK_ON_BUS_1 — 2026-05-21

**Brief:** `briefs/BRIEF_HAGENAUER_DESK_ON_BUS_1.md`
**Working branches:**
- baker-master: `b1/hagenauer-desk-on-bus-1`
- baker-vault: fresh `/tmp/bv-hag-desk-bus-pilot/` clone per orientation branch-isolation rule
- user-global: in-place edits to `~/.claude/hooks/session-start-bus-drain.sh` + new `~/bm-hag-desk/CLAUDE.md` (no repo)

**Pre-requisites:**
- b1 working tree current (`cd ~/bm-b1 && git pull --ff-only`).
- Read `briefs/BRIEF_HAGENAUER_DESK_ON_BUS_1.md` in full before editing.
- Reference picker pattern: read `~/bm-ben/CLAUDE.md` for the structure to mirror in `~/bm-hag-desk/CLAUDE.md`.

**Acceptance criteria (testable):** see brief §"Acceptance criteria" — 6 ACs (AC1-AC4 = b1 ships; AC5-AC6 = AH1 fires post-merge after Render env update).

**Ship gate:**
- baker-master PR with literal local smoke output (placeholder-key 401 is expected — that's fine, confirms client-side whitelist).
- baker-vault PR with skill update.
- Capture in-place edits (drain hook + picker CLAUDE.md) as diff/file content in ship report.

**Reporting:**
- Bus-post `lead` on each PR open.
- Bus-post `lead` on ship-complete with both PR anchors + filesystem state.
- Ship report at `briefs/_reports/B1_HAGENAUER_DESK_ON_BUS_1_20260521.md`.

**Out of scope for b1:** 1Password key generation + Render env PUT + brisen-lab redeploy + live smoke fires (AC5/AC6) — AH1 Tier-B lane post-merge.
