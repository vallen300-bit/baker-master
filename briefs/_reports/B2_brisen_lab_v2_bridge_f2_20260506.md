---
status: SHIPPED
brief: briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_F2.md (baker-master 41dc9ef8 V0.2)
target_repo: vallen300-bit/baker-master
target_branch: b2/brisen-lab-v2-bridge-f2
pr: https://github.com/vallen300-bit/baker-master/pull/165
merge_commit: 2e8d3b07b9dbd59d471f6d0db2622b17a1f7f860
merged_at: 2026-05-06T12:15:20Z
tier: B
shipped_by: B2
shipped_at: 2026-05-06
companion_pr: vallen300-bit/brisen-lab b2/brisen-lab-v2-bridge-f2-authz-bools (optional, separate-repo, A8/A9 — not in this checkout, status unverified)
---

# B2 ship report — BRISEN_LAB_V2_BRIDGE_F2

## Summary

Outbound auto-post helper for AI Heads. `~/.baker-hooks/bus_post.{sh,py}` symlinks live; AH1/AH2 can invoke `bus_post.sh <recipient> <body> [topic]` to post to the bus daemon directly instead of producing paste-blocks. 1Password key fetch on demand. Director-recipient blocked at script level (load-bearing safety until Stage 2 autopoll wires Cowork's App-side hook).

PR #165 merged `2e8d3b0` 2026-05-06T12:15:20Z. Baker-master ships standalone per brief two-repo split — brisen-lab companion PR (A8/A9 bool-predicates) is optional and not gated on this merge.

## PR

- **URL:** https://github.com/vallen300-bit/baker-master/pull/165
- **Branch:** `b2/brisen-lab-v2-bridge-f2` (commit `3b01d59` impl)
- **Merge commit:** `2e8d3b07b9dbd59d471f6d0db2622b17a1f7f860`
- **Tag:** `tier-b-tooling`

## AC table

| AC | Test | Status |
|----|------|--------|
| A1 | `shellcheck scripts/bus_post.sh` clean | ☑ |
| A2 | `python3 -c "import py_compile; py_compile.compile('scripts/bus_post.py', doraise=True)"` clean | ☑ |
| A3 | `python3 -m pytest tests/test_bus_post.py -v` → 15 passed in 6.11s | ☑ |
| A4 | `~/.baker-hooks/bus_post.{sh,py}` symlinks exist + executable, point at bm-b2 | ☑ |
| A5 | Manual smoke (post-merge by AH1-T) — out of B2 scope | n/a (AH1-T) |
| A6 | `bash scripts/bus_post.sh director "ac6-test"` → exit 1 with explicit stderr | ☑ |
| ~~A7~~ | ~~Orientation + SKILL update~~ — STRUCK V0.2 (vault-side, AH1-T handles) | n/a |
| A8 | brisen-lab CallerContext bool-predicates + 4 new tests (22→26) | ☐ companion PR |
| A9 | brisen-lab full pytest GREEN (no regression) | ☐ companion PR |

## A3 literal pytest output

```
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b2
collected 15 items

tests/test_bus_post.py::test_01_sh_director_blocked PASSED               [  6%]
tests/test_bus_post.py::test_02_sh_unknown_slug PASSED                   [ 13%]
tests/test_bus_post.py::test_03_sh_no_args PASSED                        [ 20%]
tests/test_bus_post.py::test_04_sh_baker_role_unset PASSED               [ 26%]
tests/test_bus_post.py::test_05_sh_baker_role_unrecognized PASSED        [ 33%]
tests/test_bus_post.py::test_06_sh_post_succeeds PASSED                  [ 40%]
tests/test_bus_post.py::test_07_sh_post_503 PASSED                       [ 46%]
tests/test_bus_post.py::test_08_sh_post_unreachable PASSED               [ 53%]
tests/test_bus_post.py::test_09_sh_payload_escapes_special_chars PASSED  [ 60%]
tests/test_bus_post.py::test_10_sh_payload_includes_topic PASSED         [ 66%]
tests/test_bus_post.py::test_11_py_multi_recipient PASSED                [ 73%]
tests/test_bus_post.py::test_12_py_director_blocked PASSED               [ 80%]
tests/test_bus_post.py::test_13_py_payload_includes_parent_id PASSED     [ 86%]
tests/test_bus_post.py::test_14_py_kind_broadcast_tier_a PASSED          [ 93%]
tests/test_bus_post.py::test_15_py_baker_role_missing PASSED             [100%]

============================== 15 passed in 6.11s ==============================
```

## A6 literal director-block output

```
$ BAKER_ROLE=AH1 bash scripts/bus_post.sh director "ac6-test"
ERROR: director-recipient blocked.
  Director-facing dispatches must stay paste-blocks until Stage 2 autopoll.
  See: BRIEF_BRISEN_LAB_V2_BRIDGE_F2.md — Director ratified 2026-05-06 sequencing.
exit=1
```

## Files modified

| File | Change | LOC |
|------|--------|-----|
| `scripts/bus_post.sh` | NEW — POSIX Bash helper, 12-slug recipient guard, 1P key fetch, director block | +122 |
| `scripts/bus_post.py` | NEW — Python companion (multi-recipient, parent_id chains, kind/tier) | +140 |
| `tests/test_bus_post.py` | NEW — 15 subprocess + stub-daemon tests | +299 |

## Symlinks (post-merge state)

```
/Users/dimitry/.baker-hooks/bus_post.py -> /Users/dimitry/bm-b2/scripts/bus_post.py
/Users/dimitry/.baker-hooks/bus_post.sh -> /Users/dimitry/bm-b2/scripts/bus_post.sh
```

## Two-repo split disposition

Brief explicitly authorized baker-master to ship standalone if brisen-lab companion review hits issues. Baker-master PR shipped without dependency on bool-predicate fold. brisen-lab companion PR (A8/A9, branch `b2/brisen-lab-v2-bridge-f2-authz-bools`) status not verified from this checkout — `~/brisen-lab` repo not present locally; defer to AH1-T or B2 follow-up dispatch if companion fold needed.

## In-flight observations

1. **Director-recipient block is double-pinned.** Both `test_01_sh_director_blocked` and `test_12_py_director_blocked` pin AC A6. If Stage 2 autopoll lands and Director-recipient becomes valid, both test names + the explicit stderr message become the search keys to remove (canonical AC A6 anchor: `BRIEF_BRISEN_LAB_V2_BRIDGE_F2.md` 2026-05-06 sequencing).

2. **A4 symlinks point at bm-b2.** Not bm-b1. AH1-T should be aware that any `~/.baker-hooks/bus_post.*` invocation reads bm-b2 source-of-truth — relevant if bm-b1 ever diverges. Both bm-b1 and bm-b2 share the merged commit (it's on origin/main), so functionally identical today.

3. **Pytest discoverability.** Bare `pytest` is not on PATH for B2's environment (`zsh: command not found: pytest`); `python3 -m pytest` works. Documented for future ship reports — A3 always uses `python3 -m pytest tests/test_<file>.py -v`.

4. **A8/A9 not verified from baker-master checkout.** brisen-lab companion repo isn't checked out at `~/brisen-lab`. If AH1-T wants A8/A9 confirmed, a separate B2 dispatch on that repo (or AH1-T direct verify) is needed.

## Lessons applied (per brief)

- **Function-signature verification** — `auth_lab._TERMINAL_KEYS` test fixture used to lock the 12-slug list verbatim in script + tests. No guessed slugs.
- **Tier-B classification** — no daemon code change; no new auth surface; `bus.py` untouched.
- **Director-recipient block as load-bearing safety** — pinned by AC A6 with both shell + Python tests; explicit stderr cites brief sequencing.
- **Two-repo split** — baker-master shipped standalone per brief authorization; companion PR not gated.

## Lessons learned this build

- **V0.2 brief amendment recognised B2 boundary catch.** Original AC A7 (vault-side `_ops/agents/aihead{1,2}/orientation.md` + `_ops/skills/ai-head/SKILL.md` updates) was struck because vault files live at `~/baker-vault/_ops/` per CHANDA Inv 9 — outside B2 scope. AH1-T handles convention update separately. Anchor for future briefs: vault-side files are NEVER in B-code scope; the V0.2 fold pattern (`brief(b2-dispatch): V0.2 fold` commit `41dc9ef8`) is the documented escape hatch.

- **Pytest invocation discipline.** Bare `pytest` failed; `python3 -m pytest` succeeded. Going forward, B2 ship reports use the `python3 -m` form to avoid PATH-dependent ambiguity.

## Mailbox hygiene

Flipping `briefs/_tasks/CODE_2_PENDING.md` → COMPLETE in same commit as this report (per `_ops/processes/b-code-dispatch-coordination.md` §3).

## Next steps for AH1

1. **A5 manual smoke.** Run `BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh b2 "F2 smoke" "v2-bridge/f2/smoke"` from AH1-T own shell; verify HTTP 200 + B2 inbox receives the message.
2. **Vault-side convention update (struck-A7 lane).** Update `_ops/agents/aihead{1,2}/orientation.md` + `_ops/skills/ai-head/SKILL.md` to teach AI Heads the new `bus_post` invocation pattern (replaces paste-block-only convention for inter-worker dispatches).
3. **brisen-lab companion (A8/A9).** Optional. If wanted, dispatch B2 on brisen-lab repo for `b2/brisen-lab-v2-bridge-f2-authz-bools` (CallerContext bool-predicates + 4 new tests, ClickUp 86c9nr9dw closes on merge).
