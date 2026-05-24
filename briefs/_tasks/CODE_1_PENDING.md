---
status: COMPLETE
completed_on: 2026-05-24
merge_anchors:
  - baker-vault PR #110 → 9c12ec3
  - baker-master PR #254 → 53aa5f7
  - brisen-lab PR #32 → 0db99b6
request_changes_resolved: bus #867 (F1 + F2 applied via commit 1dd2a25; F3 ratified vault-fallback no-change)
merge_complete_msg: bus #880
brief: HAG_WORKERS_PHASE_1
dispatched_by: lead (AH1)
dispatched_on: 2026-05-24
target: b1
canonical_brief: ~/baker-vault/_ops/briefs/BRIEF_HAG_WORKERS_PHASE_1.md
install_sop: ~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md
design_specs:
  - ~/baker-vault/_ops/agents/_universal/cm/cm-1-design.md (canonical)
  - ~/baker-vault/_ops/agents/_universal/cm/cm-2-design.md
  - ~/baker-vault/_ops/agents/_universal/cm/cm-3-design.md
  - ~/baker-vault/_ops/agents/_universal/cm/cm-4-design.md
  - ~/baker-vault/_ops/agents/hagenauer-desk/workers/filer/hag-filer-design.md
ratification_anchor: baker-vault 763e8fc (5-design batch ratified 2026-05-24)
sop_compliance: 5-SOP bundle b5924b7 + 7315874 cascade (create-new-agent-sop-base/fleet/matter-desk + worker-execution-of-matter-filing-sop + important-document-sop)
priority: HIGH (Hag-desk overloaded; filing crunch 2026-05-26/27)
estimated_complexity: Medium (~12-16h Phase 1 MVP, cross-repo)
supersedes: BAKER_SUBSTACK_SEARCH_1 (status COMPLETE, prior dispatch from 2026-05-23, closed via PR #251 merged ff0a589)
---

# CODE_1_PENDING — HAG_WORKERS_PHASE_1 Layer 2 install dispatch

## Mandate

Execute Fix/Features 1-6 from `~/baker-vault/_ops/briefs/BRIEF_HAG_WORKERS_PHASE_1.md` to install 5 new agents (CM-1..4 + hag-filer) onto Brisen Lab per the install-SOP.

## Read first (in order)

1. `~/baker-vault/_ops/briefs/BRIEF_HAG_WORKERS_PHASE_1.md` — full brief (6 Fix/Features, all step-by-step, Files Modified + Do NOT Touch).
2. `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` — canonical install-SOP. **Cross-check brief against 12-row wiring map; flag any row not covered.**
3. The 5 design specs (frontmatter list above). Each spec resolves [FILL] from brief content; use as ground truth for slug names, paths, 1P key paths, sender slugs, runtime locations.
4. `~/baker-vault/_ops/processes/create-new-agent-sop-base.md` (+ fleet + matter-desk extensions). For context only — design phase already complete.

## Repos touched (sequential PR order per install-SOP §"Three-repo PR sequencing")

1. **baker-vault PR FIRST** — if any `_ops/agents/_universal/cm/*` or `hagenauer-desk/workers/filer/*` files need creation beyond designs already on main. (Most likely NONE since designs landed 2026-05-24; verify before opening PR.)
2. **baker-master PR SECOND** — Fix/Features 2 (bus_post.sh whitelist) + 3 (5 worktree clones) + 4 (role-context files) + 5 (SessionStart hook cwd cases) + 6 (memory scaffolds touched on baker-vault, but committed via baker-master if any baker-master-side files involved).
3. **brisen-lab PR THIRD** — Fix/Feature 1 (5 slug registration: app.py:40 + bus.py:896 + bus.py:1005 + db.py:226 + lifecycle.py:493 + Render env + 1P items).

## Brief coverage vs install-SOP 12-row map (lead pre-flight gap-scan)

Brief covers SOP rows 1, 4, 5, 6, 7, 8, 9, 11. Two gaps require supplementary ACs:

### Gap A — Row 12: Snapshot pusher (LOAD-BEARING — RESEARCHER scar 2026-05-22)

**Supplementary AC A1.** Edit `~/baker-vault/_ops/scripts/forge_snapshot_push.sh` (or wherever canonical lives per AH1 repo — likely `~/bm-aihead1/scripts/`) TERMINALS array at line ~61. Add 5 entries:

```
CM-1:$HOME/bm-CM-1
CM-2:$HOME/bm-CM-2
CM-3:$HOME/bm-CM-3
CM-4:$HOME/bm-CM-4
hag-filer:$HOME/bm-hag-filer
```

**Important per install-SOP §"Second-pass lived foot-gun" foot-note (researcher scar):** for any of the 5 pickers without their own `.git` clone, use `$HOME/baker-vault` as the repo-path fallback. Pusher errors with "repo missing" if path has no .git. CMs/hag-filer DO clone baker-master per brief Step 3.1, so they have .git — but verify.

**Supplementary AC A2.** Add regression test cases in `tests/test_forge_snapshot_push.sh` mirroring Case L (PR #238 pattern) — one case per new slug.

**Supplementary AC A3.** Post-merge AH1 Tier-B execution: redeploy snapshot pusher on EACH host (MacBook + Mac Mini) via:
```
FORGE_KEY=$(plutil -extract EnvironmentVariables.FORGE_KEY raw ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist) bash scripts/install_forge_push.sh
```

### Gap B — Row 2: Shell aliases (LOW priority)

**Supplementary AC B1.** Add 5 shell functions to `~/.zshrc` (CM-1, CM-2, CM-3, CM-4, hag-filer) following the existing `aodesk` / `moviedesk` / `hagenauerdesk` pattern. Functions cd to `~/bm-<slug>`, set `BAKER_ROLE=<slug>` + `FORGE_TERMINAL=<slug>`, launch claude.

(LOW priority because workers run in Cowork App, not Terminal.app. Skip if time-pressured; defer to fast-follow.)

## Critical constraints (per brief + designs + install-SOP)

1. **Slug case-sensitivity:** `CM-1` uppercase everywhere EXCEPT role-context filename (lowercase `cm-1.md` per SessionStart hook lowercasing logic at line 55). hag-filer always lowercase.
2. **Do NOT touch existing slug entries** (lead, cowork-ah1, deputy, b1-b4, hag-desk, researcher, architect, aid, cortex, daemon). Extend lists only.
3. **Existing slug conflict:** `hag-desk` already in bus_post.sh whitelist (line 46 per brief). Brief Step 2.1 example shows `hag-desk` twice — remove the duplicate when editing.
4. **Render env race:** pause active dispatches during `BRISEN_LAB_TERMINAL_KEYS` env update; redeploy AFTER env fully written.
5. **Disk space:** 5 clones × ~500MB = ~2.5GB. Verify `df -h ~` before Step 3.1.
6. **hag-filer cross-blocker CLOSED** — filing-protocol.md v2 ratified D-014 (2026-05-24, commit 9902430). hag-filer can ship immediately.

## Gate chain on PR open

MEDIUM trigger class (cross-repo + new public surface + auth changes via new bus keys). Expected gate chain per AH2 deputy lane:
- Gate-1 architecture-review
- Gate-2 `/security-review`
- Gate-3 picker-architect (multi-picker install — 5 new pickers)
- Gate-4 code-reviewer 2nd-pass
- Gate-5 AH1 merge

## Ship gate

Literal pytest output for:
- `pytest tests/test_a3_a8_a9_bus.py -v` (brisen-lab)
- `bash tests/test_forge_snapshot_push.sh` (baker-master)

in PR description. NO "pass by inspection" — REQUEST_CHANGES on inspection-only claims.

## Ship report routes to

`lead` via bus (topic: `ship/hag-workers-phase-1`). Include both PR numbers + verification command outputs.

## Reply expected

`"B1 oriented. Read: CODE_1_PENDING.md, MEMORY.md."` on session start.
