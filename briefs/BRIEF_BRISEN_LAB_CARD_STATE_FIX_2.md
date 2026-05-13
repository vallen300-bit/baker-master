---
brief: BRISEN_LAB_CARD_STATE_FIX_2
status: DRAFT
trigger_class: TIER_B_GLANCE_UX_PLUS_BUS_HYGIENE
author: ai-head-1 (AH1)
authored_at: 2026-05-13
target: b3
working_branch_baker_master: b3/brisen-lab-card-state-fix-2
working_branch_brisen_lab: b3/brisen-lab-card-state-fix-2
working_branch_baker_vault: b3/brisen-lab-card-state-fix-2
expected_pr_count: 3 (1 baker-master, 1 brisen-lab, 1 baker-vault — direct push on vault per CHANDA Inv 9)
estimated_time: ~3-4h
complexity: medium
prerequisites:
  - BRISEN_LAB_CARD_STATE_FIX_1 (baker-master PR #190 + brisen-lab PR #13) MERGED — frontmatter-authoritative classifier already in `scripts/forge_snapshot_push.sh:189-241`. Do NOT redo that work.
  - Render env var `BRISEN_LAB_TERMINAL_KEY` set on baker-master `srv-d6dgsbctgctc73f55730` (Tier-B flip 2026-05-13 09:55Z, AH1 actions_log) — MCP path verified live.
  - DEADLINE_MATTER_SLUG_BACKFILL_1 cleared from b3's queue (sibling dispatch at baker-master `3091f50`, b3 mailbox not yet written).
hard_ship_gate: |
  1. Literal `pytest` PASS on every new test added under each PR (no "by inspection").
  2. Manual reveal sequence (Director-facing): commit any mailbox flip → reload `https://brisen-lab.onrender.com/#production` within 60s → confirm card colour + subtitle reflect new state (no "Working at" past mailbox=complete).
  3. Manual reveal sequence (bus hygiene): dispatch a throwaway brief via `bus_post.sh` to a test terminal, run the new `ack_dispatch_msgs.sh` against the same brief slug, verify `GET /msg/<slug>` returns 0 unread for that brief's topics.
  4. Lead-counter staleness: after ack-on-ship lands, Lead's badge MUST track live bus state — verified by reload + 60s wait.
gates_required:
  - AH2 /security-review on baker-master PR (helper script touches credential path via `op` reads — perimeter)
  - picker-architect (code-architecture-reviewer) on all three PRs
  - feature-dev:code-reviewer 2nd-pass — MANDATORY per Tier-B trigger #4 (external surface: brisen-lab daemon + post-commit hooks touch all 6 B-code/AH1 clones)
mandatory_2nd_pass: TRUE
---

# BRIEF: BRISEN_LAB_CARD_STATE_FIX_2 — Three fixes for post-FIX_1 glance-UX truth drift

## Context

FIX_1 (PR #190 + brisen-lab PR #13, merged 2026-05-12) shipped the worktree-aware clone picker, frontmatter-authoritative mailbox classifier, and flock guard. Three orthogonal bugs survived FIX_1's surface and were observed live on 2026-05-13 09:00-09:40Z by Director:

1. **B4 card stayed "Working at: hard-deadline-audit-1"** for >30 min after AH1 committed mailbox(b4) → COMPLETE at `36708ff`. The frontmatter classifier is correct; the daemon reads from the local B4 clone `~/bm-b4`, which is 5 commits behind `origin/main`. Snapshot truthfully reports what its source-of-truth says — but its source-of-truth lags reality.
2. **Lead card showed "3 unread / 602m"** while direct daemon query `GET /msg/lead` (with lead's 1Password terminal key) returned 0 unread. UI badge state is captured at SSE-stream-open and only mutated by `bus_badge_change` events; nothing forces a periodic resync against `/api/v2/terminals`, so a value set at load-time stays stale indefinitely.
3. **6 zombie wake-pings on B1 + B4 inboxes** (ids 186/187 for vault_mirror, 155/175/181/182 for harness migration) for already-shipped work. B-codes flip their `CODE_N_PENDING.md` frontmatter on ship but never `POST /msg/<id>/ack` their own dispatch/correction/scope-amendment messages. Every shipped brief leaves 2-4 zombies on the bus indefinitely.

The three fixes share one surface (glance-UX truth pipeline) and one root pattern (state mutations don't propagate to the glance layer). Bundled to avoid 3x review chains.

## Estimated time: ~3-4h
## Complexity: medium
## Prerequisites: see frontmatter.

---

## Fix 1: Worker ack-on-ship hygiene (foundational — kills zombie generation at source)

### Problem

Every shipped brief leaves 2-4 unacked dispatch/correction messages on the worker's inbox. After ~5 ships per worker per week, the bus accumulates 10-20 zombies per terminal. Badges become meaningless. Director's only signal of "real work pending" is buried under historical noise.

Observed 2026-05-13: B1 had 2 unread (both wake-pings from a brief that shipped 30 min later via PR #196). B4 had 4 unread (all for HARNESS_SUBAGENT_MIGRATION_1 + MODEL_DEPRECATION_SWEEP_1 — both shipped >24h ago).

### Current State

`_ops/processes/b-code-dispatch-coordination.md §3 Mailbox hygiene after merge` (baker-vault) currently documents:
1. PR merges to main.
2. Dispatcher runs `git pull --rebase origin main`.
3. Mark mailbox: write `COMPLETE` marker OR overwrite with next brief.
4. `git add briefs/_tasks/CODE_N_PENDING.md && git commit && git push origin main`.

**Missing:** no step for acking inbox messages. B-codes have no helper script for this; the only ack tool is direct `curl POST /msg/<id>/ack` or the (still-broken-for-non-lead-slugs) MCP `baker_inbox_ack`.

Existing helpers in `scripts/`:
- `scripts/bus_post.sh` — POSTs to `/msg/<recipient>` for dispatch/ship messages (working today).
- `scripts/bus_post.py` — Python variant.
- No `bus_ack` helper exists.

### Implementation

**1.1** Create `scripts/ack_dispatch_msgs.sh` (NEW, baker-master). Mirrors `bus_post.sh` shape:

```bash
#!/usr/bin/env bash
# ack_dispatch_msgs.sh — sweep-ack inbox messages tied to a shipped brief.
#
# Usage:
#   BAKER_ROLE=b3 scripts/ack_dispatch_msgs.sh --brief-slug DEADLINE_MATTER_SLUG_BACKFILL_1
#
# Topic prefixes acked (all case-insensitive contains-match on lowercase slug):
#   dispatch/<slug>             — original wake-ping
#   dispatch/<slug>-*           — corrections (stale-checkout, branch reset)
#   request-changes/<slug>      — review REQUEST_CHANGES wake-pings
#   scope-amendment/<slug>      — Director-ratified mid-flight scope adds
#   ship/<slug>-v*-rerun        — gate-chain re-trigger pings
#
# Director-ratified 2026-05-13 (BRISEN_LAB_CARD_STATE_FIX_2 Fix 1).
# Non-fatal: any single ack failure logs + continues; script always exits 0
# unless config is invalid.

set -u
set -o pipefail

DAEMON_URL="${BRISEN_LAB_DAEMON_URL:-https://brisen-lab.onrender.com}"
BRIEF_SLUG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --brief-slug) BRIEF_SLUG="$2"; shift 2 ;;
    *) echo "[ack] unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$BRIEF_SLUG" ]] && { echo "[ack] --brief-slug required" >&2; exit 2; }

# Resolve sender slug from BAKER_ROLE — same map as bus_post.sh.
ROLE="${BAKER_ROLE:-}"
case "$ROLE" in
  b1|B1) SENDER="b1" ;;
  b2|B2) SENDER="b2" ;;
  b3|B3) SENDER="b3" ;;
  b4|B4) SENDER="b4" ;;
  AH1|aihead1|lead|LEAD) SENDER="lead" ;;
  *) echo "[ack] BAKER_ROLE unset or unrecognized: ${ROLE!r}" >&2; exit 2 ;;
esac

KEY="$(op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_${SENDER}/credential" 2>/dev/null)"
[[ -z "$KEY" ]] && { echo "[ack] 1Password fetch failed for ${SENDER}" >&2; exit 2; }

# Drain own inbox (limit 50 — well above per-brief topic count of ~5).
INBOX="$(curl -fsS -H "X-Terminal-Key: ${KEY}" "${DAEMON_URL}/msg/${SENDER}?limit=50")"
[[ -z "$INBOX" ]] && { echo "[ack] empty response from daemon"; exit 0; }

# Lowercase slug for topic matching.
SLUG_LC="$(echo "$BRIEF_SLUG" | tr '[:upper:]' '[:lower:]')"

# Match topics: dispatch/<slug>*, request-changes/<slug>*, scope-amendment/<slug>*,
# ship/<slug>-v*-rerun. Hyphens in slug stay hyphens.
MATCHING_IDS="$(echo "$INBOX" \
  | python3 -c "
import json, sys, re
slug = '${SLUG_LC}'
patterns = [
    rf'^dispatch/{re.escape(slug)}(-|$)',
    rf'^request-changes/{re.escape(slug)}(-|$)',
    rf'^scope-amendment/{re.escape(slug)}(-|$)',
    rf'^ship/{re.escape(slug)}-v.*-rerun$',
]
d = json.load(sys.stdin)
ids = []
for m in d.get('messages', []):
    if m.get('acknowledged_at'):  # already acked — skip
        continue
    topic = (m.get('topic') or '').lower()
    if any(re.match(p, topic) for p in patterns):
        ids.append(m['id'])
print(' '.join(str(i) for i in ids))
")"

if [[ -z "$MATCHING_IDS" ]]; then
  echo "[ack] no unacked messages for slug ${BRIEF_SLUG} on ${SENDER}'s inbox"
  exit 0
fi

ACKED=0
for id in $MATCHING_IDS; do
  HTTP="$(curl -fsS -o /dev/null -w '%{http_code}' -X POST \
    -H "X-Terminal-Key: ${KEY}" \
    "${DAEMON_URL}/msg/${id}/ack")" || true
  if [[ "$HTTP" == "200" ]]; then
    ACKED=$((ACKED + 1))
    echo "[ack] ${SENDER}/${id}: OK"
  else
    echo "[ack] ${SENDER}/${id}: HTTP ${HTTP} (continuing)" >&2
  fi
done
echo "[ack] acked ${ACKED} of $(echo "$MATCHING_IDS" | wc -w | tr -d ' ') messages for ${BRIEF_SLUG} on ${SENDER}'s inbox"
exit 0
```

**1.2** Add a pytest at `tests/test_ack_dispatch_msgs.py`. Mock `op read` + daemon HTTP. Cover:
- Happy path: 3 matching messages, all acked.
- Mixed: 2 matching + 1 already-acked → 2 acked, 1 skipped.
- Slug not present: 0 acked, exit 0.
- 1Password fetch fail: exit 2.
- Single-ack 4xx: continues + final count correct.

**1.3** Update `_ops/processes/b-code-dispatch-coordination.md §3` (baker-vault) to add a Step 4 ack call between mailbox-flip-commit and push:

```markdown
3. Mark mailbox: rewrite `CODE_N_PENDING.md` frontmatter `status: COMPLETE` (filename retained per FIX_1 frontmatter-authoritative classifier).
4. **Ack inbox messages tied to this brief** (NEW — Director-ratified 2026-05-13 BRISEN_LAB_CARD_STATE_FIX_2):
   ```bash
   BAKER_ROLE=b<N> scripts/ack_dispatch_msgs.sh --brief-slug <UPPER_SNAKE_SLUG>
   ```
   Non-fatal; if it fails, log the output in your ship report but proceed with commit + push. Director will catch any drift on the Director-facing glance surface.
5. `git add briefs/_tasks/CODE_N_PENDING.md && git commit && git push origin main`.
```

### Key Constraints

- Helper MUST be non-fatal on every failure path. A bus-ack failure cannot block a ship-merge.
- Helper MUST NOT auto-ack messages whose topic doesn't match a known brief-slug prefix — Director-relayed messages, cross-agent dispatches, and ratify-decision threads stay unacked for human review.
- Helper MUST iterate over messages, not bulk-ack via `msg_ids[]` array — daemon's bulk-ack signature exists (per `mcp__baker__baker_inbox_ack` schema) but single-ack is the documented authoritative path and produces one log line per ack for audit.
- Slug-matching is case-insensitive AND honours the canonical `UPPER_SNAKE_CASE` brief naming — must match `dispatch/upper_snake_case` (slug lowercased in topics per existing dispatcher convention).

### Verification

```bash
# Pre-fix: synthetic dispatch
BAKER_ROLE=lead scripts/bus_post.sh --to b4 --topic "dispatch/ZOMBIE_TEST_1" \
  --body "test dispatch — ignore"

# Verify it lands unacked
op read "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_b4/credential" | \
  xargs -I{} curl -s -H "X-Terminal-Key: {}" \
  "https://brisen-lab.onrender.com/msg/b4?limit=10" | \
  python3 -c "import json,sys; d=json.load(sys.stdin); \
    print([m['id'] for m in d['messages'] if not m['acknowledged_at'] and 'zombie_test_1' in (m['topic'] or '').lower()])"
# Expect: [<id>]

# Run the helper
BAKER_ROLE=b4 scripts/ack_dispatch_msgs.sh --brief-slug ZOMBIE_TEST_1
# Expect: [ack] b4/<id>: OK
# Expect exit 0

# Verify unread now empty
# (same curl as above)
# Expect: []
```

---

## Fix 2: Forge daemon reads stale local clones (B-code clones lag origin/main)

### Problem

The forge daemon (`scripts/forge_snapshot_push.sh`, runs every 30s via launchd `com.baker.forge-snapshot-push`) classifies each terminal's mailbox by reading the local clone at `~/bm-b{1-4}`. When AH1 commits a mailbox flip to `origin/main` from `~/bm-aihead1`, the B-code clones don't auto-pull, so the daemon's classifier sees stale frontmatter.

Observed 2026-05-13: AH1 committed `36708ff` (mailbox(b4) → COMPLETE) from `~/bm-aihead1`. ~/bm-b4's last commit is `5c8cfe0` (3 commits behind). Daemon classifies B4's mailbox from the stale local copy as `pending`, renders "Working at: hard-deadline-audit-1" even though the brief shipped 10h ago.

### Current State

`scripts/forge_snapshot_push.sh:189-241` correctly reads frontmatter status AND filename suffix from the file at `<repo>/briefs/_tasks/CODE_<N>_<SUFFIX>.md`. The `<repo>` is the local clone path resolved by `pick_active_clone()` (FIX_1's worktree picker). **The picker scores clones by recency + open PR + mailbox presence but never `git fetch`'s.**

`launchd com.baker.forge-snapshot-push` `StartInterval = 30` — cadence is fine; root cause is the local-clone source-of-truth.

### Implementation

**2.1** Add a `git fetch + ff-only pull` step to `scripts/forge_snapshot_push.sh` BEFORE `classify_mailbox()` is called. Insert after `pick_active_clone()` resolves the repo path:

```bash
# Ensure the chosen clone is at origin/main for mailbox-state reads.
# Mailbox state lives on main; working branch state (git_branch, git_head_subject)
# still comes from local HEAD, so a B-code mid-feature-branch is still reported
# as "yellow / Working at: <branch>" correctly.
sync_clone_to_main() {
  local repo="$1"
  local current_branch
  current_branch="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
  # Background-detached fetch + ff-pull on main only — never touches feature branches.
  # If pull would not fast-forward, log + skip (B-code has unpushed work; daemon
  # truthfully reports stale main mailbox until merge resolves).
  if [[ "$current_branch" == "main" ]] || [[ "$current_branch" == "master" ]]; then
    git -C "$repo" fetch origin main --quiet 2>/dev/null || true
    git -C "$repo" merge --ff-only origin/main --quiet 2>/dev/null || true
  else
    # On a feature branch: fetch only; mailbox reads use `git show origin/main:path`
    git -C "$repo" fetch origin main --quiet 2>/dev/null || true
  fi
}
```

Then modify `classify_mailbox()` to read mailbox files via `git show origin/main:briefs/_tasks/CODE_<N>_<suffix>.md` when the clone is on a feature branch:

```bash
# Inside classify_mailbox(), after picking the suffix candidate:
local content=""
if [[ "$current_branch" == "main" ]] || [[ "$current_branch" == "master" ]]; then
  content="$(cat "$candidate" 2>/dev/null)"
else
  # Feature-branch clone — read from origin/main reflog instead of local HEAD.
  content="$(git -C "$repo" show origin/main:briefs/_tasks/CODE_${n}_${suffix}.md 2>/dev/null)"
fi
# Pass $content to extract_frontmatter_status / extract_brief_name via a temp file.
```

**2.2** Add 2 bash-test cases to whatever tests cover `forge_snapshot_push.sh` (look for `tests/test_forge_snapshot_push.sh` or similar — if absent, create):
- **Case A:** B-code on feature branch, local main is 3 commits behind origin/main, origin/main has `status: COMPLETE` mailbox. Verify classifier returns "complete".
- **Case B:** B-code on main, local main IS origin/main. Verify classifier returns frontmatter status (regression check on FIX_1).

**2.3** Update the launchd plist installed copy at `/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh` — this is the working-copy the daemon runs from (not the repo path). Manual sync step in ship report:

```bash
cp /Users/dimitry/Desktop/baker-code/scripts/forge_snapshot_push.sh \
   "/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh"
launchctl kickstart -k gui/$(id -u)/com.baker.forge-snapshot-push
```

### Key Constraints

- `git fetch` MUST be quiet (`--quiet 2>/dev/null`) — daemon logs are tailed and noisy fetches would drown the signal.
- `git merge --ff-only` MUST fail silently when not fast-forwardable — B-code mid-feature-branch with unpushed work cannot be touched.
- Never run `git pull` (would attempt merge); only `fetch` + `merge --ff-only` separately for explicit control.
- Daemon iterates 6 clones every 30s — measure end-to-end runtime BEFORE merging. If >5s, parallelize fetches or skip when last-fetch <30s ago.
- DO NOT change `pick_active_clone()` — FIX_1's worktree scoring is correct and orthogonal.

### Verification

```bash
# Setup: ~/bm-b3 mid-feature-branch, origin/main has flipped mailbox to COMPLETE
cd ~/bm-b3 && git checkout b3/some-feature-branch
# Trigger daemon once
/Users/dimitry/Library/Application\ Support/baker/forge_snapshot_push.sh
# Inspect last snapshot for b3 — should report mailbox_status=complete
curl -s -H "X-Terminal-Key: $(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')" \
  https://brisen-lab.onrender.com/api/v2/terminals | python3 -m json.tool | \
  python3 -c "import json,sys; d=json.load(sys.stdin); print(next(t for t in d.get('terminals',[]) if t['alias']=='b3'))"
# Expect: "mailbox_status": "complete"
```

---

## Fix 3: Lab UI badge state stale on Lead (no SSE resync on reconnect / no sanity poll)

### Problem

Lead's "3 unread / 602m" badge stayed despite direct bus query returning 0 unread. UI's `state.busBadge[alias]` is captured at SSE-stream-open and only mutated by `bus_badge_change` events that affect THAT specific alias. If Lead's badge was set to 3 at page load and no subsequent ack fired for Lead's inbox in this SSE session, the value stays at 3 indefinitely.

Observed 2026-05-13 09:35Z: direct curl `GET /msg/lead` returned 0 unread (all 5 most-recent messages have `acknowledged_at` populated, oldest 7 days ago). Lab UI showed "3 unread / 602m". After 6 ack curls against b1/b4 endpoint, B1+B4 badges cleared in the same UI session — proving SSE pipeline works for received `bus_badge_change` events. Lead's stale value never updated because no events for Lead arrived.

### Current State

`brisen-lab-staging/static/app.js:67-79` (`inboxBadgeProps`):

```javascript
function inboxBadgeProps(alias) {
  const ub = state.busBadge[alias];
  if (!ub || !ub.unacked_count) return null;
  // ... renders "N unread · Xm"
}
```

`state.busBadge` is mutated by SSE event handlers (look for `bus_badge_change` event listener in same file) and initialized from the `/api/v2/terminals` response at page-load (look for terminals-fetch path).

No code path forces a periodic resync of `state.busBadge` against `/api/v2/terminals` after page-load.

### Implementation

**3.1** Add a 60s polling loop in `app.js` that fetches `/api/v2/terminals` and reconciles `state.busBadge` for ALL aliases (not just ones with active SSE events). Place near existing SSE-init code:

```javascript
// Director-ratified 2026-05-13 (BRISEN_LAB_CARD_STATE_FIX_2 Fix 3).
// Periodic sanity-poll for badge state — SSE delivers incremental updates per
// affected alias, but a value set wrong at SSE-stream-open OR a missed event
// during reconnect cannot self-correct. 60s poll bounds staleness.
const BADGE_SANITY_POLL_MS = 60_000;

async function pollBadgeSanity() {
  try {
    const r = await fetch("/api/v2/terminals", { credentials: "same-origin" });
    if (!r.ok) return;
    const data = await r.json();
    for (const term of data.terminals || []) {
      const alias = term.alias;
      const live = term.inbox_badge;  // { unacked_count, oldest_unacked_age_sec }
      if (!live) continue;
      const cached = state.busBadge[alias] || {};
      // Reconcile if drift detected
      if (cached.unacked_count !== live.unacked_count) {
        state.busBadge[alias] = live;
        // Re-render this terminal's card
        if (typeof renderCard === "function") renderCard(alias);
      }
    }
  } catch (e) {
    // Silent failure — next tick will retry
  }
}

setInterval(pollBadgeSanity, BADGE_SANITY_POLL_MS);
```

**3.2** Verify the `/api/v2/terminals` response includes `inbox_badge: { unacked_count, oldest_unacked_age_sec }` per alias. If the field name differs, adapt — DO NOT change the daemon to match. Check `brisen-lab-staging/bus.py:930-1000` for response shape.

**3.3** Add a JS test (if test infrastructure exists for app.js — Jest or similar). If no JS test infra, add a manual-test step to the ship report covering:
- Load Lab page with a known-stale badge state (manually `INSERT` a fake-acked message via DB to make /api/v2/terminals return 0 while leaving state.busBadge at last known higher value).
- Wait 60s, verify badge clears.

### Key Constraints

- Poll cadence 60s is a deliberate ceiling — Director's "real signal" tolerance for staleness. Lower cadences cost daemon CPU; higher cadences let stale badges linger past Director-visible reveal cycles.
- Reconciliation MUST be unidirectional: server is authoritative. Never push UI-side mutations back to server.
- If `inbox_badge` is null on server but cached value is non-zero, treat as drift and clear the cached value.
- Do NOT remove the existing SSE incremental-update path — sanity-poll is additive, not a replacement. SSE remains primary for <1s latency on real acks.

### Verification

```bash
# Manual: set a stale value in UI state via DevTools
# 1. Open https://brisen-lab.onrender.com/#production
# 2. DevTools console:
state.busBadge.lead = { unacked_count: 99, oldest_unacked_age_sec: 999999 };
renderCard("lead");
# Card now shows "99 unread · 16666m"
# 3. Wait 60s
# Expect: card reverts to whatever /api/v2/terminals returns for lead
```

---

## Files Modified

- `scripts/ack_dispatch_msgs.sh` — NEW (Fix 1; baker-master)
- `tests/test_ack_dispatch_msgs.py` — NEW (Fix 1; baker-master)
- `scripts/forge_snapshot_push.sh` — MODIFIED (Fix 2; baker-master)
- `/Users/dimitry/Library/Application Support/baker/forge_snapshot_push.sh` — MIRROR install (Fix 2; manual step in ship report)
- `tests/test_forge_snapshot_push.sh` — NEW or MODIFIED (Fix 2; baker-master)
- `brisen-lab-staging/static/app.js` — MODIFIED (Fix 3; brisen-lab repo PR)
- `_ops/processes/b-code-dispatch-coordination.md` — MODIFIED §3 (baker-vault; direct push per CHANDA Inv 9)

## Do NOT Touch

- `scripts/forge_snapshot_push.sh:189-241` (`extract_frontmatter_status` + `classify_mailbox`) — FIX_1 logic is correct; only ADD fetch step before, do not modify the classifier.
- `scripts/forge_snapshot_push.sh:26-55` (mkdir-mutex flock guard) — FIX_1 architect-cleared.
- `brisen-lab-staging/bus.py:444-493` (ack endpoint) — `_emit_badge_refresh` already broadcasts SSE on ack; Fix 3 is purely client-side.
- `brisen-lab-staging/auth_lab.py` — terminal-key auth path, separate concern.
- `baker_mcp/baker_mcp_server.py:1138` (`_brisen_lab_terminal_key()`) — Render env var fix shipped 2026-05-13 09:55Z via Tier-B PUT; MCP path works for lead slug only by design.
- `scripts/bus_post.sh` / `scripts/bus_post.py` — outbound posters; orthogonal.

## Quality Checkpoints

1. Pytest PASS literal output pasted in ship report (Fix 1 unit tests).
2. Bash test PASS for forge_snapshot_push.sh feature-branch+stale-main case (Fix 2).
3. Manual end-to-end (Fix 1): dispatch + ack throwaway brief, verify 0 unread on inbox.
4. Manual end-to-end (Fix 2): commit mailbox flip on `~/bm-aihead1`, reload Lab within 60s, verify B-code's card flips from yellow to green.
5. Manual end-to-end (Fix 3): set stale badge via DevTools, wait 60s, verify auto-reconcile.
6. `/security-review` on baker-master PR — must clear (helper script reads `op` credentials; perimeter concern).
7. picker-architect on each of 3 PRs.
8. `feature-dev:code-reviewer` 2nd-pass on each of 3 PRs — MANDATORY (Tier-B trigger #4).
9. Mirror install of forge_snapshot_push.sh to `/Users/dimitry/Library/Application Support/baker/` + launchctl kickstart in ship report.
10. Confirm sibling-dispatch BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1 (3091f50) has cleared b3's queue BEFORE picking this up — do not collide with parallel-AH1's incomplete dispatch.

## Verification SQL / probes

```sql
-- Bus daemon: confirm no unacked messages for a shipped brief
-- (run from brisen-lab daemon's DB session)
SELECT id, from_terminal, to_terminals, topic, created_at, acknowledged_at
FROM brisen_lab_msg
WHERE acknowledged_at IS NULL
  AND topic ILIKE 'dispatch/zombie_test_1%'
ORDER BY id DESC LIMIT 10;
-- Expect: 0 rows post-ack-on-ship sweep.
```

```bash
# Lab live state, all terminals
curl -s -H "X-Terminal-Key: $(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')" \
  https://brisen-lab.onrender.com/api/v2/terminals | python3 -m json.tool | head -80
# Expect: every alias's inbox_badge matches direct GET /msg/<alias> unacked count.
```

## Anti-pattern checks (lessons.md)

- ✅ Snippets are copy-pasteable, no `...` placeholders for important logic.
- ✅ Function signatures grep-verified (`extract_frontmatter_status`, `classify_mailbox`, `pick_active_clone`).
- ✅ All file paths absolute or repo-relative with explicit clone reference.
- ✅ No secrets in brief — credentials referenced by `op://` path only.
- ✅ Helper script non-fatal on failure (Sequential pollers blocked by upstream failure lesson — applies inversely here).
- ✅ Render restart survival: `app.js` poll auto-restarts on page load; ack helper is one-shot per B-code ship.
- ✅ Blast radius: each fix is independently reversible (revert single PR).

## Dispatch instructions

Once committed to baker-master main, write `briefs/_tasks/CODE_3_PENDING.md` with this brief as `brief:` reference, dispatch via `bus_post.sh` to b3 (topic `dispatch/BRISEN_LAB_CARD_STATE_FIX_2`). Wait for BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1 to clear first.

End-of-work: B3 bus-posts `ship/BRISEN_LAB_CARD_STATE_FIX_2` to `lead` with the 4-gate verdicts + literal pytest/bash outputs.
