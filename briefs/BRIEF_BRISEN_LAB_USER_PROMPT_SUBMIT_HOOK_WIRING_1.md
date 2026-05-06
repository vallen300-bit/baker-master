# BRIEF: BRISEN-LAB-USER-PROMPT-SUBMIT-HOOK-WIRING-1 — activate H7 auth chain + Surface 5 inbox drain

## Context

The 2026-05-05 V2 cutover (`BRISEN_LAB_V2_ENABLED=true`) is daemon-side complete. The H7 auth chain (ed25519 session-pubkey + human-confirmation JWT) was built into `.claude/hooks/user-prompt-submit-confirm.py` (V0.3.7 + Surface 6a 409 retry) but is **dormant** because no `settings.json` references it as a `UserPromptSubmit` hook.

Without the hook wired:
- No `POST /auth/register-session-pubkey` calls fire on real prompts.
- No human-confirmation JWT minted.
- `POST /msg/<id>/ratify_decision` returns 403 forever.
- Surface 5 inbox drain (auto-pull-on-prompt) doesn't run.
- Director cannot see Cowork → Lead messages without manually invoking `mcp__baker__baker_inbox_read`.

This brief activates the hook across the auth-bearing roles.

## Estimated time: ~15 min
## Complexity: Low (config-only — no code change)
## Prerequisites: V2 cutover live + 3+ terminal keys provisioned (done 2026-05-05 — 3 keys; full 12 covered in BRIEF_BRISEN_LAB_AUTH_COMPLETION_1)
## Tier: B (config touching every auth-bearing terminal launcher; no code, no DB, no auth-logic change)

---

## Feature 1 — Wire `user-prompt-submit-confirm.py` as a `UserPromptSubmit` hook

### Problem

