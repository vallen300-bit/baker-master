# BRIEF: HAG_DESK_HEARTBEAT_DAEMON_1 — wire hag-desk into the Mac Mini snapshot pusher

## Context

The hag-desk card on https://brisen-lab.onrender.com is stuck at `daemon_last_seen: 2026-05-21T21:57:34Z` — frozen at yesterday's one-off ship-validation post. All other supervisor + worker cards (lead / cowork-ah1 / deputy / b1-b4) update every 30s.

Director directive 2026-05-22: *"I needed to function like all other cards on Brisen Labs. All other cards work perfectly. When somebody sends you a bus, the card shows that something arrived. Can you do exactly the same with HAG desk on Brisen lab?"*

The infrastructure is **already 95% in place**:

- **Front-end card slot** — `static/index.html` has `<article class="card card-desk" data-alias="hag-desk"></article>` (verified via `curl https://brisen-lab.onrender.com/`).
- **Front-end JS** — `static/app.js:9` `TERMINALS = ["lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk"]`; `inboxBadgeProps(alias)` at `app.js:80` is alias-agnostic so bus-arrival badge fires automatically.
- **Bus server-side** — `bus_post.sh` accepts `hag-desk` slug (whitelisted line 47); brisen-lab daemon serves `/msg/hag-desk` (verified via msg #650 delivery 2026-05-22).
- **Picker drain hook** — `~/.claude/hooks/session-start-bus-drain.sh` reads `BAKER_ROLE=hag-desk` and drains inbox on SessionStart (verified via Director's `orient` run 2026-05-22).

**The ONE remaining gap:** `scripts/forge_snapshot_push.sh` TERMINALS array (lines 61-69) has no `hag-desk` entry. Mac Mini daemon iterates that array every 30s, POSTs `/api/snapshot` per terminal; without an entry, `hag-desk` heartbeat never refreshes → card visually stale despite being functionally live.

## Estimated time: ~30 min
## Complexity: Low
## Prerequisites: none (canonical script at `scripts/forge_snapshot_push.sh` is identical to deployed copy verified 2026-05-22)

---

## Fix 1: Add hag-desk to TERMINALS array

### Problem
`scripts/forge_snapshot_push.sh:61-69` defines the slug → repo-path map. `hag-desk` is missing.

### Current State
```bash
declare -a TERMINALS=(
  "lead:/Users/dimitry/bm-aihead1"
  "cowork-ah1:/Users/dimitry/bm-aihead1"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab"
  "b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab"
  "b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab"
  "b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab"
)
```

### Implementation
Append one line:
```bash
declare -a TERMINALS=(
  "lead:/Users/dimitry/bm-aihead1"
  "cowork-ah1:/Users/dimitry/bm-aihead1"
  "deputy:/Users/dimitry/bm-aihead2"
  "b1:/Users/dimitry/bm-b1,/Users/dimitry/bm-b1-brisen-lab"
  "b2:/Users/dimitry/bm-b2,/Users/dimitry/bm-b2-brisen-lab"
  "b3:/Users/dimitry/bm-b3,/Users/dimitry/bm-b3-brisen-lab"
  "b4:/Users/dimitry/bm-b4,/Users/dimitry/bm-b4-brisen-lab"
  "hag-desk:/Users/dimitry/baker-vault"
)
```

**Why repo path = `~/baker-vault`:**
- Hag Desk has no code clone (the picker at `~/bm-hag-desk` is a vault-companion folder, not a git repo — verified `git remote -v` returns "not a git repository" 2026-05-22).
- Hag Desk's actual work surface IS `~/baker-vault` — writes `_ops/agents/hagenauer-desk/OPERATING.md`, `ARCHIVE.md`, `wiki/matters/hagenauer-rg7/*`.
- `~/baker-vault` is a checked-out git repo (verified `git log` returns commits 2026-05-22).
- Surfacing baker-vault `git_branch` / `git_head_sha` / `git_head_subject` is the right semantic: it tells Director "what's the latest committed state of Hag Desk's work?"

### Key Constraints
- Do NOT change mailbox-classification logic at `scripts/forge_snapshot_push.sh:449` (`if [[ "$alias" =~ ^b([1-9])$ ]]`). For non-b-code aliases this branch is skipped; `mailbox_status` defaults to `n/a` and `mailbox_brief_name` defaults to empty. This matches existing behavior for `lead`/`deputy`/`cowork-ah1` and is correct for `hag-desk` (no CODE_N_PENDING mailbox — its "mailbox" is the bus, badge-rendered separately by `app.js:inboxBadgeProps`).
- Do NOT modify the `pick_active_clone()` function — single-path entries (no comma) already work as verified by `lead`/`deputy`/`cowork-ah1` entries.

### Verification
After deploy + 30s wait:
```bash
KEY="$(op read 'op://Baker/brisen-lab-lead-key/credential')"
curl -s "https://brisen-lab.onrender.com/api/state?terminal=lead" -H "X-Terminal-Key: $KEY" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); h=d['snapshots']['hag-desk']; print(h)"
```
Expected: `daemon_last_seen` is within last 60s. `git_branch="main"`. `git_head_sha`+`git_head_subject` match `git -C ~/baker-vault log --oneline -1`. `mailbox_status="n/a"`.

Run twice 30s apart — `daemon_last_seen` must advance.

---

## Fix 2: Add smoke test coverage

### Problem
`tests/test_forge_snapshot_push.sh` Cases A-G cover b-code mailbox classification + multi-clone selection but have no fixture for a non-b-code single-clone slug (current coverage assumes such slugs are only `lead`/`deputy` which are implicit / never tested explicitly).

### Implementation
In `tests/test_forge_snapshot_push.sh`, after Case G, add:

```bash
# ─────────────────────────────────────────────────────────────────────────────
# Case H — non-b-code single-clone slug (desk pattern, e.g. hag-desk).
# Asserts: terminal_alias is preserved; mailbox_status defaults to "n/a";
# mailbox_brief_name empty. Future desks-on-bus follow this pattern.
# ─────────────────────────────────────────────────────────────────────────────
CASE_H_REPO="$TMP/case-h-desk"
mkdir -p "$CASE_H_REPO"
(
  cd "$CASE_H_REPO"
  git init -q
  git config user.email "test@test"
  git config user.name "test"
  echo "vault-content" > README.md
  git add README.md
  git commit -qm "case-h: desk vault clone init"
)

CASE_H_OUT="$TMP/case-h.out"
run_daemon "case-h" "hag-desk:$CASE_H_REPO" > "$CASE_H_OUT"
assert_no_prod_aliases "$CASE_H_OUT"

CASE_H_ALIAS="$(extract_payload_field "$CASE_H_OUT" "hag-desk" "terminal_alias")"
CASE_H_MSTATUS="$(extract_payload_field "$CASE_H_OUT" "hag-desk" "mailbox_status")"
CASE_H_MBRIEF="$(extract_payload_field "$CASE_H_OUT" "hag-desk" "mailbox_brief_name")"

[[ "$CASE_H_ALIAS" == "hag-desk" ]]    || { echo "FAIL Case H: terminal_alias='$CASE_H_ALIAS'" >&2; exit 1; }
[[ "$CASE_H_MSTATUS" == "n/a" ]]       || { echo "FAIL Case H: mailbox_status='$CASE_H_MSTATUS'" >&2; exit 1; }
[[ -z "$CASE_H_MBRIEF" ]]              || { echo "FAIL Case H: mailbox_brief_name='$CASE_H_MBRIEF' (expected empty)" >&2; exit 1; }
echo "PASS Case H: non-b-code single-clone slug — mailbox stays n/a"
```

### Verification
```bash
cd ~/bm-aihead1
bash tests/test_forge_snapshot_push.sh
```
Expected: all 8 cases (A through H) print `PASS`.

---

## Fix 3: Deploy

### Problem
Editing the canonical script is necessary but not sufficient — Mac Mini's launchd reads the deployed copy at `~/Library/Application Support/baker/forge_snapshot_push.sh`. The deployed copy must be refreshed via the existing `install_forge_push.sh` script.

### Implementation
On the host running the daemon (Mac Mini per CLAUDE.md, also runs on this MacBook per `launchctl list | grep com.baker.forge`):

```bash
cd ~/bm-aihead1
git pull --rebase origin main   # pick up Fix 1 + Fix 2
FORGE_KEY="$(launchctl getenv FORGE_KEY 2>/dev/null || op read 'op://Baker/forge-key/credential')" \
  bash scripts/install_forge_push.sh
```

The install script:
1. Copies canonical → deployed location (`~/Library/Application Support/baker/forge_snapshot_push.sh`).
2. Unloads existing launchd agent.
3. Regenerates plist with FORGE_KEY substituted.
4. Reloads agent — next 30s tick uses new TERMINALS array.

### Key Constraints
- Do NOT edit the deployed copy directly — that breaks reproducibility from git.
- `install_forge_push.sh` must be invoked on **every host** running the daemon. If both Mac Mini AND MacBook run it (verified `launchctl list | grep forge-snapshot-push` returns active agent on MacBook 2026-05-22), redeploy on both.

---

## Files Modified
- `scripts/forge_snapshot_push.sh` — one new line in TERMINALS array (line 69)
- `tests/test_forge_snapshot_push.sh` — append Case H (~30 LOC)

## Do NOT Touch
- `scripts/install_forge_push.sh` — deploy mechanism unchanged
- `static/index.html`, `static/app.js`, `static/styles.css` (brisen-lab front-end) — already wired
- `app.py`, `bus.py` (brisen-lab server) — already accepts hag-desk
- `~/bm-aihead1/scripts/bus_post.sh` — already whitelists hag-desk
- The deployed `~/Library/Application Support/baker/forge_snapshot_push.sh` — let install script handle it

## Quality Checkpoints

1. Diff is minimal: one new TERMINALS line + one new test case. No refactoring, no comment churn.
2. `bash tests/test_forge_snapshot_push.sh` exits 0 with 8 PASS lines.
3. Post-deploy verification (run twice, 30s apart):
   ```bash
   KEY="$(op read 'op://Baker/brisen-lab-lead-key/credential')"
   for i in 1 2; do
     curl -s "https://brisen-lab.onrender.com/api/state?terminal=lead" -H "X-Terminal-Key: $KEY" \
       | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['snapshots']['hag-desk']['daemon_last_seen'])"
     sleep 30
   done
   ```
   Both prints must show timestamps within last 60s, and the second must be later than the first.
4. Browser visual: open https://brisen-lab.onrender.com — hag-desk card renders with same structure as b-code cards (name, current-state line, badge row when applicable). Card-desk styling differences acceptable (the `card-desk` class exists for visual distinction).
5. Bus-arrival badge end-to-end:
   ```bash
   cd ~/bm-aihead1
   BAKER_ROLE=lead scripts/bus_post.sh hag-desk "heartbeat smoke test" smoke/heartbeat
   ```
   Within ~2s (SSE), hag-desk card shows `1 unread · <age>` badge. (Server + UI side already work; this just confirms wiring end-to-end.)

## Verification SQL
n/a — no schema changes.

---

## Pattern for future desk-on-bus additions

When AO Desk / MOVIE Desk / Brisen Desk / Origination Desk / Baden-Baden Desk go on the bus (post hag-desk pilot proof), this brief's three-fix pattern repeats:

1. Add `<slug>:/Users/dimitry/baker-vault` to TERMINALS array in `forge_snapshot_push.sh`.
2. Add a test Case (`I`, `J`, ...) mirroring Case H for the new slug.
3. Re-run `install_forge_push.sh` to redeploy.

Front-end requires: `<article data-alias="<slug>" class="card card-desk"></article>` slot in `static/index.html` + slug added to `app.js:TERMINALS` + label in `app.js:15` `LABELS` dict. (Done for `hag-desk` already; replicate for each new desk.)

Bus server requires: slug added to `bus_post.sh` whitelist + brisen-lab daemon's recipient validator (per HAGENAUER_DESK_ON_BUS_1 pattern).

---

## Risks
- **LOW:** Adding one TERMINALS entry. Daemon iterates per-terminal with isolated try/catch (`scripts/forge_snapshot_push.sh:519-540`). If hag-desk entry fails any reason, other terminals continue uninterrupted.
- `~/baker-vault` routinely has uncommitted changes (Hag Desk + other desks write to it). `git_head_sha` reports committed state only — dirty working tree is invisible. Same behavior as `lead` reporting from `bm-aihead1` (also routinely dirty during AH1 sessions). Acceptable.
- If a future desk shares the `~/baker-vault` path with hag-desk in TERMINALS, ALL such desks will report identical git state. Cosmetic (each desk's card shows the same baker-vault HEAD). Acceptable for the pilot — revisit if confusing once 3+ desks on bus.

## Ship gate
Literal `bash tests/test_forge_snapshot_push.sh` output showing 8 PASS lines, included in PR description. No "pass by inspection."

## Reporting
- Bus-post `lead` on PR open: `BAKER_ROLE=b<N> ~/bm-aihead1/scripts/bus_post.sh lead "PR #<num> opened: HAG_DESK_HEARTBEAT_DAEMON_1" ship/hag-desk-heartbeat`.
- `dispatched_by: lead` in CODE_N_PENDING mailbox UPDATE.
