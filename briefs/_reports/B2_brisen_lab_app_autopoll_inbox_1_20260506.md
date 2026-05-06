---
status: PR_OPEN
brief: briefs/BRIEF_BRISEN_LAB_APP_AUTOPOLL_INBOX_1.md (baker-master bd2b334c)
target_repo_primary: vallen300-bit/baker-master
target_branch_primary: b2/brisen-lab-app-autopoll-inbox-1
pr_primary: https://github.com/vallen300-bit/baker-master/pull/166
target_repo_companion: vallen300-bit/brisen-lab
target_branch_companion: b2/brisen-lab-app-autopoll-inbox-1-daemon-block
pr_companion: https://github.com/vallen300-bit/brisen-lab/pull/7
tier: A
trigger_class: TIER_A_AUTHZ + RECEIVE_SIDE_HOOK + DIRECTOR_INBOX
shipped_by: B2
shipped_at: 2026-05-06
ratification_pending: AH1-T merge (gate 5; gates 1-4 GREEN)
ship_sequencing: brisen-lab #7 merges FIRST, then baker-master #166
---

# B2 ship report — BRISEN_LAB_APP_AUTOPOLL_INBOX_1

## Summary

Stage 2 of the Director-locked sequence (F2 ship → Stage 2 → 1-week burn-in → Stage 3 NOT authorized). Two-repo, two-flag kill-switch design.

