# BRIEF: RESEARCHER_CAGE_ENFORCE_REMEDIATION_1 — unblock the Bash-cage ENFORCE flip (vetted inbox-read + multiline bus_post false-reject)

status: PENDING
dispatched_by: lead
assignee: b1
Harness-V2: task_class=medium-fix · gate plan: b1 build → codex G3 → lead merge → lead flips ENFORCE + POST_DEPLOY_AC_VERDICT

## Context Contract
- Inputs b1 needs: this brief; warn log `~/.claude/projects/-Users-dimitry-bm-researcher/bash-cage.log`; canonical cage `_ops/hooks/researcher_bash_cage.sh` + suite `_ops/hooks/tests/test_researcher_bash_cage.sh` (baker-vault main); reader precedent `~/Desktop/baker-code/scripts/check-lead-inbox.sh`; vetted-script precedent `scripts/bus_post.sh` (baker-master).
- NOT in context / do not assume: researcher seat env; any un-merged cage branch (all cage work is on main post-#143).
- Repos touched: baker-master (new script) + baker-vault (cage + tests). Two PRs, deploy-order-independent.

## Done rubric (done-state class: gate-verified merge + lead post-deploy flip)
1. Both PRs merged after codex G3 PASS.
2. Cage suite green, count ≥ 156, new ALLOW/DENY + regression cases included.
3. Live researcher-role probes pass under exported ENFORCE=1 (inbox read + multiline bus_post).
4. Fix-2 diagnosis outcome stated explicitly in ship report (bug fixed vs correct-deny documented).
5. Deployed-copy sync to `~/bm-researcher/.claude/hooks/` reported.
NOT done at: "compiles" / "suite passes locally without the new cases" / "script written but not allow-listed".

## Context

The researcher Bash-cage (RESEARCHER_HARNESS_RETROFIT_1 → RESEARCHER_GIT_WRAPPER_CAGE_CLOSE_1, vault PR #143 merged 2026-07-08, 156/156 suite, codex round-6 PASS) shipped WARN-only on the Bash leg by design: "lead reviews the log, then flips it ON." Lead reviewed the log today (flip decision was due 2026-07-10 15:00Z). **Verdict: NOT flippable yet — two workflow-breaking gaps.** This brief closes them so the flip can happen.

Warn-log evidence (`~/.claude/projects/-Users-dimitry-bm-researcher/bash-cage.log`, 130 would-block entries 07-07→07-10):

1. **No vetted inbox-READ path.** Researcher reads its bus inbox via `RESEARCHER_KEY=$(cat ~/.brisen-lab/keys/researcher) + curl + python3` — command substitution, curl, AND python3 are each denied (22 `$( )` denials on 07-10 alone). `ack_dispatch_msgs.sh` is ack-only, not a reader. Under ENFORCE=1 the researcher cannot drain its inbox at all.
2. **Vetted bus_post.sh false-rejects on multiline bodies.** Log entry 2026-07-10T11:41:46Z: a legitimate `BAKER_ROLE=researcher ~/bm-b1/scripts/bus_post.sh codex-arch "<multiline body>" "<topic>"` was denied with `segment leading command '1' not on the read-only allow-list` — the numbered-list line "1. SKILL NAME…" inside the QUOTED body became a segment leader. The vetted-path `continue` should have fired before any segment scan of body content. Under ENFORCE=1 the researcher cannot post multiline bus messages (its main delivery form).
3. (No code change) Raw `git add`/`git branch` denials on 07-10 = habit not yet migrated to `research_commit.sh` — the ENFORCE block message already steers there; acceptable.

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites: none (all on main; PR #143 merged)

## Baker Agent Vault Rails
Relevant: verification-surfaces (cage hooks + test suite), bus-and-lanes (vetted bus scripts). Ignore: standing-contract, skills-and-playbooks, memory-and-lessons, loop-runner.

---

## Fix 1: vetted read-only inbox script + allow-list entry

### Problem
No sanctioned way for a caged agent to READ its inbox. The lead's reader (`~/Desktop/baker-code/scripts/check-lead-inbox.sh`) is lead-specific and not allow-listed for researcher.

### Current State
- Vetted-path allow-list: `_ops/hooks/researcher_bash_cage.sh` (baker-vault) lines 175-183 — exact canonical paths only, all outside researcher-writable roots (`wiki/research/**` + session-memory dir). Deployed copy: `~/bm-researcher/.claude/hooks/researcher_bash_cage.sh`.
- Reader precedent: `~/Desktop/baker-code/scripts/check-lead-inbox.sh` — key from `~/.brisen-lab/keys/<slug>` with 1P fallback, GET `/msg/<slug>`, filters `acknowledged_at==null`, ignores wildcard broadcasts.

### Engineering Craft Gates
- Diagnose: N/A — gap is structural (no script exists), not a bug.
- Prototype: N/A.
- TDD: applies — new cage-suite cases BEFORE wiring: exact-path invocation ALLOW; impostor at a researcher-writable path (`~/baker-vault/wiki/research/check_inbox.sh`) DENY; relative/PATH-resolved invocation DENY.

### Implementation
1. Create `scripts/check_inbox.sh` in **baker-master** (lands at `~/bm-b1/scripts/check_inbox.sh`, the same trusted root as the vetted `bus_post.sh`). Generalize from `check-lead-inbox.sh`: slug from `BAKER_ROLE` (mapped via `scripts/agent_identity_generated.sh`, same sourcing pattern as `bus_post.sh`), key from `~/.brisen-lab/keys/<slug>` then 1P fallback, GET `${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}/msg/<slug>?limit=<N>`, print unacked (exclude `to_terminals==['*']`), read-only — no ack, no write, no eval of message content.
2. Add ONE exact-path entry to the vetted `case "$VS"` block in `_ops/hooks/researcher_bash_cage.sh` (baker-vault):
   ```sh
   "$HOME"/bm-b1/scripts/check_inbox.sh) continue ;;
   ```
   Keep the exact-path discipline — no basename matching, no glob (codex G3 F1 lesson in the file header).
3. Sync the deployed copy `~/bm-researcher/.claude/hooks/researcher_bash_cage.sh` (same content as canonical; note the sync in the ship report).

### Key Constraints
- The new script must itself be safe-to-trust: no arg-driven exec, no writes, no ack side-effect. `set -u`, quote all expansions.
- Do NOT add curl/python3 to the general allow-list — the vetted-script exact-path is the only widening.

### Verification
- Cage suite: new ALLOW/DENY cases green, full suite green (was 156/156 — must not regress).
- Live probe as researcher role: `BAKER_ROLE=researcher ~/bm-b1/scripts/check_inbox.sh` returns unacked list with cage hook active and `RESEARCHER_BASH_CAGE_ENFORCE=1` exported in the probe shell.

---

## Fix 2: diagnose + fix multiline-quoted-body false-reject on vetted script invocations

### Problem
A vetted `bus_post.sh` call with a multiline double-quoted body is denied — segment scanning ran over quoted body content ("segment leading command '1'", also `'#'` entries). 9 occurrences on 07-09/07-10, all legitimate posts.

### Current State
`_ops/hooks/researcher_bash_cage.sh`: `scan_reveal()` (lines 78-107) is supposed to neutralize in-quote structural bytes (incl. NL, line 73-76) to sentinel `\x1f`; `SEGMENTS` split (line 148) then iterates; vetted-path check (lines 168-183) `continue`s per segment. Evidence says a quoted-NL body still produced body-content segments.

### Engineering Craft Gates
- Diagnose: applies. Feedback loop: pipe a captured hook payload (JSON with the exact logged CMD from the 2026-07-10T11:41:46Z entry) into the script, observe deny reason — seconds per iteration. Ranked hypotheses: (H1) `scan_reveal` fast-path/quote-state bug when the body mixes quotes + backslashes + parens (body contained `( )`, `->`, quotes); (H2) the logged CMD contains an unquoted `&&`/newline outside the body (multi-command chain: `... && git push origin main` appears in the adjacent log entry — verify which entry maps to which CMD); (H3) `$( )`/backtick pre-check on `SKEL_SQ` fires on body content (different deny reason — check exact reason strings in log). Probe: reproduce → fix → the SAME payload must ALLOW.
- Prototype: N/A.
- TDD: applies — add the captured real-world payload as a regression case (scrub matter content, keep structure: numbered list lines, parens, quotes, newlines) BEFORE fixing.
- IMPORTANT: if diagnosis shows the denied CMD was actually a `bus_post && <non-vetted segment>` chain (H2), the cage behaved CORRECTLY — then Fix 2 becomes docs-only: append a "chain vetted calls as separate Bash invocations" note to the ENFORCE block message, and say so in the ship report. Do not "fix" a correct deny.

### Key Constraints
- Fail-closed posture is non-negotiable: any fix must not widen what non-vetted segments can do. Every existing DENY case in the suite must still deny.
- Never weaken the exact-path vetted match or the quoted-flag reveal logic (codex #7230 / #7208 / #7272 regressions are in the suite — keep them green).

### Verification
- Regression case (captured payload) flips DENY→ALLOW (or is documented as correct-deny per the H2 escape hatch).
- Full cage suite green; codex G3 on the diff.

---

## Files Modified
- `baker-master: scripts/check_inbox.sh` — NEW vetted read-only inbox reader.
- `baker-vault: _ops/hooks/researcher_bash_cage.sh` — allow-list entry + Fix-2 outcome.
- `baker-vault: _ops/hooks/tests/test_researcher_bash_cage.sh` — new ALLOW/DENY + regression cases.
- `~/bm-researcher/.claude/hooks/researcher_bash_cage.sh` — deployed-copy sync (report the sync).

## Do NOT Touch
- `_ops/hooks/researcher_write_cage.sh` — enforce-ON, working, out of scope.
- `research_commit.sh` — sanctioned and working; git-habit denials are steering, not bugs.
- Researcher seat `settings.json` env — the ENFORCE flip itself is LEAD's action after merge, not b1's.

## Quality Checkpoints
1. Cage suite fully green (no count regression from 156).
2. Live researcher-role probe: inbox read + multiline bus_post both ALLOW under exported ENFORCE=1.
3. Impostor-path DENY probes still deny.
4. codex G3 PASS on both repos' diffs.
5. Ship report states Fix-2 diagnosis outcome explicitly (bug fixed vs correct-deny documented).

## After merge (lead lane, not b1)
Lead flips `RESEARCHER_BASH_CAGE_ENFORCE=1` in the researcher seat env, runs one live researcher session watch, posts POST_DEPLOY_AC_VERDICT. New flip target: within 24h of merge.
