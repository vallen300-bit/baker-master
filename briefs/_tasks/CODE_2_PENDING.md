# CODE_2_PENDING — BRISEN_LAB_APP_AUTOPOLL_INBOX_1

**Dispatched:** 2026-05-06
**Tier:** A (daemon authz surface change + receive-side hook extension touching Director's inbox)
**Repo (primary):** `vallen300-bit/baker-master`
**Branch (primary):** `b2/brisen-lab-app-autopoll-inbox-1`
**Repo (companion, REQUIRED — daemon ships first):** `vallen300-bit/brisen-lab`
**Branch (companion):** `b2/brisen-lab-app-autopoll-inbox-1-daemon-block`
**Brief:** `briefs/BRIEF_BRISEN_LAB_APP_AUTOPOLL_INBOX_1.md` (read it first — full spec, copy-paste-ready code blocks)

## Summary

Stage 2 of the Director-locked sequence (F2 ship → Stage 2 → 1-week burn-in). Bundles F2-FU-1 (move Director-recipient block from F2 script-layer to brisen-lab daemon, env-gated) + App-side autopoll (AH1-App's UserPromptSubmit hook drains `/msg/director` on top of `/msg/lead`). Director sees Director-facing bus traffic in preamble alongside AH1's own inbox.

Director Q1-Q5 ratified 2026-05-06: per-prompt drain (Q1a), two flags (Q2b), reuse bm-aihead1 picker drain-both (Q3b), full body up to 8K (Q4b), ratify_required pinned at top (Q5a).

## What to build

**brisen-lab (companion PR — ships FIRST):**
- `bus.py` EXTEND — env-gated (`BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED`, default=true) reject in `_post_msg_inner` when `to` includes "director". Defense-in-depth at daemon layer.
- `tests/test_director_recipient_block.py` NEW — 8 tests (default behavior, multi-recipient, regression, typo-tolerance, etc.)

**baker-master (primary PR — ships AFTER companion):**
- `.claude/hooks/user-prompt-submit-confirm.py` EXTEND — new helpers `_app_autopoll_enabled`, `_is_director_facing_role`, `_fetch_director_key`, `_drain_director_inbox`. Integrate into `main()` after existing self-inbox drain. Per-inbox last-seen markers (separate files for /msg/lead vs /msg/director).
- `scripts/bus_post.sh` + `scripts/bus_post.py` EDIT — REMOVE F2 director-recipient hard-reject; ADD "director" to slug allowlist. Single control point at daemon (defense-in-depth split is now structurally impossible).
- `tests/test_director_inbox_drain.py` NEW — 10 hook unit tests (autopoll gate, role gate, key fetch, ratify_required pinning, full-body via /event/{id}/full, ack semantics, marker isolation, fail-open).
- `tests/test_bus_post.py` EDIT — invert F2 tests 1 + 12 (director-passes-through; daemon enforces).

## Two flags (kill-switch design)

- `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED` — Render env on brisen-lab. Default=true (blocked). Flip to false to allow Director-recipient bus traffic.
- `BRISEN_LAB_APP_AUTOPOLL_ENABLED` — AH1-App's shell env. Default=false. Flip to true to enable hook drain of /msg/director.

Both default-OFF. Brief merge = NO behavior change. Director flips each independently to enable Stage 2.

## CRITICAL: 5-gate review chain MANDATORY (Tier A)

Run all reviewers in **parallel** in a single message:

1. **AH2 static review** — `feature-dev:code-reviewer` agent — full diff (both repos)
2. **AH2 `/security-review`** — focus areas:
   - Director's terminal-key handling in hook (env vs op CLI fetch path; never logged)
   - daemon env-flag parsing (defaults safe; typos/title-case don't unblock)
   - hook fail-open contract preserved (no new exit-non-zero paths)
   - drain ordering (ack-then-fetch acceptable for read-only inbox)
3. **picker-architect review** — design fit:
   - kill-switch flag granularity (Q2b two-flag design)
   - per-role marker file naming (collision-safe across roles + flips)
   - body-cap policy (8K matches daemon ceiling)
   - F2 script cleanup tradeoff (single control point vs defense-in-depth — daemon is load-bearing)
4. **feature-dev:code-reviewer 2nd-pass** — after any review-driven changes
5. **AH1-T merges** — squash + delete branches + PL ship-report

Tag PRs with `tier-a-authz`. Cross-link companion PRs in both bodies.

## Two-repo split + ship sequencing

**Companion (brisen-lab) merges FIRST.** Daemon ships with default-blocked behavior — no behavior change vs F2. THEN baker-master primary merges (hook + script changes ship with autopoll flag default-OFF — no behavior change). Two no-op merges. Director then flips env flags to enable Stage 2 traffic.

If brisen-lab review hits issues: STOP. Hook depends on daemon being ready to handle director-recipient. Don't merge baker-master without brisen-lab landing first.

## Acceptance criteria — 11 total

- A1: brisen-lab `pytest tests/test_director_recipient_block.py -v` — 8/8 PASS
- A2: brisen-lab full `pytest` GREEN (no regression in 22 factory + 9 inbox + 8 new)
- A3: baker-master `pytest tests/test_director_inbox_drain.py -v` — 10/10 PASS
- A4: baker-master `tests/test_bus_post.py` — F2 inversion tests PASS (director passes through)
- A5: shellcheck `scripts/bus_post.sh` clean (post-edit)
- A6: py_compile `.claude/hooks/user-prompt-submit-confirm.py` clean
- A7: py_compile `scripts/bus_post.py` clean
- A8: py_compile `bus.py` (brisen-lab) clean
- A9: smoke (post-merge by AH1-T): both env flags ON → `BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh director "Stage 2 smoke" "stage2/smoke"` returns 200; AH1-App next prompt surfaces the message
- A10: reverse smoke (post-merge): default flags → same call returns 403 director_recipient_blocked. Pin-not-vacuous.
- A11: pin-not-vacuous (autopoll): autopoll=false → hook does NOT call /msg/director (verify via daemon access log)

## Ship-report

After both PRs merge, write `briefs/_reports/B2_brisen_lab_app_autopoll_inbox_1_20260506.md`: PR numbers (both repos), merge commits, AC table all ☑, files modified, any V0.x amendments, in-flight observations on hook/daemon interaction edge cases.

## Files modified — see brief §"Files modified"

## Do NOT touch

- `authz.py` — daemon authz factory unchanged. Director-block is a recipient-list filter, not an authz policy.
- `auth_lab.py` — no key-store changes.
- Existing `_drain_inbox()` for self-inbox — Director-inbox drain is parallel new function; do NOT merge into one.
- `BRISEN_LAB_V2_ENABLED` — orthogonal master switch; do NOT couple Stage 2 flags.
- AH2 / B-code orientation files — vault-side per CHANDA Inv 9. AH1-T handles separately if needed.
- Director's outbound flow — Stage 2 only automates AH1 → Director; Director's outbound stays prompt-typed (no Stage 3).

## Lessons applied (in brief)

- Two-flag kill-switch — daemon and hook concerns separated; either flips independently
- Default-safe env parse — missing env defaults to BLOCKED; typo-tolerant via .lower() check
- Per-inbox marker isolation — /msg/lead and /msg/director have distinct last-seen files
- /event/{id}/full reuse for Q4(b) full-body fetch — no daemon endpoint expansion
- Single control point (script cleanup) — F2 script-layer hard-reject removed; daemon is load-bearing gate
- Pin-not-vacuous tests A10/A11 — explicit verification flags actually gate behavior
- Two-repo split with cross-link + STRICT ship sequencing — companion FIRST
