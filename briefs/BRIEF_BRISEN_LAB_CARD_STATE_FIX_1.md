---
brief: BRISEN_LAB_CARD_STATE_FIX_1
status: DRAFT
trigger_class: TIER_B_FRONTEND_PLUS_DAEMON_LOGIC
author: ai-head-1 (AH1)
authored_at: 2026-05-13
target: b3
working_branch_baker_master: b3/brisen-lab-card-state-fix-1
working_branch_brisen_lab: b3/brisen-lab-card-state-fix-1
expected_pr_count: 2 (1 in brisen-lab, 1 in baker-master)
estimated_time: ~2-3h
complexity: low-medium
prerequisites:
  - PR #12 (BRISEN_LAB_CARD_UX_CLEANUP_1) merged on brisen-lab (commit b612489) ✓
  - PR #188 (BRISEN_LAB_FORGE_PUSH_FOLD_1) merged on baker-master (commit 334362a) ✓
  - Forge daemon `com.baker.forge-snapshot-push` running on Mac Mini ✓
hard_ship_gate: literal pytest/bash test output for both `tests/test_forge_snapshot_push.sh` (extended) and any brisen-lab JS tests; manual Mac Mini reinstall + visual reveal of all 6 cards showing truthful state
gates_required:
  - AH2 /security-review (both PRs, but diff is low-perimeter)
  - picker-architect (both PRs)
  - feature-dev:code-reviewer 2nd-pass — OPTIONAL (Tier-B trigger #7 judgment call: low-stakes UX fix, no auth/DB/external surface; AH1 will skip unless ambiguity surfaces during review)
---

# BRIEF: BRISEN_LAB_CARD_STATE_FIX_1 — Fold-fix for 3 post-deploy card-state bugs

## Context

PR #12 (BRISEN_LAB_CARD_UX_CLEANUP_1, merged 2026-05-12) shipped the glance-readable card UX. On Director's post-deploy reveal (2026-05-12 ~22:50Z), three real bugs surfaced: card colours and "Dispatch waiting" text are lying about actual terminal state. Director directive same evening: do NOT clean stale mailbox files; proper fold-fix tomorrow.

This brief packages the three fixes. Source-of-truth: `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/session_handover_2026-05-12_night_aihead_a_brisen_lab_glance_ux_dispatch.md` § "Top open question for Director".

## Estimated time: ~2-3h
## Complexity: low-medium
## Prerequisites: see frontmatter.

---

## Fix 1: Worktree-aware daemon (per-alias multi-clone candidates)

### Problem

The forge daemon's `TERMINALS` array maps each b-code to a single clone path (`b2 → /Users/dimitry/bm-b2`, the baker-master clone). But b-codes frequently work in a sibling repo (`~/bm-b2-brisen-lab` for brisen-lab work). The daemon reads git state + mailbox from the wrong clone, surfacing stale baker-master state instead of the live brisen-lab work.

**Director-observed anchor (2026-05-12):** b2's card surfaced `cockpit-legacy-slug` branch + baker-master stale state, while b2 had just shipped PR #12 from `b2/brisen-lab-card-ux-cleanup-1` in `~/bm-b2-brisen-lab`. Worktree-blindness.

### Current State

`scripts/forge_snapshot_push.sh:20-27` — single path per alias:

```bash
declare -a TERMINALS=(
  "lead:/Users/dimitry/Desktop/baker-code"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1"
  "b2:/Users/dimitry/bm-b2"
  "b3:/Users/dimitry/bm-b3"
  "b4:/Users/dimitry/bm-b4"
)
```

`snapshot_one()` at line 38 takes a single repo path; reads `git -C "$repo"` + `briefs/_tasks/CODE_N_PENDING.md` from that one clone only.

### Implementation

**1.1** Change `TERMINALS` entries to comma-separated candidate paths per alias. b-codes get two candidates (baker-master + brisen-lab); lead/deputy stay single-path:

```bash
declare -a TERMINALS=(
  "lead:/Users/dimitry/Desktop/baker-code"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab"
  "b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab"
  "b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab"
  "b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab"
)
```

**1.2** Add a `pick_active_clone()` function that takes alias + comma-separated paths, returns the single best repo path. Scoring priority (highest wins; missing or non-git clones get score 0 and are skipped):

| Signal | Score | Why |
|---|---|---|
| Local branch has open PR on origin | 1000 | Definitive "this is where the live work is" |
| `briefs/_tasks/CODE_N_PENDING.md` exists | 100 | Pending dispatch = active focus |
| Most-recent commit timestamp (unix epoch / 1e6) | <0.001 per epoch tick | Tiebreaker only |

Implementation sketch (bash, integrate with existing `PR_LOOKUP_ENABLED` guard so tests can skip the `gh pr list` call):

```bash
pick_active_clone() {
  # ALL state vars are declared local — bash function scope. Reviewer-flagged
  # 2026-05-13: without `local`, best_ts/best_score persist across alias calls
  # and corrupt tiebreaker logic on aliases 2+.
  local alias="$1"
  local paths_csv="$2"
  local n=""
  local best_path=""
  local best_score=-1
  local best_ts=0
  local repo score branch remote_url repo_slug pr_count last_commit_ts

  if [[ "$alias" =~ ^b([1-9])$ ]]; then
    n="${BASH_REMATCH[1]}"
  fi

  # Run the split + scoring inside a subshell so IFS mutation cannot leak into
  # the caller. Subshell echoes the winning path on stdout. Reviewer-flagged
  # 2026-05-13: empty paths_csv would skip the unset IFS at loop end, leaking
  # IFS=',' to the rest of the script.
  best_path="$(
    IFS=','
    set -- $paths_csv  # word-split paths_csv into positional args using ',' as IFS
    local inner_best_path=""
    local inner_best_score=-1
    local inner_best_ts=0
    for repo in "$@"; do
      [[ -d "$repo/.git" ]] || continue
      score=0

      # Pending mailbox (b-codes only)
      if [[ -n "$n" && -f "$repo/briefs/_tasks/CODE_${n}_PENDING.md" ]]; then
        score=$((score + 100))
      fi

      # Open PR on current branch (skip in test mode)
      if [[ "$PR_LOOKUP_ENABLED" == "1" ]]; then
        branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
        if [[ -n "$branch" && "$branch" != "main" && "$branch" != "master" ]]; then
          remote_url="$(git -C "$repo" remote get-url origin 2>/dev/null || echo '')"
          repo_slug="$(echo "$remote_url" | sed -E 's#.*github\.com[:/]##; s#\.git$##')"
          if [[ -n "$repo_slug" ]]; then
            pr_count="$(gh pr list --repo "$repo_slug" --head "$branch" --state open --json number --limit 1 2>/dev/null \
              | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d))' 2>/dev/null || echo '0')"
            if [[ "$pr_count" -ge 1 ]]; then
              score=$((score + 1000))
            fi
          fi
        fi
      fi

      # Tiebreaker: most-recent commit timestamp (unix epoch — integer only).
      last_commit_ts="$(git -C "$repo" log -1 --format='%ct' 2>/dev/null || echo '0')"

      if [[ "$score" -gt "$inner_best_score" ]] \
         || { [[ "$score" -eq "$inner_best_score" ]] && [[ "$last_commit_ts" -gt "$inner_best_ts" ]]; }; then
        inner_best_score="$score"
        inner_best_ts="$last_commit_ts"
        inner_best_path="$repo"
      fi
    done
    echo "$inner_best_path"
  )"

  # If subshell returned empty (no clones with .git, or empty paths_csv), fall
  # back to first candidate so the daemon still produces a snapshot row.
  if [[ -z "$best_path" ]]; then
    best_path="${paths_csv%%,*}"
  fi
  echo "$best_path"
}
```

**Reviewer-folded notes (2026-05-13):**
- All state vars now `local`. Subshell isolation prevents IFS leak even on empty `paths_csv`. Subshell's `inner_best_*` vars die with the subshell.
- The `if-then-or` test syntax uses `{ ...; }` group (not subshell) so the short-circuit works without spawning yet another subshell per loop iteration.

**1.3** In the main iteration loop (`scripts/forge_snapshot_push.sh:142-146`), call `pick_active_clone` before `snapshot_one`:

```bash
for entry in "${TERMINALS[@]}"; do
  alias="${entry%%:*}"
  paths_csv="${entry#*:}"
  repo="$(pick_active_clone "$alias" "$paths_csv")"
  snapshot_one "$alias" "$repo" || true
done
```

**1.4** Update `TERMINALS_OVERRIDE` parser at lines 31-33 — it's space-separated and shouldn't change format. But each space-separated entry can now have a comma-separated tail; existing single-path overrides still work (no comma → single candidate). Verify by running the existing test fixture against the new code (should still pass unchanged).

### Key Constraints

- **Do NOT** require sibling clones to exist. b3 hasn't cloned brisen-lab at `~/bm-b3-brisen-lab`; the daemon must silently skip missing clones and pick the existing one. Missing-clone path returns score 0 and is excluded from `best_path` selection.
- **Do NOT** add a network dependency that breaks the daemon if `gh` is missing or unauthenticated. Existing code at lines 77-89 already swallows `gh pr list` errors via `|| echo '[]'`; preserve that.
- **Do NOT** change the snapshot payload schema — `terminal_alias` still maps 1:1 to one row in `forge_snapshots`. The change is which clone the daemon reads, not what it writes.
- **Cost discipline:** `gh pr list` runs once per *candidate clone* now (was: once per alias). With 4 b-codes × 2 candidates + 2 single-path = 10 calls per 30s cycle. GitHub API rate is 5000/hr authenticated; we'd hit 1200/hr — well under. No batching needed.

### Verification

```bash
# Run the extended test (see Fix 4 below)
cd /Users/dimitry/bm-aihead1
bash tests/test_forge_snapshot_push.sh
# Expected: PASS lines for all sub-cases (existing + new)
```

Then on Mac Mini after install reload, observe live cards:
- b2 card should show brisen-lab work (matching `~/bm-b2-brisen-lab` state) instead of baker-master.
- If a b-code has no brisen-lab clone, card surfaces baker-master state (unchanged behavior).

---

## Fix 2: cardState() heuristic uses open_pr_number + mailbox_status as primary signals

### Problem

`static/app.js:89-106` `cardState()` uses *branch name* as a primary signal for "yellow = building":

```javascript
if (snap.mailbox_status === "pending") {
  const branch = (snap.git_branch || "").toLowerCase();
  if (branch && branch !== "main" && branch !== "master") return "yellow";
  return "red";
}
```

This fires off the local branch even after the PR has merged — b1's STOP_HOOKS PR #186 merged hours ago, but b1's local clone still on `b1/stop-hooks-...` → card stays yellow indefinitely. The heuristic ignores merge state and ignores open-PR existence.

### Current State

- Snapshot already includes `open_pr_number` (see `app.py:344-347` POST handler; column in `db.py:119` `forge_snapshots`; SELECT in `/api/state` at `app.py:362-368`).
- Frontend already receives `state.snapshots[alias].open_pr_number` (initial paint at line 466; live SSE at line 375).
- Currently the heuristic doesn't read it.

### Implementation

**2.1** Rewrite `cardState()` at `static/app.js:89-106` with priority-ordered rules:

```javascript
function cardState(snap) {
  if (!snap || snap.mailbox_status == null || snap.mailbox_status === "n/a") {
    return "grey";
  }
  // GREEN takes precedence: just shipped (mailbox flipped to complete by AH1).
  if (snap.mailbox_status === "complete") {
    if (snap.daemon_last_seen) {
      const ageMs = Date.now() - new Date(snap.daemon_last_seen).getTime();
      if (!Number.isNaN(ageMs) && ageMs < GREEN_WINDOW_MS) return "green";
    }
    return "grey";
  }
  // YELLOW (PR open): work is in review regardless of local branch / merge state.
  if (snap.open_pr_number != null) return "yellow";
  // YELLOW (building, no PR yet): mailbox pending + on a feature branch.
  if (snap.mailbox_status === "pending") {
    const branch = (snap.git_branch || "").toLowerCase();
    if (branch && branch !== "main" && branch !== "master") return "yellow";
    return "red";  // pending dispatch, on main, no PR — unstarted
  }
  return "grey";
}
```

**2.2** Update the subject-line at `static/app.js:160-169` so yellow-with-PR says `"PR #N: <pr_title>"` instead of `"Working at: <branch>"`. Yellow-without-PR keeps the existing "Working at" text. Architect-folded 2026-05-13: green-with-no-PR gets a distinct label `"Shipped (no PR): <subject>"` to make the no-trail edge case readable without adding a 4th state:

```javascript
} else if (cs === "yellow") {
  if (snap.open_pr_number != null) {
    const t = String(snap.open_pr_title || "").slice(0, 80);
    line = "PR #" + snap.open_pr_number + (t ? ": " + t : "");
  } else {
    const shortBranch = shortenBranch(snap.git_branch, alias) || "(branch?)";
    line = "Working at: " + shortBranch;
  }
} else if (cs === "green") {
  const subj = String(snap.git_head_subject || "").slice(0, 80);
  const prefix = (snap.open_pr_number != null) ? "Just shipped" : "Shipped (no PR)";
  line = prefix + ": " + (subj || "(no subject)");
}
```

(The existing `else if (cs === "green")` block at lines 166-169 is replaced by the version above. The card still renders the same colour — only the subject text differs.)

**2.3** Bump cache-bust on the static asset reference in `static/index.html` to force reload on iOS PWA (Lesson: "No cache bust" anti-pattern). Open `static/index.html`, find the `<script src="app.js?v=N">` line — N is whatever the current value is (last set by PR #11/#12). Increment N by 1 and commit. Same for `styles.css` only if Fix 2 requires CSS changes (it doesn't — no CSS touched). If b3 finds N is missing or the asset reference doesn't use `?v=`, fall back to adding `?v=1` to the `app.js` reference and note the addition in the PR description.

### Key Constraints

- **Do NOT** add new fields to the snapshot payload. `open_pr_number` is already populated by the daemon (`forge_snapshot_push.sh:81-89`).
- **Do NOT** remove the 12h `GREEN_WINDOW_MS` staleness gate on green. A b-code that shipped 14h ago and never had its mailbox reset should fade to grey, not stay green forever.
- **Do NOT** change `renderCortexCard()` or `renderCoworkCard()` (lines 180-244). They don't use the `mailbox_*` schema — they have their own freshness rules.

### Verification

Manual smoke test against live dashboard after frontend PR merges + brisen-lab redeploys:

| Terminal | Snapshot state | Expected card |
|---|---|---|
| Any b-code with open PR on origin | `mailbox_status=pending`, `open_pr_number=N`, branch=feature OR main | yellow + "PR #N: ..." |
| b-code post-ship, mailbox not yet flipped | `mailbox_status=pending`, `open_pr_number=null`, branch=feature, age >12h | yellow + "Working at: ..." (acceptable — same as today; mailbox should be flipped to complete) |
| b-code mailbox=complete + daemon fresh | `mailbox_status=complete`, daemon < 12h | green + "Just shipped: ..." |
| b-code mailbox=complete + daemon stale | `mailbox_status=complete`, daemon > 12h | grey |
| b-code with no mailbox file | `mailbox_status=n/a` | grey |
| b-code freshly dispatched, no branch yet | `mailbox_status=pending`, branch=main, no PR | red + "Dispatch waiting: ..." |

If feasible, add a small JS unit test for `cardState()` covering the 6 cases above. If brisen-lab has no JS test harness today, document the manual checklist in a comment block above `cardState()` and skip the unit test.

---

## Fix 3: mailbox_brief_name parser handles YAML frontmatter

### Problem

`scripts/forge_snapshot_push.sh:64,68` extracts the brief name with `head -1 "$pending" | sed 's/^# *//'`. When the mailbox file starts with YAML frontmatter (Director's standard brief format begins with `---`), the first line is `---`, and after `sed 's/^# *//'` it stays `---`. Card shows "Dispatch waiting: ---".

**Director-observed anchor (2026-05-12):** b4 card showed "Dispatch waiting: ---" because `~/bm-b4/briefs/_tasks/CODE_4_PENDING.md` (real dispatch: CODEX_JUDGE_INTEGRATION_IMPL_1) starts with `---` YAML.

### Current State

Two call sites in `scripts/forge_snapshot_push.sh`:
- Line 64: `mailbox_brief_name="$(head -1 "$pending" | sed 's/^# *//' | head -c 200)"`
- Line 68: `mailbox_brief_name="$(head -1 "$complete" | sed 's/^# *//' | head -c 200)"`

Brief file format today (mixed in the wild):
1. **YAML frontmatter style** (e.g., `~/bm-b4/briefs/_tasks/CODE_4_PENDING.md`):
   ```yaml
   ---
   status: PENDING
   brief: ~/baker-vault/_ops/briefs/CODEX_JUDGE_INTEGRATION_IMPL_1.md
   ...
   ---
   ```
2. **Markdown heading style** (test fixture uses this):
   ```markdown
   # CODE_9_PENDING — TEST_BRIEF_FORGE_PUSH_FOLD
   ```

### Implementation

**3.1** Add a helper function `extract_brief_name()` that takes a file path and returns up to 200 chars of brief name, with three-step fallback:

```bash
extract_brief_name() {
  local f="$1"
  [[ -f "$f" ]] || { echo ""; return; }

  # Step 1: YAML frontmatter `brief:` field (between first --- and second ---).
  # awk: count '---' lines; while in block (c==1), match brief: lines.
  # Reviewer-folded 2026-05-13: regex is `[[:space:]]*` (zero-or-more) so we
  # accept `brief:value` (no space, valid minimal YAML) as well as `brief: value`
  # and `brief:\tvalue`. The brief's edge-case note claimed this; the original
  # `[[:space:]]` (exactly one) contradicted it.
  local brief_line
  brief_line="$(awk 'BEGIN{c=0} /^---$/{c++; if(c==2) exit; next} c==1 && /^brief:[[:space:]]*/{print; exit}' "$f" 2>/dev/null \
    | sed -E 's/^brief:[[:space:]]*//; s/[[:space:]]*$//' \
    | head -1)"
  if [[ -n "$brief_line" ]]; then
    # Strip directory prefix + .md suffix, take basename.
    local base
    base="$(basename "${brief_line%.md}")"
    echo "$base" | head -c 200
    return
  fi

  # Step 2: first '# ' heading anywhere in file.
  local heading
  heading="$(grep -m1 '^# ' "$f" 2>/dev/null | sed 's/^# *//' | head -c 200)"
  if [[ -n "$heading" ]]; then
    echo "$heading"
    return
  fi

  # Step 3: explicit failure marker. Architect-folded 2026-05-13: returning
  # the filename slug (e.g. `CODE_4_PENDING`) is noise — every b-code file is
  # named that, surfacing it again next to the terminal alias adds zero
  # information. `(unparseable)` makes the failure mode unambiguous to a card
  # reader and signals "fix the brief file or the parser".
  echo "(unparseable)"
}
```

**3.2** Replace both call sites:

```bash
# Line 64:
mailbox_brief_name="$(extract_brief_name "$pending")"
# Line 68:
mailbox_brief_name="$(extract_brief_name "$complete")"
```

### Key Constraints

- **Do NOT** change the snapshot schema — `mailbox_brief_name` remains a free-form string ≤200 chars.
- **Do NOT** require a specific brief file format on disk. The parser must accept both styles; future changes to brief format must not break the daemon.
- **Edge case — empty file:** awk returns empty, grep returns empty, basename fallback returns `CODE_4_PENDING` (the filename minus `.md`). Acceptable degraded state — far better than `---`.
- **Edge case — frontmatter with no `brief:` key:** awk returns empty → falls through to step 2; if no `# ` heading exists either → falls through to step 3 (filename slug). Acceptable.
- **Edge case — multi-line YAML value or `brief:` with no leading space:** the `[[:space:]]` matcher in awk handles tab/space; the `sed -E` strips trailing whitespace. Multi-line YAML values (unusual for `brief:`) lose the continuation — acceptable, we just want the first line.

### Verification

Manual smoke against three real brief files (and the test in Fix 4 covers automated regression):

```bash
# Frontmatter style — current b4 file.
bash -c 'source <(declare -f extract_brief_name <(cat scripts/forge_snapshot_push.sh)); extract_brief_name ~/bm-b4/briefs/_tasks/CODE_4_PENDING.md'
# Expected: CODEX_JUDGE_INTEGRATION_IMPL_1

# Heading style — what the existing test fixture uses.
echo "# CODE_9_PENDING — TEST_BRIEF" > /tmp/test1.md
extract_brief_name /tmp/test1.md
# Expected: CODE_9_PENDING — TEST_BRIEF

# Empty file fallback.
touch /tmp/test2.md
extract_brief_name /tmp/test2.md
# Expected: test2
```

(Exact extraction-call syntax in real environment will differ; the test harness in Fix 4 is the authoritative verification path.)

---

## Fix 3b: flock guard against overlapping daemon runs (architect-folded 2026-05-13)

### Problem

The daemon runs every 30s via launchd. If a single run takes longer than 30s (worst case: 10 candidate clones × `gh pr list` calls + 6 git rev-parse calls), launchd will spawn a second instance while the first is still running. Two daemons doing per-cycle `gh pr list` calls double the rate against the GitHub API and can race on the curl POST → snapshot duplication (UPSERT is safe, but events are noisy).

This is a pre-existing latent risk in the daemon, NOT a regression from Fixes 1-3. But Fix 1 grows per-cycle work from "1 gh call per b-code-on-feature-branch" (≤4) to "1 gh call per candidate clone where branch != main" (≤10). Architect flagged this 2026-05-13 as the single structural production risk worth addressing in the same fold.

### Current State

`scripts/forge_snapshot_push.sh` runs unguarded. The launchd plist (`scripts/launchd/com.baker.forge-snapshot-push.plist`) has `StartInterval: 30` which launchd interprets as "if previous run still running at 30s mark, launch another instance anyway."

### Implementation

**3b.1** Wrap the entire body of `scripts/forge_snapshot_push.sh` in a `flock` advisory-lock guard. Add immediately after the `if [[ -z "$FORGE_KEY" ]]` block (around line 17):

```bash
# Single-instance guard. If a previous invocation is still running (e.g. on a
# slow network cycle), the new instance exits silently. Architect-flagged
# 2026-05-13: per-cycle gh pr list count grew with multi-clone snapshots;
# launchd will respawn at 30s even if previous instance hasn't finished, so
# without this guard two daemons can run concurrently.
LOCK_FILE="${LOCK_FILE:-/tmp/forge_snapshot_push.lock}"
exec 200>"$LOCK_FILE" || { echo "[forge-push] FATAL: cannot open lock file $LOCK_FILE" >&2; exit 2; }
if ! flock -n 200; then
  # Another instance holds the lock — exit cleanly so launchd doesn't back off.
  echo "[forge-push] another instance is running; exiting" >&2
  exit 0
fi
# Lock is held for the lifetime of this shell; released automatically on exit.
```

(macOS's `flock` is provided by `util-linux` or Homebrew's `flock`; if not present on the Mac Mini, the equivalent is `lockfile-create` from procmail-tools or a hand-rolled `mkdir`-based mutex. Verify which is installed before specifying — the daemon already runs on Mac Mini today; b3 confirms before final commit.)

### Key Constraints

- **Exit 0, not non-zero**, when another instance holds the lock. Launchd interprets non-zero exit as a crash and may back off the daemon entirely.
- **Lock file at `/tmp/...`**, not the repo. Survives across daemon restarts; cleared on Mac Mini reboot.
- **Do NOT** add the lock to the test harness — tests run synchronously, no concurrency risk. Test invocation already uses `bash "$SCRIPT"` directly; the lock will be acquired and released within the single test run.

### Verification

Manual smoke on Mac Mini after install:

```bash
# Start two daemon invocations in parallel; only one should produce output.
bash ~/Library/Application\ Support/baker/forge_snapshot_push.sh &
bash ~/Library/Application\ Support/baker/forge_snapshot_push.sh &
wait
# Expected: one normal run, one "[forge-push] another instance is running; exiting" stderr line.
```

---

## Fix 4: Test coverage — YAML frontmatter fixture + worktree-scoring fixture

### Problem

`tests/test_forge_snapshot_push.sh` covers the legacy `# CODE_N_PENDING` heading-style mailbox and a single-clone TERMINALS layout. Fixes 1 + 3 introduce new behaviors that the existing test doesn't exercise.

### Current State

`tests/test_forge_snapshot_push.sh:1-59` — single fixture: one fake b9 repo, heading-style mailbox, `TERMINALS_OVERRIDE="b9:$FAKE_REPO"`, asserts the script processed b9 and skipped production aliases.

### Implementation

**4.1** Extend the test to add two additional cases without rewriting the existing one. Either (a) extend the current script with three sequential fixture-runs, or (b) split into three test files. Prefer (a) for fewer files.

**Case A** (existing): heading-style mailbox, single clone. Keep as-is.

**Case B** (new): YAML frontmatter mailbox. Build a fake b9 with `CODE_9_PENDING.md` containing:

```yaml
---
status: PENDING
brief: ~/baker-vault/_ops/briefs/FAKE_FRONTMATTER_BRIEF_1.md
---
# CODE_9_PENDING — should NOT be extracted because frontmatter wins
```

Assert (via inspection of the daemon's POST body or — since the test doesn't actually POST — by adding a `DEBUG_DUMP_PAYLOAD=1` env-var path in the daemon that prints the JSON payload to stderr when set) that `mailbox_brief_name` extracts to `FAKE_FRONTMATTER_BRIEF_1`.

**Case C** (new): two candidate clones for one alias, only one has a pending mailbox. Build `FAKE_REPO_A` (no mailbox, recent commit) + `FAKE_REPO_B` (pending mailbox, older commit). Set `TERMINALS_OVERRIDE="b9:$FAKE_REPO_A,$FAKE_REPO_B"`. Assert the daemon picked `FAKE_REPO_B` (pending mailbox scores 100, beats recency tiebreaker).

**Case D** (new, required): two candidate clones, neither has a mailbox; one has a more-recent commit. Assert the daemon picked the more-recent one. This locks down the tiebreaker behavior so future refactors don't silently regress it.

**Case E** (new, required — reviewer-folded 2026-05-13): two candidate paths, NEITHER is a git repo (e.g. empty placeholder directories). Assert the daemon falls back to the first candidate path AND still produces a snapshot row (downstream UI shows grey). This locks down the empty-`paths_csv` / no-`.git` edge case that exposed the IFS-leak bug during reviewer pass.

**4.2** Add a `DEBUG_DUMP_PAYLOAD` hook in `scripts/forge_snapshot_push.sh:121-126` (inside the `payload` capture block):

```bash
if [[ "${DEBUG_DUMP_PAYLOAD:-0}" == "1" ]]; then
  echo "PAYLOAD_DUMP:$payload" >&2
fi
```

The test asserts on stderr containing `PAYLOAD_DUMP:` lines with the expected JSON fields. Use `python3 -c 'import json,sys; ...'` for JSON-aware assertions (not raw grep — the field order isn't guaranteed).

### Key Constraints

- **Do NOT** make the test POST to a real endpoint. Keep `LAB_URL="http://127.0.0.1:1"` so curl exits 000 — we are validating state-collection, not HTTP transport.
- **Do NOT** require `gh` to be installed/authenticated in the test environment. Keep `PR_LOOKUP_ENABLED=0` for all cases — open-PR scoring is exercised via the live daemon, not unit tests.
- **DO** preserve the existing assertion that production aliases (lead/deputy/b1-b4) are NOT processed when TERMINALS_OVERRIDE is set.

### Verification

```bash
cd /Users/dimitry/bm-b3 && git checkout b3/brisen-lab-card-state-fix-1
bash tests/test_forge_snapshot_push.sh
# Expected output (exact format may vary, must include):
#   PASS: Case A — heading-style mailbox
#   PASS: Case B — YAML frontmatter mailbox extracts brief: field
#   PASS: Case C — two-clone alias picks pending-mailbox clone
#   PASS: Case D — two-clone alias falls back to recency tiebreaker
#   PASS: Case E — two non-git candidate paths fall back to first; daemon still POSTs
#   (script exit code 0)
```

This is the **literal pytest/bash output** required for ship-gate. No "by inspection" allowed.

---

## Files Modified

### Repo: vallen300-bit/baker-master (working in `~/bm-b3`)

- `scripts/forge_snapshot_push.sh` — Fix 1 (`TERMINALS` multi-path + `pick_active_clone()` + main-loop swap) + Fix 3 (`extract_brief_name()` + two call-site replacements) + Fix 3b (`flock` single-instance guard) + Fix 4.2 (`DEBUG_DUMP_PAYLOAD` hook)
- `tests/test_forge_snapshot_push.sh` — Fix 4.1 (Cases B + C + D added; Case A preserved)

### Repo: vallen300-bit/brisen-lab (working in `~/bm-b3-brisen-lab` — needs initial clone)

- `static/app.js` — Fix 2 (`cardState()` rewrite + subject-line PR-aware update)
- `static/index.html` — Fix 2.3 (cache-bust bump on `app.js?v=N`)

## Do NOT Touch

- `scripts/launchd/com.baker.forge-snapshot-push.plist` — daemon scheduling; no change.
- `scripts/install_forge_push.sh` — installer; the new comma-separated TERMINALS list is embedded inside `forge_snapshot_push.sh` which the installer already deploys verbatim. No installer edit needed.
- `app.py` (brisen-lab) `/api/snapshot` POST handler at lines 317-351 — schema unchanged.
- `db.py` (brisen-lab) `forge_snapshots` schema at lines 110-123 — no migration.
- `static/styles.css` (brisen-lab) — no CSS change required (Fix 2 is logic-only; colour mapping by `data-card-state` attribute already covers red/yellow/green/grey).
- `app.js` (brisen-lab) `renderCortexCard()` + `renderCoworkCard()` (lines 180-244) — different data sources, different rules; out of scope.
- Any baker-vault files — this brief is code-only.

## Quality Checkpoints

1. **Both PRs ship green CI** — literal `pytest` or `bash tests/test_forge_snapshot_push.sh` output in PR description.
2. **Mac Mini daemon reinstall + visual reveal** — after baker-master PR merges, AH1 runs `bash scripts/install_forge_push.sh` from Mac Mini, then opens https://brisen-lab.onrender.com and confirms all 6 cards show truthful state:
   - b2 card surfaces its brisen-lab work (when present).
   - b1 card is green/grey (not yellow) after PR merge if mailbox flipped.
   - b4 card shows real brief name (not `---`).
3. **No regressions on cards already correct today** — lead, deputy, b3 (post-ship green) should be unchanged. Take a screenshot pre-deploy, compare post-deploy.
4. **GitHub API budget verified** — 30s daemon cadence × 10 candidate clones × 12 cycles/hour = 1200 `gh pr list` calls/hour. Should stay well under 5000/hr authenticated limit. AH1 spot-checks `gh api rate_limit` after 1h of live running.
5. **Mailbox file housekeeping is NOT part of this brief** — Director directive 2026-05-12 22:50Z ("no use now to clean"). Stale `CODE_N_PENDING.md` cleanup is separate; AH1 sweeps manually if needed after this brief ships.

## Verification SQL

After the daemon redeploys, observe the live data in Render Postgres:

```sql
-- All 6 terminal aliases have fresh snapshots.
SELECT terminal_alias, git_branch, mailbox_status, mailbox_brief_name,
       open_pr_number, daemon_last_seen
FROM forge_snapshots
ORDER BY terminal_alias;

-- Sanity: no NULL mailbox_brief_name on b-codes with pending mailbox (Fix 3 should
-- have replaced any "---" extraction with a real name or filename slug).
SELECT terminal_alias, mailbox_status, mailbox_brief_name
FROM forge_snapshots
WHERE terminal_alias LIKE 'b%' AND mailbox_status = 'pending';
-- Expected: mailbox_brief_name is a recognizable brief name or filename, never "---".
```

## Risks + Lessons Applied

- **Lesson #325 (forge-agent `--bm-b1` double-dash):** string-encoding edge case in path construction. Mitigation: explicit bash array of candidate paths, no automated path-mangling.
- **Lesson #339 (YAML version typing in roadmap renderer):** YAML scalar parsing surprises. Mitigation: the awk parser in Fix 3.1 treats the `brief:` value as a string and strips with `sed -E`; doesn't rely on YAML type-coercion.
- **Lesson "No cache bust" (general):** Fix 2.3 bumps `?v=N` to ensure iOS PWA reloads.
- **Lesson "Untracked briefs":** AH1 commits `briefs/BRIEF_BRISEN_LAB_CARD_STATE_FIX_1.md` + `briefs/_tasks/CODE_3_PENDING.md` to baker-master `main` at dispatch time.

## Review Chain Folded (pre-dispatch, 2026-05-13)

| Pass | Severity | Fix | Status |
|---|---|---|---|
| Reviewer #1 | HIGH | IFS leak into outer scope when `paths_csv` empty | Folded → subshell isolation in `pick_active_clone()` |
| Reviewer #3 | HIGH | `best_path`/`best_score`/`best_ts` not `local`, polluted across alias calls | Folded → explicit `local` declarations + subshell |
| Reviewer #2 | MEDIUM | awk regex `[[:space:]]` (exactly-one) contradicted brief's "edge case handled" claim | Folded → regex changed to `[[:space:]]*` |
| Reviewer #4 | LOW | Cache-bust instruction underspecified | Folded → added "if missing, add `?v=1`" fallback |
| Reviewer #5 | LOW | No explicit test case for non-git candidate paths | Folded → Case E added (required) |
| Architect Item 2 | SIGNIFICANT | API storm risk on daemon overlap | Folded → Fix 3b (`flock` single-instance guard) |
| Architect Item 3 | SIGNIFICANT | Green-no-PR card identical to green-with-PR | Folded → `"Shipped (no PR)"` distinct label in Fix 2.2 |
| Architect Item 3 minor | MINOR | Filename slug fallback returns useless `CODE_4_PENDING` | Folded → `"(unparseable)"` explicit marker in Fix 3.1 |

Items NOT folded (intentionally):
- Architect Item 1 (multi-row schema): scope expansion + UI refactor; rejected.
- Architect Item 5 (PR sequencing): no risk — both orders safe; ship either.
- Architect Item 6 (builder choice): confirmed b3.

## Builder Choice — b3

| Signal | b3 score | b2 score |
|---|---|---|
| Daemon source familiarity (Fix 1 + 3) | Built it (PR #187/#188) | Reviewed only |
| `cardState()` familiarity (Fix 2) | Saw it in PR #188 review chain | Built it (PR #12) |
| Test harness familiarity | Wrote `tests/test_forge_snapshot_push.sh` | None |
| Cross-repo experience | High (forge-agent + lab + master) | Medium |
| Currently idle | Yes (post PR #188 ship) | b2 has Fix 5 fold open + WAHA work |

**Recommendation: b3.** Two of three fixes live in code b3 authored; b3 wrote the existing test harness so Fix 4 is incremental. b2 still has WAHA Phase 2 follow-through. Bug 2 (frontend) is small and well-specified; b3 can handle.

## Ship Gate

Both PRs must satisfy:
1. Literal `bash tests/test_forge_snapshot_push.sh` exit-0 output pasted in the baker-master PR description, all 4 cases PASS.
2. Manual smoke checklist from Fix 2 §Verification pasted in the brisen-lab PR description.
3. AH2 `/security-review` + picker-architect both PASS (or PASS-WITH-NITS folded).
4. `feature-dev:code-reviewer` 2nd-pass — skip (Trigger evaluation: no auth/DB/external/concurrency/cross-repo-state surface; #7 judgment is low-stakes). AH1 may invoke at discretion if review surfaces ambiguity.
5. No "pass by inspection" language anywhere in ship report.

## Heartbeat Cadence

12h max between heartbeats during active build. Heartbeat formats accepted: mailbox UPDATE entry, commit-msg `mailbox(b3): heartbeat <ISO>`, ship-report file. Two consecutive misses (24h) → AH1 surfaces stall to Director once.