`~/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py` exists, syntax-clean, V0.3.7 + Surface 6a fold landed (PR #161, commit `87f0535`). It is REFERENCED nowhere. Verified by:

```
$ grep -rE "user-prompt-submit-confirm|UserPromptSubmit" \
    ~/.claude ~/Desktop/baker-code/.claude \
    ~/bm-aihead1/.claude ~/bm-aihead2/.claude \
    ~/bm-b1/.claude ~/bm-b2/.claude ~/bm-b3/.claude ~/bm-b4/.claude ~/bm-b5/.claude
# → only the file itself shows up; zero settings.json references anywhere.
```

### Current state

`~/Desktop/baker-code/.claude/settings.json` wires only `SessionStart` (`~/forge-agent/session-start-hook.sh`), `PostToolUse` (syntax-check), `PreToolUse` (block-secrets). No `UserPromptSubmit`.

The hook itself is correct in design:
- `_AUTH_BEARING_ROLES = {director, cowork-ah1, lead, deputy, architect, ah1, ah2}` — only auth-bearing roles run the auth chain. Other workers (b1–b5, cortex) skip cleanly.
- Hook always exits 0 (NEVER blocks Claude startup — discipline from PR #149).
- Reads `BAKER_ROLE` env to determine its slug; reads `BRISEN_LAB_V2_ENABLED` to early-exit if frozen.

### Implementation

**Files modified (config only — no code edits):**
1. `~/Desktop/baker-code/.claude/settings.json` (this terminal — `lead`)
2. `~/bm-aihead2/.claude/settings.json` (`deputy`)
3. `~/bm-b1/.claude/settings.json` (`b1` — currently has only `settings.local.json`)
4. `~/bm-b2/.claude/settings.json` (already exists; merge UserPromptSubmit block)
5. `~/bm-b3/.claude/settings.json` (`b3` — does the dir even have a `.claude/` config? — verify)
6. `~/bm-b4/.claude/settings.json` (`b4`)
7. `~/bm-b5/.claude/settings.json` (`b5`)

(`~/bm-aihead1/.claude/settings.json` — verify; this is the Cowork-AH1 picker symlink target.)

**Hook block to add to each settings file (V0.4: AUTHORITATIVE — split by file type per §A timeout-30 + §J path-strategy):**

> **⚠️ V0.4: TWO blocks — choose based on file type. The V0.1 single-block design below was SUPERSEDED by §A (timeout fix) and §J (path-strategy split). Both blocks below are the operative versions; do NOT use the V0.1 single-block.**

| File type | File path(s) | Hook block to use |
|---|---|---|
| **Committed** | `~/Desktop/baker-code/.claude/settings.json` (only) | **Block A — symlink path** (below) |
| **Device-local** | `~/bm-aihead1/.claude/settings.local.json`, `~/bm-aihead2/.claude/settings.local.json`, `~/bm-b1..b5/.claude/settings.local.json` | **Block B — direct absolute path** (below) |

**Block A — Committed file (symlink path, requires `~/.baker-hooks/` sequencing 0a):**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/dimitry/.baker-hooks/user-prompt-submit-confirm.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

**Block B — Device-local files (direct absolute path, no symlink dependency — eliminates "sh: no such file" SIGKILL hazard per §J):**

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}
```

> **Note (V0.4 M2):** the path above is host-specific (`/Users/dimitry/Desktop/baker-code/`). Do NOT copy verbatim to a machine where baker-code lives at a different path. AH1 wires this on Director's MacBook only.

**Critical wiring rules:**

- **MERGE with existing `hooks` block** — do NOT clobber `SessionStart`, `PostToolUse`, `PreToolUse`. If a `settings.json` already has a `hooks` key, fold the new `UserPromptSubmit` array in.
- **Path strategy (V0.4 per §J):** committed file uses `~/.baker-hooks/` symlink (Block A); device-local `settings.local.json` uses direct absolute path (Block B). Symlink-missing-on-device → `sh: no such file` exits non-zero BEFORE Python starts, bypassing the `sys.exit(0)` safety net.
- **Timeout = 30s (V0.4 per §A — was 15s in V0.1, fix CRITICAL):** hook does up to 3 sequential HTTPS calls (register-pubkey + human-confirm + drain) at 5s + 5s + 8s timeouts internally + Surface 6a 409 retry adds ~5s jitter. Worst-case = 23.15s sequential. 30s outer = ~6.85s cushion for OS scheduling + Render Frankfurt egress slow first-byte.
- **Worker scope per role**: B-codes (b1–b5) and `cortex` are NOT auth-bearing. The hook self-skips for non-auth-bearing roles via `_AUTH_BEARING_ROLES` early return. **Wire it anyway** — keeps the surface uniform; future role-policy changes don't need a settings.json sweep. The skip path costs ~5 ms (no HTTPS calls). Negligible.

**For each picker that needs the wire:**

If `settings.json` does not exist, create with the full hooks structure (mirror `~/Desktop/baker-code/.claude/settings.json`'s shape — preserve `SessionStart` `forge-agent/session-start-hook.sh`).

If `settings.json` exists with other hooks: open, parse JSON, add `"UserPromptSubmit"` key into the existing `"hooks"` object, write back. Use `Edit` tool string-replace, not full rewrite — minimizes blast radius.

### Key constraints

- **Hook contract: ALWAYS exit 0.** Already enforced in the script (`PR #149 discipline` — file header line 19). Wiring change does NOT reopen that contract.
- **No symlink breakage.** Tonight's AH2 picker uses a symlink `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-aihead2 → /Users/dimitry/bm-aihead2` (per CLAUDE.md AH2 block). Wiring goes into the resolved path (`~/bm-aihead2/.claude/settings.json`), not the symlink-source.
- **No `BRISEN_LAB_V2_ENABLED=false` test** today. Default is `true`; the hook self-checks and exits cleanly when frozen. If a future drill flips to `false`, the hook returns immediately — no settings.json change needed.
- **Don't add `UserPromptSubmit` to `~/.claude/settings.json` (global)** — the global config is unscoped; global wiring would fire the hook on EVERY Claude Code session including non-Baker matter desks (AO Desk, MOVIE Desk, etc.) which DO NOT have `BAKER_ROLE` in the auth-bearing set. Self-skip is harmless but adds a per-prompt HTTPS lookup latency cliff. Per-picker wiring is the right surface.
- **bm-aihead1 picker symlinks to a Dropbox-synced folder** (`~/Vallen Dropbox/Dimitry vallen/bm-aihead1/`). Wiring goes there. Verify before edit.

### Verification

#### Per-picker syntax check

```bash
for picker in ~/Desktop/baker-code ~/bm-aihead2 ~/bm-b1 ~/bm-b2 ~/bm-b3 ~/bm-b4 ~/bm-b5; do
  if [ -f "$picker/.claude/settings.json" ]; then
    python3 -c "import json; json.load(open('$picker/.claude/settings.json'))" \
      && echo "OK: $picker/.claude/settings.json valid JSON" \
      || echo "FAIL: $picker/.claude/settings.json invalid"
  else
    echo "MISSING: $picker/.claude/settings.json (create per brief)"
  fi
done
```

#### Live hook fire test (manual, in fresh session)

1. Open fresh `aihead1` shell — picks up new settings.json.
2. Submit any prompt (literal: `hello`).
3. Verify Render brisen-lab daemon logs show:
   ```
   POST /auth/register-session-pubkey 200 (<10ms)
   POST /auth/human-confirmation 200 (<10ms)
   ```
4. If those land, the hook is wired and authenticating. If you see 401 instead → terminal-key not loaded into env (confirm `BRISEN_LAB_TERMINAL_KEY` is set on the shell). If 503 → V2 frozen. If hook didn't fire at all → settings.json malformed or path wrong.

#### End-to-end ratify_decision verification (depends on AUTH_COMPLETION_1 F3 = 12 keys provisioned)

Once ratify is exercised, surface success via:

```sql
-- TEST_DATABASE_URL_BRISEN_LAB or prod
SELECT COUNT(*) FROM brisen_lab_session_keys WHERE expired_at IS NULL;
```

(Should be ≥ 1 after first wired-hook prompt; rolls per-prompt under V0.3.7 atomic UPDATE+INSERT.)

---

## Acceptance Criteria

| AC | Description | Verification |
|---|---|---|
| **A1** | `~/Desktop/baker-code/.claude/settings.json` has `hooks.UserPromptSubmit` array containing the hook command at absolute path | grep + JSON validate |
| **A2** | All 6 worker pickers (`bm-aihead2`, `bm-b1`–`bm-b5`) have `settings.json` with the same wire | per-picker grep |
| **A3** | `bm-aihead1` (Cowork-AH1 Dropbox-synced picker) has `settings.json` with the same wire | grep + JSON validate |
| **A4** | All 7+ `settings.json` files parse as valid JSON | one-liner script in Verification §1 |
| **A5** | No regression: existing `SessionStart` / `PostToolUse` / `PreToolUse` hooks preserved | diff against pre-edit |
| **A6** | Live test: fresh `aihead1` session, submit prompt, Render log shows `/auth/register-session-pubkey 200` + `/auth/human-confirmation 200` within ~5s | tail Render log |
| **A7** | `~/.claude/settings.json` (global) is NOT modified | grep — must not contain `user-prompt-submit-confirm` |
| **A8** | After Step 30 / next live cycle: `brisen_lab_session_keys` table has ≥ 1 active row keyed by `lead` after first prompt submit in `aihead1` | SQL query against prod DB |

**Ship gate:** A1–A5 all green. A6 verified manually post-merge.

---

## Files Modified

- `~/Desktop/baker-code/.claude/settings.json` — add UserPromptSubmit array
- `~/bm-aihead1/.claude/settings.json` — add or create
- `~/bm-aihead2/.claude/settings.json` — add or create
- `~/bm-b1/.claude/settings.json` — add or create (currently only `settings.local.json` exists)
- `~/bm-b2/.claude/settings.json` — add (exists; merge)
- `~/bm-b3/.claude/settings.json` — add or create
- `~/bm-b4/.claude/settings.json` — add or create
- `~/bm-b5/.claude/settings.json` — add or create

## Do NOT Touch

- `~/.claude/settings.json` (global) — out of scope.
- `~/forge-agent/session-start-hook.sh` — different hook, different lifecycle.
- `.claude/hooks/user-prompt-submit-confirm.py` itself — already V0.3.7 + Surface 6a folded; no script change in this brief.
- `block-secrets.sh` / `syntax-check.sh` — unaffected.
- AH1's tmux + Mac Mini wiring — out of scope.

---

## Quality Checkpoints

1. JSON parse OK on every file edited.
2. `git diff` per file is clean — only the new hooks key/array, no whitespace churn.
3. Live test (Verification §2) — register-session-pubkey 200 timestamp captured.
4. Verify the 6 pickers' files are untracked-or-tracked consistently — bm-* picker repos may be separate from baker-master git tracking; check whether `settings.json` per-picker is in `.gitignore` or committed (per project conventions, `.claude/settings.local.json` is `.gitignore`'d but `.claude/settings.json` is committed in some cases). Don't accidentally commit local-only changes.

