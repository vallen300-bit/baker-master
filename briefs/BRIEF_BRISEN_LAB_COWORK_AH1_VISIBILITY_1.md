# BRIEF: BRISEN_LAB_COWORK_AH1_VISIBILITY_1 — add cowork-ah1 to brisen-lab snapshot whitelist + UI

## Context

2026-05-17 the AH1 bus slug was split: `lead` (Terminal) + `cowork-ah1` (Cowork App). Wired in baker-master `8d8adf9` (BAKER_ROLE mapping) + baker-vault `9562cad` (worker reply-to-sender rule). Bus-side activity for `cowork-ah1` already populates `/api/v2/terminals` automatically (last_msg_at, recent_messages, unacked_count).

But `cowork-ah1` is missing from the daemon's hardcoded snapshot/UI whitelist. Specifically:
- `app.py:40` — `TERMINALS = ["lead", "deputy", "b1", "b2", "b3", "b4"]` → daemon rejects `/api/snapshot` for `cowork-ah1` with HTTP 400 "unknown alias"
- `static/app.js:9` — same array → frontend renders only 6 cards, no `cowork-ah1` tile

Result today: `forge_snapshot_push.sh` fires every 30s and gets HTTP 400 for cowork-ah1 (harmless noise in `~/Library/Logs/forge-snapshot-push.err.log`). Dashboard UI shows 6 cards, not 7.

This brief patches the whitelist in 2-3 places so the cowork-ah1 card renders + git/mailbox snapshots accept.

## Estimated time: ~1-2 hours (revised 2026-05-18 per Path B amendment)
## Complexity: Medium (was Low; bus.py:997 refactor + renderCoworkCard delete bumped scope)
## Working repo: brisen-lab (NOT baker-master)
## Trigger class: MEDIUM (was LOW; bus.py refactor + dead-code delete + multi-file coordinated change; still no auth/DB schema/external surface change)
## Prerequisites
- `~/brisen-lab-staging` clone (or fresh clone from `https://github.com/vallen300-bit/brisen-lab` if missing).
- Existing forge_snapshots DB table accepts arbitrary `terminal_alias` strings (no schema enum constraint to update — verified 2026-05-17 by reading INSERT statement at `app.py:333-348`).

## API version / deprecation / fallback

Not applicable — internal Brisen Lab daemon + frontend changes only.

---

## Problem statement

The AH1 split is operationally live on the bus + bus_post.sh + drain hook + worker orientations. Brisen Lab's snapshot whitelist + UI render list are the last gap. Without this patch:
- AH1-Cowork's git/mailbox state never updates in the dashboard (always shows null/stale).
- No UI card for cowork-ah1 — Director can't visually distinguish "AH1-App working" from "AH1-Terminal working."
- Snapshot pusher's 30s-interval log accumulates harmless HTTP 400 noise.

## Amendment 2026-05-18 — Path B ratified by AH1

B1 surfaced via bus #393 that the brief's assumed repo state was stale. Real state: `cowork-ah1` is ALREADY wired as a SYSTEM_CARD across 6 files (`static/app.js:10`, `static/index.html:39`, `bus.py:896` KNOWN_CARD_SLUGS, `db.py:226`, `lifecycle.py:493`, `tests/conftest.py:83`) with its own `renderCoworkCard()` at `app.js:253` that renders bus-only (no git/mailbox state visible). The true gap is `app.py:40 TERMINALS` rejecting `/api/snapshot` calls for cowork-ah1 (HTTP 400 every 30s) — which means snapshots don't even land in the DB.

