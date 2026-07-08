# BRIEF: RESEARCHER_GIT_WRAPPER_CAGE_CLOSE_1 — vetted research_commit.sh wrapper + git deny-by-default, closing the cage before the ENFORCE flip

dispatched_by: lead
assignee: b1
effort: high (recommended tier for codex gate: high — security cage, adversarial history)
repo: baker-vault (`_ops/hooks/researcher_bash_cage.sh` + new wrapper script; brief filed in baker-master per dispatch convention)
task_class: security-hardening (defensive: egress/exfil containment for the researcher agent's Bash lane)
deadline: ENFORCE flip scheduled 2026-07-10 15:00Z — flip only fires if this lands + gates PASS; otherwise I delay the flip (ruled: never flip porous)

## Context

Researcher Bash-cage ENFORCE flip is scheduled 2026-07-10 15:00Z. Current state (your #6663 + codex #6760):
- Vault branch `b1/researcher-harness-retrofit` @21a1b88 carries 2 commits NOT on vault main: `2b538ef` (quote/chaining/encoding parser hardening — codex PASS #6680) and `21a1b88` (git/gh/env-prefix hardening — codex FAIL #6760).
- Codex #6760 proved on exact tip @21a1b88 with `RESEARCHER_BASH_CAGE_ENFORCE=1`: `git notes add`, `git worktree add`, out-of-cage `git add` all exit 0 (expected block). Cage lines 107-113 deny selected git vectors; 116-120 still allow leading `git` generally.
- Your durable-fix recommendation (#6663, endorsed): raw git is inherently leaky for a caged agent (arbitrary-remote push = exfil; many exec vectors). Replace git-for-delivery with a vetted wrapper so raw git write access leaves the allow-list entirely. Codex's required closure (#6760, explicit allowed forms + deny-by-default) is the same policy — the wrapper implements it in one auditable place instead of parsing git invocations in the cage.

### Context Contract
- Cage: `_ops/hooks/researcher_bash_cage.sh` (vault) — lines 107-120 are the git policy to invert.
- Prior hardening branch: `b1/researcher-harness-retrofit` @21a1b88 (2 unmerged commits, dispositions differ — see Task).
- Researcher delivery surface: commits research artifacts to `wiki/research/**` + its own session-memory paths, push `origin HEAD` only.
- Pattern precedent: `scripts/bus_post.sh` (single vetted script replacing raw capability).
- Gate history: #6618→#6680 PASS (parser), #6657/#6672→#6760 FAIL (git writes). Adversarial reviewer keeps finding vectors — assume more exist; deny-by-default is the only stable posture.

## Problem

The cage allow-lists `git` broadly, so any git write subcommand (notes, worktree, add outside approved paths, config, etc.) escapes the cage while ENFORCE=1. The researcher needs exactly ONE write capability (deliver research to approved vault paths) and a handful of read-only git forms — everything else is attack surface.

## Task

1. **Land the PASS'd commit:** cherry-pick `2b538ef` (parser hardening, codex PASS #6680) onto vault main cleanly. Do NOT land `21a1b88` as-is — its approach (selective deny) is superseded by this brief; salvage its env-prefix/`-c` smuggling guards into the new policy.
2. **Build `research_commit.sh`** (vault `_ops/scripts/` or alongside the cage; mirror bus_post.sh conventions): args = file path(s) + commit message. Behavior: validates every path against the approved-prefix list (`wiki/research/**` + researcher session-memory paths — enumerate the exact list in the script header), `git add` only those paths, `git commit`, `git push origin HEAD`. Fail-loud (non-zero + stderr) on: path outside prefixes, non-origin remote configured for push, any flag smuggling. No pass-through of arbitrary git args.
3. **Invert the cage git policy:** allow ONLY exact read-only forms `git log|diff|show|status` (with the salvaged env-prefix/`-c`/chaining guards so smuggled forms don't match); DENY every other git invocation by default. Remove the general leading-`git` allowance (lines 116-120 class). `gh` policy: same deny-by-default posture — re-verify what researcher genuinely needs (likely nothing; document).
4. **Seeded adversarial tests** (must FAIL pre-fix, PASS post-fix, run with `RESEARCHER_BASH_CAGE_ENFORCE=1`): `git notes add`, `git worktree add`, out-of-cage `git add`, `git -c core.editor=... commit`, env-prefix forms, `git push <arbitrary-remote>`; positive controls: the 4 read-only forms allowed, wrapper delivers to an approved path end-to-end.
5. **Researcher orientation line:** delivery = `research_commit.sh` only; raw git writes will be denied. One line + pointer, in the researcher role-context/orientation file.

## Files Modified

- `_ops/hooks/researcher_bash_cage.sh` (vault) — inverted git policy + salvaged smuggling guards.
- `_ops/scripts/research_commit.sh` (vault, NEW) — vetted delivery wrapper.
- Cage seeded-test file (vault, wherever the existing cage tests live — discover; fail-loud if none exist and create).
- Researcher orientation/role-context — one delivery-rule line.
- Nothing in baker-master except this brief.

## Constraints (hard)

- Defensive containment only: this brief hardens an internal agent's egress. No offensive tooling, no bypass documentation beyond seeded negative tests.
- Do NOT flip `RESEARCHER_BASH_CAGE_ENFORCE` yourself — flip stays lead-owned, post-gate.
- Researcher must remain able to deliver: the wrapper path is proven end-to-end BEFORE the old path closes (test on a scratch commit to an approved path).
- Vault main only via clean branch + gate; no direct-main pushes for cage code.

## Verification

1. TDD: seeded adversarial suite red on current main, green post-change (literal run output with ENFORCE=1).
2. Positive: `research_commit.sh` scratch-delivery to `wiki/research/` succeeds; `git push` to a non-origin remote via wrapper impossible (literal output).
3. Codex G3 (effort: high) on the exact tip — the same reviewer that found #6618/#6657; request explicitly names the prior FAIL findings as regression checks.
4. Read-only forms still work from a researcher-simulated shell (literal output).

## Acceptance criteria (done rubric)

- AC1: `2b538ef` landed on vault main (hash in report).
- AC2: Wrapper live + scratch-delivery proven end-to-end (literal output).
- AC3: Cage deny-by-default: all 6+ seeded adversarial forms blocked, 4 read-only forms allowed (literal ENFORCE=1 runs).
- AC4: codex G3 high PASS at exact tip, explicitly closing #6657/#6672/#6760.
- AC5: Researcher orientation updated; ship report to `briefs/_reports/`.

Done-state: all 5 ACs with literal evidence. Flip readiness is then MY call — report leaves the flag untouched.

## Gate plan

codex G3 (effort: high, regression-check the #6760 findings by name) → lead merge → lead decides ENFORCE flip vs delay before 2026-07-10 15:00Z. No Director gate (Tier-A security hardening, pre-authorized lane).

## Reply target

Bus-post all state changes (start, blocker, gate request, ship) to `lead`. Reply-target = lead.
