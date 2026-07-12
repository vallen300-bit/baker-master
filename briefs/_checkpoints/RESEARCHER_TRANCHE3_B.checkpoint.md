---
brief_id: RESEARCHER_TRANCHE3_B
dispatch: deputy #9337 (Director order via lead #9334)
owner: b2
attempt: 1
updated: 2026-07-12
status: #11 MERGED · #12 BUILT + shipped to build-gate (launchd verify DELEGATED to deputy)

## Current state (2026-07-12 ~15:17Z)
- **#11 MERGED** (codex build-gate PASS #9409; lead merged baker-master #534 + baker-vault #174).
- **#12 BUILT, both PRs open, routed to codex build-gate #9435:**
  - baker-master **PR #536** (branch `b2/researcher-standing-monitors`): reader
    `check_source_monitors.sh` + tests (8/8).
  - baker-vault **PR #176** (worktree `~/bm-b2-vault-monitors`, branch
    `b2/researcher-standing-monitors-vault`): prefetch + 2 launchd plists + digest-dispatch
    trigger + cache scaffold/_status + cage entry + method row + cage tests (206/206).
  - End-to-end proven locally (prefetch --dry-run → reader 171 fresh items, 0 stale).
  - **DELEGATED-PENDING** (lead #9418): real-launchd-context force-fire/log/commit
    verification owned by deputy (Mac Mini SSH); merge waits on that + codex build-gate.
- **Next:** watch bus for codex #12 build-gate reply (→ address any CHANGES on the existing
  #536/#176 branches, no amend). Then deputy's Mac-Mini verification → lead merges both.
  Keep worktree `~/bm-b2-vault-monitors` until #176 merges.

---
### (historical) prior status: #11 SHIPPED to build-gate · #12 SPEC-LOCKED, not yet built
---

# Checkpoint — Researcher Tranche-3 (b2 items #11 + #12)

## What's done
- **#11 authenticated-source access — BUILT + tested + 2 PRs open, routed to codex
  build-gate (#9405).**
  - baker-master **PR #534** (branch `b2/researcher-auth-source-access`, commit `e0bfe311`):
    `scripts/auth_source_fetch.sh` (CDP-driven cookie-auth read of port-9222 profile;
    urllib parser, https-only, userinfo-reject, baked host allow-list exact/dotted-suffix,
    FINAL post-redirect host re-verify before extraction) + `scripts/tests/
    test_auth_source_fetch.sh` (13/13, incl live arxiv read).
  - baker-vault **PR #174** (worktree `~/bm-b2-vault-authsrc`, branch
    `b2/researcher-auth-source-cage`, commit `26cda46`): `researcher_bash_cage.sh`
    IS_VETTED entry + `method.md` channel row + cage tests (202/202).
  - Design doc: `briefs/_design/DESIGN_RESEARCHER_TRANCHE3_11_AUTH_SOURCE_ACCESS.md`
    (codex #9391 CHANGES incorporated).
- **#12 design DONE + codex design-verified (#9394 CHANGES incorporated).** Spec locked in
  `briefs/_design/DESIGN_RESEARCHER_TRANCHE3_12_STANDING_MONITORS.md`.

## What's left — #12 standing source monitors (build to the locked spec)
Codex #9394 locked decisions (in the design doc frontmatter):
1. `~/bm-b2/scripts/check_source_monitors.sh` — vetted READ-ONLY cache reader: reads
   `_ops/research-monitors-cache/`, filters to last 7 days, dedups vs last 4 weekly
   digests, FAIL-LOUD on missing/stale cache (no env override, no arg-driven config path).
2. Source registry — baked constant OR pinned non-researcher-writable config (arXiv
   cs.AI/cs.SE/cs.CL/cs.CR + primary-source vendor changelogs ONLY; consume — do not
   supersede — aidennis-edge-scout / anthropic-feature-scout).
3. **launchd + cron split (codex Q2, NO brisen-lab APScheduler):** Mac Mini launchd
   prefetches the cache; a scheduled task/cron (edge-scout family) fires the weekly digest
   → `wiki/research/YYYY-MM-DD-research-monitors-weekly.md`.
4. `_ops/research-monitors-cache/` — Mac-Mini-populated, researcher read-only; add
   README/schema + `_status.json` staleness contract.
5. baker-vault cage: additive IS_VETTED entry for `check_source_monitors.sh` + method row.
6. Tests: fresh-cache surfaced; stale `_status.json` flagged-not-dropped; dedup vs prior
   digests; empty/missing cache clean.
7. **Codex F3 HARD AC:** real-launchd-context verification (force-fire/log/commit), mirror
   `B1_AID_EDGE_SCOUT_VAULT_CACHE_1` — **needs Mac Mini launchd context; b2 delivers the
   script + plist, lead/Mac-Mini installs + verifies.** Flag this to lead at #12 build time.

## Key paths / commits
- Designs: `briefs/_design/DESIGN_RESEARCHER_TRANCHE3_1{1,2}_*.md`
- #11 baker-master branch `b2/researcher-auth-source-access` @ `e0bfe311` (PR #534)
- #11 vault branch `b2/researcher-auth-source-cage` @ `26cda46` (PR #174), worktree
  `~/bm-b2-vault-authsrc`
- Cage canonical: `~/baker-vault/_ops/hooks/researcher_bash_cage.sh` (symlinked into
  `~/bm-researcher/.claude/hooks/`; bm-researcher is NOT a git repo)
- Vetted scripts live in baker-master `scripts/`; researcher invokes them at
  `~/bm-b1/scripts/` (the cage allow-lists bm-b1 paths)
- Prior art to mirror for #12: `aidennis-edge-scout` (cron+cache+_status.json),
  `open_report.sh` (race-free reader), `read_message.sh` (vetted-script idiom)

## Next concrete step
1. If codex build-gate on #11 (watch bus for reply to #9405) returns CHANGES → address on
   the existing #11 branches (new commit, no amend) before touching #12.
2. Build #12 `check_source_monitors.sh` + registry + cache README/`_status.json` schema +
   launchd plist + tests on a NEW branch `b2/researcher-standing-monitors` (baker-master)
   + a vault cage/method branch. Route #12 design is already codex-cleared → build →
   codex build-gate → lead merge. Hand the launchd-install + real-context verification
   (codex F3) to lead/Mac-Mini explicitly.