- **Companion (brisen-lab #7)** — ships FIRST. Daemon-layer Director-recipient block, env-gated via `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED` (default=true). 8 new tests + 1 monkeypatch addition to `test_a5_director_only_tier_validates`.
- **Primary (baker-master #166)** — ships AFTER. Hook gains `_drain_director_inbox()` for AH1-App as Director's secretary; F2 client-side director-rejects removed (single control point at daemon). 10 new tests + 2 inversions in `test_bus_post.py`.

Both kill-switch flags default-OFF → both PR merges are no-op behavioral. Director flips `BRISEN_LAB_APP_AUTOPOLL_ENABLED=true` (AH1-App shell) + `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=false` (Render env on brisen-lab) independently to enable Stage 2.

## PRs

| Repo | PR | Branch | Head commit | Tag |
|------|----|----|--------|-----|
| brisen-lab (companion) | [#7](https://github.com/vallen300-bit/brisen-lab/pull/7) | `b2/brisen-lab-app-autopoll-inbox-1-daemon-block` | `3b54c90` | tier-a-authz |
| baker-master (primary) | [#166](https://github.com/vallen300-bit/baker-master/pull/166) | `b2/brisen-lab-app-autopoll-inbox-1` | `e8717fa5` | tier-a-authz |

## AC table

| AC | Test | Status |
|----|------|--------|
| A1 | brisen-lab `pytest tests/test_director_recipient_block.py -v` — 8/8 PASS (52s w/ Neon test DB) | ☑ |
| A2 | brisen-lab full pytest — 84 passed, 1 skipped, 0 failed (6m18s w/ Neon) | ☑ |
| A3 | baker-master `pytest tests/test_director_inbox_drain.py -v` — 10/10 PASS | ☑ |
| A4 | baker-master `tests/test_bus_post.py` — 15/15 PASS incl. test_01 + test_12 inversions | ☑ |
| A5 | shellcheck `scripts/bus_post.sh` clean (post-edit) | ☑ |
| A6 | py_compile `.claude/hooks/user-prompt-submit-confirm.py` clean | ☑ |
| A7 | py_compile `scripts/bus_post.py` clean | ☑ |
| A8 | py_compile brisen-lab `bus.py` clean | ☑ |
| A9 | Manual smoke (post-merge by AH1-T): both flags ON → `bus_post.sh director ...` returns 200 + AH1-App preamble surfaces it | ☐ post-merge |
| A10 | Reverse smoke: default flags → 403 director_recipient_blocked (pin-not-vacuous on daemon block) | ☐ post-merge |
| A11 | Pin-not-vacuous (autopoll): autopoll=false → no GET /msg/director from hook (verify via daemon access log) | ☐ post-merge |

## Files modified

### baker-master (primary, +686 / -27)

| File | Change | LOC |
|------|--------|-----|
| `.claude/hooks/user-prompt-submit-confirm.py` | EXTEND — `_drain_director_inbox()` + 6 helpers + main() integration | +193 / -2 |
| `scripts/bus_post.sh` | EDIT — remove F2 director hard-reject; add director to slug allowlist | +5 / -10 |
| `scripts/bus_post.py` | EDIT — add director to VALID_SLUGS; remove sys.exit director-rejection | +3 / -7 |
| `tests/test_bus_post.py` | EDIT — invert test_01 + test_12 (director-passes-through) | +25 / -8 |
| `tests/test_director_inbox_drain.py` | NEW — 10 hook unit tests, path-aware stub HTTP daemon, fake op CLI fixture | +346 |

### brisen-lab (companion, +151 / -1)

| File | Change | LOC |
|------|--------|-----|
| `bus.py` | EDIT — `import os`; env-gated director-recipient block in `_post_msg_inner` | +18 / -0 |
| `tests/test_director_recipient_block.py` | NEW — 8 tests (default-block, env=false unblocks, multi-recipient, regression, path-param, unset-default, "False" .lower() guard, numeric "0") | +127 |
| `tests/test_a3_a8_a9_bus.py` | EDIT — `test_a5_director_only_tier_validates` now `monkeypatch.setenv(BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED, "false")` | +6 / -1 |

## 5-gate review chain

| Gate | Reviewer | Verdict |
|------|----------|---------|
| 1 | feature-dev:code-reviewer (static) | REQUEST_CHANGES → 2 items (brisen-lab test_4 sender key Conf 90; baker-master ack-decoupling Conf 85). Both fixed (`3b54c90` + `e8717fa5`). |
| 2 | /security-review skill | No HIGH-CONFIDENCE vulnerabilities found. Subprocess `op read <const>` list-form safe; key never logged; env-vars trusted per scope; daemon-side enforcement correct migration. |
| 3 | feature-dev:code-architect | LGTM. Two-flag kill-switch granularity, marker file isolation, 8K body cap, single-control-point vs defense-in-depth, block-before-tier ordering, drain ordering, single-window-secretary semantics — all 7 design Q's resolved favorably. One non-blocking advisory on test_07 substring-match. |
| 4 | feature-dev:code-reviewer 2nd-pass | LGTM_2ND_PASS on both fix commits. Surface-before-ack ordering correct; `newest_ts` gating on `ack_ok` handles partial-batch ack-failure without gap or double-surface of already-acked rows. |
| 5 | AH1-T merge | **PENDING** — B2 not authorized to merge per standing scope. |

## Architect items — disposition

- **Q1-Q7 design questions:** all resolved as ratified in brief (Director Q1-Q5).
- **Advisory: test_07 substring assertion (Conf, advisory):** test asserts `long_body in ctx` (substring). Theoretically vacuous if preamble format wraps; in practice 500-char body well under 8K cap and preamble does no wrapping. Deferred — low risk.
- **Carry-forward (not in brief scope): `_drain_inbox()` (self-inbox) has same continue-on-ack-exception pattern.** Brief explicit "Do NOT touch existing `_drain_inbox()` for self-inbox". Suitable for a future hygiene brief if Director wants alignment between self-inbox and director-inbox drain semantics.

## In-flight observations

1. **A2 regression — `test_a5_director_only_tier_validates`.** First full pytest run hit a regression: my new daemon block fires before tier classification (per brief design), so the test expecting `400 tier_below_classification` now sees `403 director_recipient_blocked`. Fix: `monkeypatch.setenv(BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED, "false")` in test_a5 to reach the tier gate. Justification documented inline + in PR body. The test's purpose is tier validation, not director-block; unblocking is appropriate. Architect gate-3 explicitly endorsed the brief's block-before-tier ordering ("running director-block first means a blocked post fails fast with a clear `403 director_recipient_blocked` before any tier-classification logic runs ... the alternative would leak observability signal").

2. **Pytest invocation discipline.** Bare `pytest` failed (`zsh: command not found`); `python3 -m pytest` succeeded. Continued from F2 lesson — A1/A2/A3/A4 all run via `python3 -m pytest`.

3. **brisen-lab full pytest is slow.** 84 tests × Neon test DB = ~6m18s. Two runs were needed (initial regression, then post-fix). Future reviewer chain should anticipate: full brisen-lab A2 sweep ≈ 7 min wall.

4. **PATH isolation in `test_03_director_key_missing_fail_open_silent`.** Test uses `PATH=/nonexistent-bin` to exclude system `op` CLI. Hook's subprocess `["op", "read", ...]` then resolves to `FileNotFoundError`, caught by the broad `except Exception: pass` in `_fetch_director_key()`. Confirmed by gate-1 review as correctly isolated.

5. **fake_op_dir scoping (test_05).** Op CLI fallback test required a fake `op` shell binary that returns the director key for the canonical `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_director/credential` reference and exits non-zero for any other ref. Mirrors F2 fake op fixture pattern from `test_bus_post.py`.

## Lessons applied (per brief)

- **Two-flag kill-switch (Q2(b))** — daemon flag (`BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED`) + hook flag (`BRISEN_LAB_APP_AUTOPOLL_ENABLED`). Independently flippable.
- **Default-safe env parse** — missing env defaults to BLOCKED; falsy parse is `.lower()`-tolerant on `{false, 0, no, off}`.
- **Per-inbox marker isolation** — `baker-brisen-lab-lastseen-{role}.txt` (self) vs `baker-brisen-lab-lastseen-director-via-{role}.txt` (director). Distinct files.
- **/event/{id}/full reuse for full-body fetch** — no daemon endpoint expansion.
- **Single control point (script cleanup)** — F2 client-side hard-reject removed; daemon is load-bearing gate. Defense-in-depth split is now structurally impossible.
- **Pin-not-vacuous tests** — `test_director_recipient_block.py` test 7 (`.lower()` guard) + drain tests 1, 2, 10 (gate firing) explicitly verify gates work.
- **Two-repo split with cross-link** — both PR bodies cross-reference. STRICT ship sequencing: companion FIRST.

## Lessons learned this build

- **Daemon-block ordering causes test regression.** Placing director-block before tier classification (per brief design) creates a regression in pre-existing `test_a5_director_only_tier_validates`. Future briefs that touch the request-pipeline ordering should explicitly enumerate which existing tests need monkeypatch updates. Generalizable: brief's "Do NOT touch" list should be paired with "Tests that may need monkeypatch update due to design changes" list.

- **Surface-vs-ack decoupling matters in user-facing drains.** Original implementation followed the brief verbatim (ack first, `continue` on failure). Gate-1 reviewer flagged the silent-drop semantic. Lesson: NM3 idempotent ack means re-delivery is safe → surface should NOT be conditional on ack success. Generalizable: future drain-style code should default to surface-first, advance-cursor-only-on-ack-success.

- **Companion-repo full pytest is the long pole.** ~7 min wall. Two runs (initial + post-fix) blew ~14 min off the build clock. Worth front-loading A1 (single-file pytest, ~50s) before A2 (full suite, ~7 min) to catch regressions early.

## Mailbox hygiene

`briefs/_tasks/CODE_2_PENDING.md` will be flipped by AH1-T on merge per `_ops/processes/b-code-dispatch-coordination.md` §3.

## Next steps for AH1

1. **Review this report + PR bodies (#7, #166).**
2. **Merge brisen-lab #7 FIRST.** Daemon ships with default-blocked behavior — no behavior change vs F2.
3. **Merge baker-master #166 SECOND.** Hook + script changes ship with autopoll flag default-OFF — no behavior change.
4. **Manual smoke A9-A11** (AH1-T own shell):
   - A9: `BAKER_ROLE=AH1 BRISEN_LAB_TERMINAL_KEY_AH1=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential') ~/.baker-hooks/bus_post.sh director "Stage 2 smoke" "stage2/smoke"` → expect 200 (after Director flips daemon flag).
   - A10: with default `BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED=true`, same call → expect 403 `director_recipient_blocked`. Pin-not-vacuous.
   - A11: with `BRISEN_LAB_APP_AUTOPOLL_ENABLED=false`, AH1-App hook does NOT call /msg/director (verify via brisen-lab access log on Render).
5. **Director flips flags** when ready to enable Stage 2.
6. **1-week burn-in.** Stage 3 (worker self-wake) explicitly out of scope per Director ratification.

## Closes (on merge)

- ClickUp 86c9nugcw — F2-FU-1 daemon Director-block (companion PR)
- (Stage 2 App-side autopoll has no separate ClickUp — Director ratified inline 2026-05-06)