---

## Sequencing

1. AH1 verifies which picker dirs exist + their git-track status.
2. AH1 reads each existing `settings.json` to understand current shape (avoid clobber).
3. AH1 edits each with `Edit` tool string-replace (or `Write` for new file creation), folding `UserPromptSubmit` into existing `hooks` block.
4. AH1 runs the JSON validation script (Verification §1).
5. AH1 commits any tracked picker-side changes (likely none — `.claude/settings.json` per-picker is typically `.gitignore`'d for personalization). Document in the actions log.
6. AH1 fresh-start `aihead1` shell (or quits + re-runs `aihead1`).
7. AH1 submits the literal "hello" prompt; verifies Render log shows 200 trio.
8. AH1 reports closure to Director.

**Optional follow-up (not in scope but adjacent):** wire `SessionStart` hook for the auth-chain pre-warm — currently the H7 chain initialises lazily on first UserPromptSubmit. A SessionStart pre-warm would shave ~150ms off the first prompt. Out of scope for this brief; spin separately if Director ratifies.

---

## Open questions for AH1 (for Director if non-obvious)

**Q1.** Is `bm-aihead1` `.claude/` Dropbox-synced (per Cowork pickers reference in user CLAUDE.md)? If yes, the settings.json edit propagates to all devices syncing that picker. Confirm the wire is appropriate for ALL devices. If laptop A wires the hook but laptop B has no `BRISEN_LAB_TERMINAL_KEY` env, the hook fires + 401s + adds latency. Suggest: either ensure key propagation matches, or scope wire to a specific device's local `.claude/settings.local.json` (which is NOT Dropbox-synced).

**Q2.** Should B-code pickers (b1–b5, cortex) get the wire even though their roles self-skip the auth chain? Recommendation: yes (uniform surface; trivial cost). Director may prefer NO (avoid unnecessary file changes). Default to yes; flip if Director directs.

---

## Reference

- Hook source: `.claude/hooks/user-prompt-submit-confirm.py` (V0.3.7 + Surface 6a, latest commit `87f0535`)
- Auth-bearing role list: hook source line 48-51
- Session-start hook (already wired): `~/forge-agent/session-start-hook.sh`
- V2 cutover deploy: `dep-d7t6qfog4nts73epb28g` (LIVE 2026-05-05T22:21:58Z)
- Terminal-key bootstrap: this session's transcript + `BRIEF_BRISEN_LAB_AUTH_COMPLETION_1` F3
- HARDENING.md H7 spec: `~/bm-b4-brisen-lab/docs/HARDENING.md`
- Brief V2_BRIDGE_1 §6 H7 §1.4: timeout window justification
- Tasks/lessons.md Lesson #X (PR #149): hook-script-blocking-claude-startup discipline

---

# V0.2 Amendment — Architect-reviewer fold (2026-05-05)

> **Trigger:** post-WRITE architect-reviewer pass surfaced one CRITICAL timeout-math error and two HIGH design gaps. Folding before AH1 executes.

## Amendment §A — CRITICAL: timeout math fix

**Reviewer finding (CRITICAL, confidence high):** the V0.1 `"timeout": 15` outer value is INSUFFICIENT for the worst-case path:

```
register-session-pubkey:    5.0s   (_REGISTER_TIMEOUT_S)
+ Surface 6a 409 retry:     0.05–0.15s jitter + 5.0s second attempt
+ human-confirmation:       5.0s   (_HUMAN_CONFIRM_TIMEOUT_S)
+ inbox drain:              8.0s   (_DRAIN_TIMEOUT_S)
─────────────────────────────────
Worst-case sequential:     ~23.15s
```

15s outer timeout would SIGKILL the hook mid-drain or mid-human-confirm, BEFORE Python reaches the `sys.exit(0)` last-resort guard. Result: terminal-startup hazard (the exact failure mode PR #149 / Lesson #X documented). The "always exits 0" contract HOLDS only via clean Python exit; SIGKILL bypasses it.

**Action:** raise outer timeout to **30 seconds**:

```json
{
  "type": "command",
  "command": "python3 ~/.baker-hooks/user-prompt-submit-confirm.py",
  "timeout": 30
}
```

Cushion: 30s − 23.15s worst-case = ~6.85s for OS scheduling + slow first-byte from Render Frankfurt egress. UX impact: in the success path (most prompts) the hook finishes in 200–500ms; the 30s cap only kicks in on a hung daemon, where killing the hook IS the right behavior (and 30s is still well under user-perception "stuck-forever" threshold of ~60s).

Fold AC A6 verification step: also confirm a SUCCESS-PATH timing measurement < 1s — protects against silent regression where every prompt eats 5–8s.

## Amendment §B — HIGH: stable hook-path symlink

**Reviewer finding (HIGH, confidence high):** the V0.1 hard-coded path `/Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py` is fragile across all 7+ pickers. If Director moves baker-code or remounts the volume, all 7 settings.json refs break simultaneously.

**Action — create stable symlink path:**

Step 0 (NEW, PRECEDES Sequencing §1):

```bash
mkdir -p ~/.baker-hooks
ln -sfn /Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py \
  ~/.baker-hooks/user-prompt-submit-confirm.py
ls -la ~/.baker-hooks/
# Expect: user-prompt-submit-confirm.py → /Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py
```

Then EVERY settings.json wires:

```json
"command": "python3 ~/.baker-hooks/user-prompt-submit-confirm.py"
```

(Or use absolute `/Users/dimitry/.baker-hooks/...` if Claude Code doesn't expand `~` in hook commands — verify behavior in fresh aihead1 session per Verification §2 before declaring done. If `~` doesn't expand, fall back to `/Users/dimitry/.baker-hooks/...`.)

Add a new AC:

| **A9** | `~/.baker-hooks/user-prompt-submit-confirm.py` symlink exists; `readlink` returns the absolute path | `ls -la ~/.baker-hooks/` |

If Director ever moves baker-code, the only update is the symlink — not 7 settings.json files.

## Amendment §C — HIGH: bm-aihead1 Dropbox-sync scope decision

**Reviewer finding (HIGH, confidence high):** `bm-aihead1` is a Dropbox-synced picker (per user CLAUDE.md role-pickup pattern). If `.claude/settings.json` propagates to a second device that lacks `BRISEN_LAB_TERMINAL_KEY` in env, every prompt on that device hits 13s of failed HTTPS (5s register fail + 8s drain fail) before silent exit. Latency cliff with no user-visible cause.

**Action — use device-local settings:**

For `bm-aihead1`, write to `~/Vallen Dropbox/Dimitry vallen/bm-aihead1/.claude/settings.local.json`, NOT `settings.json`. Per Claude Code convention: `settings.local.json` is `.gitignore`'d and explicitly device-scoped. (Dropbox-sync still happens at the OS level, but the convention signals "don't expect this to be authoritative across devices.")

Better fix: AH1 confirms whether the Dropbox folder syncs `.claude/settings.local.json` (some `.gitignore`-matching files are excluded from Dropbox by Smart Sync rules). If yes → propagate; if no → device-local. Document the determination in `_ops/agents/ai-head/actions_log.md` with the exact path tested.

ABSENT a confirmation, default policy: **wire only `~/Desktop/baker-code/.claude/settings.json` (this terminal — `lead`)** + `~/bm-aihead2/.claude/settings.json` (deputy, local-only). Skip bm-aihead1 wire until Dropbox-sync behavior verified. Surface to Director as a Q.

## Amendment §D — MED: per-picker settings.json git-track decision

**Reviewer finding (MED, confidence high):** none of `bm-b1` through `bm-b5` or `bm-aihead2` currently have a `.claude/settings.json` (only `.claude/settings.local.json` exists in some). AH1 will be CREATING new files. Brief V0.1 says "verify" but doesn't decide.

**Action — explicit decision:** wire to **`.claude/settings.local.json`** for ALL worker pickers (bm-b1..b5, bm-aihead2). Rationale:
1. Local-machine paths embedded in the file (the symlink resolves on this Mac only — irrelevant if cross-device, but no harm).
2. Aligns with existing `.gitignore` defaults across worktrees.
3. Allows per-device customization without commit-race in shared worktrees.

For `~/Desktop/baker-code/.claude/settings.json` (this terminal — checked into baker-master repo): wire there since the file is committed and the symlink path is stable. No commit race because this brief is the first to touch UserPromptSubmit.

## Amendment §E — MED: drain rationale revision for b1–b5 wire

**Reviewer finding (MED, confidence high):** V0.1 cited "drain side runs for all roles" as rationale for wiring b1–b5. Reviewer correctly notes b1–b5 don't have `BRISEN_LAB_TERMINAL_KEY` set so drain self-skips at hook line 330.

**Action — revised rationale:** wire b1–b5 anyway, BUT cite "uniform surface — future role policy changes don't need a sweep" as the reason, NOT drain. Cost is one env lookup + one early return per prompt (~1ms). Negligible. Drain is bonus once F3 (AUTH_COMPLETION_1) lands and b1–b5 keys exist.

## Amendment §F — LOW: hook-load verification step

**Reviewer finding (LOW, confidence medium):** A6's "tail Render log" verification doesn't catch silent hook-load failures (malformed JSON merge → Claude Code logs warning + skips hook → user never sees the failure).

**Action — add explicit hook-load check** in Verification §2:

```bash
# After settings.json edit, before live test:
python3 -c "import json; json.load(open('$HOME/Desktop/baker-code/.claude/settings.json'))" \
  && echo "JSON valid"
# Submit literal prompt 'hello' in fresh aihead1 session.
# Then check Claude Code's hook-execution log (location varies — check ~/.claude/cache/ for hook-related files):
grep -rE "user-prompt-submit-confirm|UserPromptSubmit" ~/.claude/cache/ 2>/dev/null | tail -5
# Expect: at least one log entry showing hook fired in this session.
```

## Amendment §G — Updated Sequencing

Insert after V0.1 §Sequencing step 0:

**0a (NEW).** Create `~/.baker-hooks/` symlink (Amendment §B Step 0).
**0b (NEW).** Verify bm-aihead1 Dropbox-sync handling for `.claude/settings.local.json` — record finding in actions_log. If unverified, scope wire to local pickers only (Amendment §C).
**0c (NEW).** Confirm `~/.baker-hooks/user-prompt-submit-confirm.py` symlink resolves: `python3 ~/.baker-hooks/user-prompt-submit-confirm.py < /dev/null; echo $?` → expect `0` (fast clean exit on empty stdin).

Subsequent steps unchanged but:
- Step 3 (per-picker edits): wire to `.claude/settings.local.json` for b1–b5 + aihead2 + (conditionally) bm-aihead1; wire to `.claude/settings.json` for `Desktop/baker-code` only.
- Step 6 (live test): use the 30s timeout + symlink path + hook-load verification per Amendments §A + §B + §F.

## Amendment §H — Acceptance Criteria deltas

**New:**
| **A9** | `~/.baker-hooks/user-prompt-submit-confirm.py` symlink exists; resolves to baker-code hook | `ls -la ~/.baker-hooks/` |
| **A10** | `timeout: 30` in every UserPromptSubmit hook block | grep — must NOT show `"timeout": 15` |
| **A11** | bm-aihead1 wire decision documented in `~/baker-vault/_ops/agents/ai-head/actions_log.md` | grep actions_log |
| **A12** | Live test success-path timing < 1s wall-clock (steady-state, not first-fire cold-start) | timing measurement in test |

**Replaced:**
- A6: now explicitly requires both 200 trio AND <1s wall-clock.

## Amendment §I — Net effect summary

- **Outer timeout 15s → 30s** (CRITICAL fix; prevents SIGKILL → terminal-startup hazard).
- **Stable symlink at `~/.baker-hooks/`** (HIGH; eliminates 7-file fragility).
- **bm-aihead1 wire scoped to settings.local.json** (HIGH; avoids cross-device latency cliff).
- **Worker pickers wire to settings.local.json** (MED; matches gitignore defaults).
- **b1–b5 rationale revised** to "uniform surface" not "drain runs for all" (MED; accuracy).
- **Hook-load verification step added** (LOW; catches silent malformed-JSON failures).

**Brief intent (activate H7 auth chain + Surface 5 inbox drain across auth-bearing terminals) preserved.**

**End V0.2 amendment.**

---

# V0.3 Amendment — Pre-execute code-reviewer fold (2026-05-06)

> **Trigger:** AH1-App-spawned `feature-dev:code-reviewer` 2nd-pass on V0.2 returned VERDICT PASS-WITH-NITS (1 HIGH + 1 MEDIUM). Folding before AH1 executes. Reviewer agent ID: `a89b11bf39ec316f8`.

## Amendment §J — HIGH: drop symlink for device-local wires; reserve for committed file only

**Reviewer finding (HIGH, confidence high):** V0.2 §B's stable-symlink approach has a silent failure mode: if `~/.baker-hooks/user-prompt-submit-confirm.py` is missing on a device (e.g., bm-aihead1's Dropbox-synced settings.local.json reaches Mac Mini, but `~/.baker-hooks/` was never created there), the shell command `python3 ~/.baker-hooks/user-prompt-submit-confirm.py` fails BEFORE Python starts — `sh` returns non-zero from "no such file" and the hook's internal `sys.exit(0)` safety net is bypassed. Result: terminal-startup hazard returns (the exact failure the timeout fix was designed to eliminate).

**Action — split wiring strategy by file type:**

**Committed file (`~/Desktop/baker-code/.claude/settings.json`):** keep V0.2 §B symlink approach. The file is committed in baker-master; the symlink path `~/.baker-hooks/...` is stable on this Mac (the only machine that runs this picker). Symlink benefit (decouple from baker-code path) is realized here.

**Device-local files (`.claude/settings.local.json` on bm-aihead1, bm-aihead2, bm-b1..b5):** drop the symlink. Use the direct absolute path:

```json
{
  "type": "command",
  "command": "python3 /Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py",
  "timeout": 30
}
```

Rationale:
1. `settings.local.json` is `.gitignore`'d AND device-local by Claude Code convention. It's NEVER cross-machine; the symlink-portability argument doesn't apply.
2. If Director moves baker-code on this Mac, all 7 device-local files break — but so does the committed file (which has the symlink). Symlink protects the committed file; device-local files have no advantage from the symlink layer.
3. Direct absolute path eliminates the missing-symlink failure mode entirely. The script's own `sys.exit(0)` safety net always fires because Python always starts.
4. bm-aihead1 Dropbox-sync footgun (V0.2 §C) is partially mitigated: if a second Dropbox-synced device opens this picker, the absolute path `/Users/dimitry/Desktop/baker-code/...` resolves only on Director's MacBook. Other devices: **[V0.4 ASSUMED — NOT verified against Claude Code docs]** `sh: command not found` → claude-code logs warning + skips hook → no terminal-startup hazard, no latency cliff (no HTTPS calls fired). Still surface to Director as Q1 (V0.2 §C decision pending). **V0.4 — DO NOT treat as confirmed mitigation until either: (a) Claude Code documentation cited proving silent-skip on missing hook binary, OR (b) AH1 tests on a machine without `/Users/dimitry/Desktop/baker-code/` mounted and observes claude-code session opens normally.** If neither verified before F2 execution, scope wire to ONLY this Mac (`Desktop/baker-code/.claude/settings.json` only) and skip Dropbox-synced bm-aihead1.

**Updated AC A9:**
| **A9** | `~/.baker-hooks/user-prompt-submit-confirm.py` symlink exists; `~/Desktop/baker-code/.claude/settings.json` references it | `ls -la ~/.baker-hooks/` + grep settings.json |

**New AC A13 (V0.4: SUPERSEDED by §L A13 — broader scope: covers BOTH file types in one row, not just settings.local.json):**
~~| **A13** | All `settings.local.json` files reference the direct absolute path (NOT `~/.baker-hooks/...`) | grep — must show `/Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py` |~~

## Amendment §K — MEDIUM: drop speculative grep; smoke-test direct path

**Reviewer finding (MEDIUM, confidence high):** V0.2 §F's `grep -rE "user-prompt-submit-confirm|UserPromptSubmit" ~/.claude/cache/` is speculative — Claude Code's hook execution log location is undocumented and may not exist at that path. The verification provides false confidence (grep returns empty → assumed "no fire" → false alarm) or false negative (grep finds stale cache → assumed "fire" → real failure missed).

**Action — replace V0.2 Amendment §F + Sequencing 0c with explicit pre-wire smoke test on BOTH paths:**

Replace V0.2 Sequencing §0c with:

> **0c (NEW — REVISED).** Pre-wire smoke test BOTH the symlink path AND the direct absolute path:
>
> ```bash
> echo "Test 1: symlink path"
> python3 ~/.baker-hooks/user-prompt-submit-confirm.py < /dev/null
> echo "exit:$?"
> # Expect: exit:0 (clean exit on empty stdin)
>
> echo "Test 2: direct absolute path"
> python3 /Users/dimitry/Desktop/baker-code/.claude/hooks/user-prompt-submit-confirm.py < /dev/null
> echo "exit:$?"
> # Expect: exit:0
> ```
>
> If either test returns non-zero, STOP — fix before wiring. If symlink test fails (Test 1) but direct test passes (Test 2), the symlink is broken — re-create it per Sequencing 0a before continuing.
>
> **CAVEAT (V0.4):** Both smoke tests above hit the hook's early-exit guards (e.g., `BRISEN_LAB_V2_ENABLED` check at hook source line ~50, or non-auth-bearing-role early return). A clean exit:0 proves ONLY: (a) file is present at the path, (b) Python interpreter starts, (c) script parses without `SyntaxError`. It does NOT exercise `register-session-pubkey`, `human-confirmation`, or drain. **Live test (Render log 200 trio) is the ONLY authoritative functional pass signal.** Treat smoke test as pre-flight, not as functional verification.

Replace V0.2 Amendment §F (hook-load verification) with the live-test signal as the AUTHORITATIVE pass:

> **Hook-load verification (replaces V0.2 §F):**
>
> Authoritative pass signal = Render brisen-lab daemon log shows `POST /auth/register-session-pubkey 200` AND `POST /auth/human-confirmation 200` within ~5s of submitting the literal `hello` prompt in a fresh `aihead1` session.
>
> ```bash
> # Live-test signal — tail Render brisen-lab logs filtered for the auth chain endpoints:
> # (use Render dashboard log stream or mcp__render__list_logs filtered by serviceId
> # srv-d7q7kvlckfvc739l2e8g, path=/auth/register-session-pubkey, last 60s)
> ```
>
> Pre-wire smoke test (above) catches silent failures (malformed JSON, missing file, broken symlink) before live-test. Live-test catches wired-but-not-firing failures (settings.json structure wrong, hook timeout too low, env var missing).
>
> The speculative `grep ~/.claude/cache/` step from V0.2 §F is REMOVED — that path is undocumented and unreliable.

## Amendment §L — Updated Acceptance Criteria deltas

**Replaced:**
- A12: "Live test success-path timing < 1s wall-clock" — kept; Render log timestamps measure this.

**New:**
| **A13a** | Committed file (`~/Desktop/baker-code/.claude/settings.json`) references symlink path | `grep -l "baker-hooks" ~/Desktop/baker-code/.claude/settings.json` must return the file path |
| **A13b** | Device-local files (`~/bm-*/.claude/settings.local.json`) do NOT reference symlink path | `grep -rL "baker-hooks" ~/bm-*/.claude/settings.local.json` must return empty (zero files use the symlink path) |
| **A14** | Pre-wire smoke test (Sequencing 0c REVISED) returns exit:0 for BOTH paths | command output captured in actions log |

**Removed:**
- V0.2 §F's `grep ~/.claude/cache/` step is DROPPED. No corresponding AC.

## Amendment §M — Net effect summary

- **Symlink-missing-on-device HIGH fix:** committed file uses symlink; device-local files use direct absolute path. Eliminates the OS-level `sh: no such file` SIGKILL-equivalent hazard for `settings.local.json` paths.
- **Speculative grep MEDIUM fix:** dropped `~/.claude/cache/` grep; pre-wire smoke test on BOTH paths is the authoritative pre-live signal; Render log 200 trio is the authoritative live signal.
- **Brief intent (activate H7 auth chain + Surface 5 inbox drain) preserved.**

**End V0.3 amendment.**