B1 surfaced three paths. **AH1 ratifies Path B (brief-literal, brief's intent honored):**

- ❌ Path A (MINIMUM, app.py:40 only) — snapshots land but cowork-ah1 card stays bus-only. Does NOT deliver the brief's stated goal of git/mailbox visibility for cowork-ah1.
- ✅ **Path B (BRIEF-LITERAL)** — add `cowork-ah1` to TERMINALS (Python + JS); refactor `_build_terminals_response` cowork-ah1 branch at `bus.py:997` to pull from `forge_snapshots`; let `renderCoworkCard` become dead code (delete in same PR). cowork-ah1 becomes a full terminal card showing both bus AND git/mailbox state — same surface as lead/deputy.
- ❌ Path C (FULL DEMOTE) — overkill for this scope.

**Scope revision:** LOW → **MEDIUM** trigger class. Estimate revised from 20-30 min → **~1-2h**. Still no auth / DB schema / external surface change; `/security-review` skip-eligible.

## Files to update (B-code grep + confirm at edit time)

1. **`app.py:40`** — `TERMINALS` constant: add `"cowork-ah1"` between `"lead"` and `"deputy"` (peer-of-AH1 position).

2. **`static/app.js:9`** — `const TERMINALS = [...]`: same addition. Same position.

3. **`bus.py:997`** — `_build_terminals_response` cowork-ah1 branch: refactor to pull git/mailbox state from `forge_snapshots` (mirror the `lead`/`deputy`/`b1`-`b4` pattern). Without this refactor, the new terminal card renders empty for cowork-ah1.

4. **`static/app.js:253` `renderCoworkCard()`** — becomes dead code. Delete the function definition + its invocation site at the dispatch layer (`renderForAlias` at `app.js:591` should now fall through to the TERMINALS branch for cowork-ah1).

5. **`static/index.html:39`** — move cowork-ah1 placeholder from `row-system` to `row-supervisors` (alongside lead/deputy) if HTML structure pre-positions cards; otherwise leave for JS to render dynamically.

6. **`bus.py:896` `KNOWN_CARD_SLUGS`** — leave alone (cowork-ah1 stays valid as a card slug; the SYSTEM_CARDS-vs-TERMINALS distinction is in the rendering paths above, not in the slug registry).

7. **Tests** — `tests/conftest.py:83`: update cowork-ah1 to TERMINALS fixture. Grep `tests/` for any hardcoded SYSTEM_CARDS-cowork assumption; update if found.

## Acceptance criteria

1. **`app.py`** — `TERMINALS` constant includes `"cowork-ah1"`.
2. **`static/app.js`** — `TERMINALS` constant includes `"cowork-ah1"`.
3. **`bus.py`** — checked; updated if it has a similar list.
4. **Smoke test (literal curl)** captured in ship report:
   ```bash
   curl -sS -X POST "https://brisen-lab.onrender.com/api/snapshot" \
     -H "X-Forge-Key: $FORGE_KEY" \
     -H "Content-Type: application/json" \
     -d '{"terminal_alias":"cowork-ah1","git_branch":"main","git_head_sha":"<sha>","git_head_subject":"<subject>","mailbox_status":"n/a","mailbox_brief_name":null,"open_pr_number":null,"open_pr_title":null}' \
     -w "\nHTTP %{http_code}\n"
   ```
   Expected: HTTP 200 with `{"ok": true}` body. (FORGE_KEY: read via op CLI from 1Password.)
5. **UI verification** captured in ship report: load `https://brisen-lab.onrender.com/`, confirm 7 cards including cowork-ah1.
6. **Existing 6-card behavior preserved** — `lead`/`deputy`/`b1`/`b2`/`b3`/`b4` still render + accept snapshots.
7. **Existing tests pass.** Run `pytest tests/ -v` literal output captured in ship report. Specifically: `tests/test_snapshot_broadcast_daemon_last_seen.py` should still pass (no changes expected to break it).

## What this brief does NOT do

- Does NOT change the bus daemon's recipient-slug whitelist (cowork-ah1 already accepted there; that was wired earlier today by baker-master `8d8adf9` + the 13-slug registry in `bus_post.sh`).
- Does NOT change DB schema for `forge_snapshots` (terminal_alias column accepts any string per inspection).
- Does NOT change BAKER_ROLE mappings (already done in `bus_post.sh` + drain hook + canonical baker-vault).
- Does NOT change worker orientations (done in baker-vault `9562cad`).
- Does NOT touch `forge_snapshot_push.sh` TERMINALS array — that's baker-master/Director-Mac side, already updated today in `~/bm-aihead1/scripts/forge_snapshot_push.sh` + deployed to `~/Library/Application Support/baker/`.

## Ship gate

- Literal `pytest tests/ -v` green output in ship report.
- Smoke curl HTTP 200 captured in ship report.
- UI screenshot OR text confirmation (7 cards, all 7 names visible) in ship report.
- PR title: `feat(lab): add cowork-ah1 to snapshot whitelist + UI cards`.
- Branch: `b<N>/brisen-lab-cowork-ah1-visibility-1` (B-code picks number on claim).

## Reporting

- Bus-post `<dispatching-AH1-slug>` (read from `dispatched_by:` in CODE_N_PENDING.md mailbox) on PR open with topic `pr-open/brisen-lab-cowork-ah1-visibility-1`.
- AH1 runs cross-lane review chain (AH2 static; `/security-review` skip-eligible — internal-only changes, no external surface).

## Anchors

- 2026-05-17 chat — Director surfaced the gap ("brisen lab will now show what ah1cowork is doing?").
- Sister commits: baker-master `8d8adf9` (BAKER_ROLE mapping), baker-vault `9562cad` (worker reply-to-sender), `~/.zshrc` (`aihead1app` shell function).
- Bus-side scaffolding pre-existed: 1Password key `BRISEN_LAB_TERMINAL_KEY_cowork-ah1` + bus daemon 13-slug registry. UI/snapshot was the only missing layer.

## Co-Authored-By

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
