---
brief_id: AID_ON_BUS_1
target: b1
target_repo: brisen-lab (front + server + tests + wake-handler) + baker-vault (agent-bus-posting-contract SKILL)
matter_slug: baker-internal
dispatched_by: lead
reply_to: lead
priority: tier-b
deadline: 2026-05-26T18:00:00Z
authored_at: 2026-05-25T20:15:00Z
template_anchor: BRIEF_RESEARCHER_ON_BUS_1 (shipped 2026-05-22 + Row-10 third-pass fix 2026-05-24)
sop_anchor: ~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md
director_ratification: chat 2026-05-25 ~19:15Z to deputy ("install him accordingly to Brisen Lab... alongside researcher, row 4, above cortex, same size as researcher")
deputy_routing: bus #1128 (AH1 lead authoring per usual SOP; deputy gates on PR open per ai-head-autonomy-charter §3)
---

# BRIEF_AID_ON_BUS_1 — wire AID (AI Dennis) onto Brisen Lab bus

### Surface contract (ui-surface-prebrief skill, V1) — AC9 + AC10 (front-end + server card)

1. **User action:** Director monitors AID activity at-a-glance via peer card on brisen-lab cockpit (read-only — heartbeat + git/mailbox state + unread badge, same pattern as researcher card shipped 2026-05-22).
2. **Backend route:** N/A — card uses existing `/api/v2/terminals` aggregator that pulls per-slug from `forge_snapshots` + `brisen_lab_msg`. No new route.
3. **Endpoint contract:** Existing `_build_terminals_response()` slug-loop at `bus.py:1005` reads from `forge_snapshots` keyed by `terminal_alias=aid` once the slug is added to all four bus.py / app.py sites + snapshot pusher TERMINALS array.
4. **State location:** brisen-lab Postgres (`forge_snapshots` keyed by `terminal_alias=aid` + `brisen_lab_msg` for bus traffic). Auto-populated once slug is server-registered (Rows 10 + 11) + snapshot pusher includes the slug (Row 12).
5. **UI repo (= state repo):** brisen-lab (state + UI co-located, ui-surface-prebrief Rule §4 ✓). Surface: brisen-lab cockpit cards.
6. **Director surface preference:** Web cockpit (brisen-lab is the canonical peer-monitoring UI; Director-ratified pattern since cockpit ratify-panel arc 2026-05-19). AID card lands in `.row-desks` next to researcher.
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `https://brisen-lab.onrender.com/` after the brisen-lab PR merges + AH1 Tier-B post-merge completes. Confirm AID card renders in `.row-desks` adjacent to researcher (grey state acceptable pre-AC12 smoke; post-smoke it should flip to green with the smoke message). Code-shape review necessary but NOT sufficient.

Outside the card (rows 1-4, 9, 12-13 — picker dir + zshrc + Terminal profile + CLAUDE.md + 1P/Render + forge pusher + wake-handler), no clickable surface — pure backend bus wiring + config + skill text.

## Problem

AID (AI Dennis) is bus-less on Brisen Lab. The slug `aid` was ratified 2026-05-10 and partially wired (Rows 5, 6, 7, 8 of the 13-row install SOP — bus_post.sh recipient + sender whitelists, session-start drain hook, 1Password terminal key). The remaining 9 rows never landed: no picker folder, no shell function, no Terminal.app profile, no CLAUDE.md, no Render env JSON merge, no dashboard card, no four-site brisen-lab bus.py/app.py registration, no snapshot pusher, no wake-handler alias.

Director ratified the full install via deputy 2026-05-25 ~19:15Z with explicit card-slot scope ("alongside researcher, row 4 of dashboard layout, positioned above cortex, same size as researcher"). Deputy routed authoring to AH1 (lead) per usual SOP; AH1 dispatches the brisen-lab code work to b1 and handles Mac-local + Tier-B rows in coordination.

## Slug + naming (Director-ratified)

- Bus slug: `aid` (ratified 2026-05-10; appears in bus_post.sh whitelists + drain hook).
- Picker dir: `~/bm-aid/` (local Mac, NOT Dropbox, NO git clone — AID does not own code repos; opens via shell function from Terminal.app).
- Shell function name: `aid` (matches slug — simplest pattern; mirrors `researcher` function).
- Terminal.app profile name: `AID` (matches dashboard card label exactly per Director's dashboard ↔ picker parity principle).
- Card label: `"AID"` (TERMINAL_LABELS dict in app.js — short, all-caps, matches Terminal profile + 1P key suffix).
- Card slot: `.row-desks` next to researcher (single `card-desk` class — peer-class to a desk in card terms per Director scope).
- Forge pusher repo-path: `/Users/dimitry/baker-vault` (Director-ratified pattern from SOP foot-note: no-code-clone agent uses baker-vault as "home" — same as hag-desk + researcher + CM workers + hag-filer).

## Bus authority

AID is **send-capable, narrow topics only** (mirrors researcher Tier-A discipline):
- `ship/<topic>` — research outputs, specs, dispatches BACK to lead
- `question/<target-agent>` — cross-agent dispatch questions (per `_ops/processes/cross-agent-knowledge-dispatch.md`)
- `fyi/<topic>` — design-time notices to peers
- NO Tier-B asks (AID CONTRACT v1.1 — escalates direct to Director on Tier-B prerogatives)
- NO dispatch authority to b-codes (engineering goes to AH1 or Director, per AID CONTRACT v1.1)

Discipline lives in AID's CLAUDE.md / CONTRACT.md (human-layer), NOT in bus_post.sh enforcement (bus is dumb pipe — slug auth + transport only).

## Rows already done (no work needed; deputy verified 5+6; AH1 pre-flight verified 7+8 2026-05-25)

| Row | Component | Status |
|---|---|---|
| 5 | bus_post.sh recipient whitelist | ✅ DONE — `aid` at line 47 of `~/bm-aihead1/scripts/bus_post.sh` (slug ratified 2026-05-10) |
| 6 | bus_post.sh sender whitelist | ✅ DONE — `aid|AID) SENDER=aid` at line 68 |
| 7 | SessionStart drain hook | ✅ DONE — `aid|AID) SLUG=aid` at line 54 of `~/.claude/hooks/session-start-bus-drain.sh` |
| 8 | 1Password terminal key | ✅ DONE — `BRISEN_LAB_TERMINAL_KEY_aid` exists in vault `Baker API Keys` (item id `ij4hsthkvsanefyu2jww4i2eiu`, created 2 weeks ago) |

## Acceptance criteria (testable; numbered to wiring-map rows where applicable)

### AC1 — Picker folder (Row 1) — **AH1 owns (Tier-A)**

Create `~/bm-aid/` as plain local directory (no git clone — AID has no code repos).

```bash
mkdir -p ~/bm-aid
```

### AC2 — Shell function (Row 2) — **AH1 owns (Tier-A)**

Append to `~/.zshrc` (after the `researcher` function block):

```bash
aid() {
  cd ~/bm-aid && BAKER_ROLE=aid FORGE_TERMINAL=aid claude
}
```

After append: `source ~/.zshrc` in any new shell to pick up the function.

### AC3 — Terminal.app profile (Row 3) — **AH1 owns (Tier-A) + Director manual relaunch (~30 sec)**

Clone existing B1 Terminal.app profile to a new `AID` profile via Python plistlib (per SOP fourth-pass foot-gun procedure):

```bash
python3 <<'PY'
import plistlib, copy, subprocess, os
plist_path = os.path.expanduser('~/Library/Preferences/com.apple.Terminal.plist')
with open(plist_path, 'rb') as f:
    data = plistlib.load(f)
window_settings = data['Window Settings']
src = window_settings['B1']
new = copy.deepcopy(src)
new['name'] = 'AID'
new['CommandString'] = 'aid'
new['WindowTitle'] = 'AID'
window_settings['AID'] = new
with open(plist_path, 'wb') as f:
    plistlib.dump(data, f)
subprocess.run(['killall', 'cfprefsd'], check=False)
print("AID profile written; relaunch Terminal.app to pick it up")
PY
```

After plistlib write: Director Cmd+Q + relaunch Terminal.app (only manual step; required because Terminal.app caches profiles in-process).

Verify post-relaunch: Terminal → Shell → New Window menu lists `AID`.

### AC4 — Picker CLAUDE.md (Row 4) — **AH1 owns (Tier-A)**

Create `~/bm-aid/CLAUDE.md` modeled on `~/bm-researcher/CLAUDE.md` + `~/bm-hag-desk/CLAUDE.md`. Required content:

- Tier 0 mandatory reads:
  1. Global rules auto-loaded (sanity check Rule 1 visible).
  2. `~/baker-vault/_ops/agents/aid/CONTRACT.md` (canonical AID design-time-only authority contract v1.1).
  3. `~/baker-vault/_ops/agents/aid/OPERATING.md` (current AID operating memory).
  4. `~/baker-vault/_ops/skills/it-manager/SKILL.md` (canonical AID skill).
  5. `~/.claude/skills/laconic/SKILL.md` (Director-facing register per dropbox-tier0.md Rule 6, ratified 2026-05-25).

- First-message confirmation phrase (evidence-bound, exact):
  `"AID oriented (Tier 0). Read: CONTRACT.md, OPERATING.md, it-manager/SKILL.md, laconic/SKILL.md."`

- "No by inspection" clause (mirror hag-desk pattern).
- Block applies when cwd path is `/Users/dimitry/bm-aid`.
- Canonical bus_post.sh reference: `~/bm-aihead1/scripts/bus_post.sh` (NOT stale `~/Desktop/baker-code/scripts/bus_post.sh` — known SOP foot-gun #3).
- Bus role wiring block: `BAKER_ROLE=aid` env required (set automatically by the `aid` shell function).
- Bus authority block: send-capable narrow topics only (`ship/<topic>`, `question/<target>`, `fyi/<topic>`); NO Tier-B asks; NO b-code dispatch.

### AC5 — Render env JSON merge (Row 9) — **AH1 owns (Tier-B)**

Verify whether `BRISEN_LAB_TERMINAL_KEYS` JSON env var on brisen-lab service already contains an `"aid"` key. If not, merge it in via single-key PUT (using `tools/render_env_guard.safe_env_put` per python-backend rules — NEVER raw array PUT, anchor 2026-05-17 catastrophic wipe):

1. Read current `BRISEN_LAB_TERMINAL_KEYS` from Render API.
2. Parse as JSON dict.
3. If `aid` already present: skip (Row 9 done).
4. If `aid` missing: read key value from 1Password (`op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_aid/credential'`).
5. Add `"aid": "<key>"` to the dict; serialize.
6. PUT updated JSON back via single-key merge-mode endpoint.
7. Trigger brisen-lab redeploy to pick up new env.

Tier-B per-action authorization — AH1 surfaces "Shall I PUT?" before executing.

### AC6 — Brisen Lab front-end (Row 10) — **b1 owns**

Edit brisen-lab repo:

- `static/index.html` — inside `<div class="row row-desks">` block, append after the researcher article:
  ```html
  <article class="card card-desk" data-alias="aid"></article>
  ```

- `static/app.js:9` `TERMINALS` array — append `"aid"` after `"researcher"`:
  ```js
  const TERMINALS = ["lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk", "researcher", "aid", "CM-1", "CM-2", "CM-3", "CM-4", "hag-filer"];
  ```

- `static/app.js:11` `TERMINAL_LABELS` dict — add entry after researcher line:
  ```js
    "researcher": "Researcher",
    "aid": "AID",
  ```

- Cache-bust `static/app.js?v=N` and `static/index.html?v=N` references (bump `v` by 1 per repo convention if those query params are present on script/link tags). If no version query params exist, no cache-bust needed.

- No CSS changes — `.card-desk` + `.row-desks` classes already exist from hag-desk + researcher installs. AID card reuses both verbatim.

### AC7 — Brisen Lab server bus.py: KNOWN_CARD_SLUGS (Row 11a) — **b1 owns**

Edit `bus.py:895-897` — append `"aid"` after `"researcher"`:

```python
KNOWN_CARD_SLUGS: tuple[str, ...] = (
    "lead", "deputy", "b1", "b2", "b3", "b4", "cortex", "cowork-ah1", "hag-desk", "researcher", "aid",
    "CM-1", "CM-2", "CM-3", "CM-4", "hag-filer",
)
```

### AC8 — Brisen Lab server bus.py: _build_terminals_response for-loop (Row 11b) — **b1 owns**

Edit `bus.py:1007` — append `"aid"` after `"researcher"` in the for-loop tuple:

```python
for slug in ("lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk", "researcher", "aid",
             "CM-1", "CM-2", "CM-3", "CM-4", "hag-filer"):
```

### AC9 — Brisen Lab server app.py: TERMINALS (Row 11c) — **b1 owns**

Edit `app.py:40-41` — append `"aid"` after `"researcher"`:

```python
TERMINALS = ["lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk", "researcher", "aid",
             "CM-1", "CM-2", "CM-3", "CM-4", "hag-filer"]
```

**CRITICAL**: this is the site that was missed on RESEARCHER_ON_BUS_1 third-pass (resulting in `POST /api/snapshot` HTTP 400 "unknown alias" every 30s + null `git_*` / `mailbox_status` / `daemon_last_seen` columns for the new slug). Do NOT skip this row.

### AC10 — Brisen Lab server regression tests (Row 11d) — **b1 owns**

Edit `tests/test_a3_a8_a9_bus.py`:

- Add `test_bus_badge_change_emitted_for_aid` — mirror existing `test_bus_badge_change_emitted_for_researcher` (line ~286); substitute `researcher` → `aid` and `lead-key` → `aid-key` as needed (key fixture probably keyed by slug). Asserts posting to `aid` emits `bus_badge_change` SSE envelope with `aid` in the `badges` dict.

- Add `test_v2_terminals_response_includes_aid` — mirror existing `test_v2_terminals_response_includes_researcher` (line ~322). Asserts `/api/v2/terminals` response slugs list includes `aid`.

- Both tests pattern-lifted from researcher fixtures shipped in PR #29 (merged 2026-05-22).

### AC11 — Snapshot pusher TERMINALS (Row 12) — **AH1 owns (Tier-A)**

Edit `~/bm-aihead1/scripts/forge_snapshot_push.sh:61-76` `TERMINALS` array — append `aid:~/baker-vault` after `researcher` line:

```bash
declare -a TERMINALS=(
  ...
  "researcher:/Users/dimitry/baker-vault"
  "aid:/Users/dimitry/baker-vault"
  "CM-1:/Users/dimitry/baker-vault"
  ...
)
```

**Foot-note (SOP §Second-pass)**: `~/baker-vault` is the canonical repo-path for no-code-clone agents. Do NOT use `~/bm-aid` (the picker dir has no `.git`, would error "repo missing" every 30s).

### AC12 — Wake-handler alias map (Row 13) — **b1 owns**

Edit `~/bm-b1-brisen-lab/tools/wake-handler/wake-handler.applescript:100-108` — add AID pair to the `fnMap` AppleScript list (append after researcher):

```applescript
set fnMap to {¬
    {"lead", "aihead1"}, ¬
    {"deputy", "aihead2"}, ¬
    {"cowork-ah1", "aihead1app"}, ¬
    {"b1", "b1"}, {"b2", "b2"}, {"b3", "b3"}, {"b4", "b4"}, ¬
    {"hag-desk", "hagenauerdesk"}, ¬
    {"researcher", "researcher"}, ¬
    {"aid", "aid"}, ¬
    {"CM-1", "cm1"}, {"CM-2", "cm2"}, {"CM-3", "cm3"}, {"CM-4", "cm4"}, ¬
    {"hag-filer", "hagfiler"}}
```

`fnName` is the shell-function name from AC2 (literal `aid`).

**Post-merge AH1 Tier-B**: rebuild + reinstall the wake-handler `.app` via `bash ~/bm-b1-brisen-lab/tools/wake-handler/build.sh` on MacBook (currently the only host where Director clicks the dashboard). Without this, clicking the AID card shows "no terminal picker installed for alias aid" instead of opening the picker.

### AC13 — agent-bus-posting-contract SKILL update (baker-vault) — **b1 owns**

Edit `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md`:

- §Recipient slugs line: append `aid` after `researcher` (currently last in the recipient list).
- Add a §AID subsection (mirror §Researcher structure) noting AID is bus-enabled with Tier-A send-capable narrow topics (`ship/<topic>`, `question/<target>`, `fyi/<topic>`), NO Tier-B authority, NO b-code dispatch (AID CONTRACT v1.1), picker at `~/bm-aid/`.

### AC14 — Card render verification (Director-visible surface) — **b1 reports; AH1 + Director verify post-merge**

After all PRs merge AND AH1 post-merge Tier-A + Tier-B (Rows 1-4, 9, 12 + wake-handler rebuild) complete:

1. AH1 loads `https://brisen-lab.onrender.com/` in browser.
2. Confirm AID card renders in `.row-desks` row, between researcher and CM-1.
3. Confirm card label reads `AID`.
4. Confirm card state: grey acceptable pre-smoke; should flip to green within ~30s after AC15 smoke if forge pusher is running.

b1 ship report flags this as "awaits AH1 post-merge per AC14."

### AC15 — End-to-end smoke (Director-visible) — **AH1 owns post-merge**

1. From any Terminal session: `BAKER_ROLE=lead ~/bm-aihead1/scripts/bus_post.sh aid "Smoke test from AH1 — Director-ratified install per bus #1128." smoke/aid-on-bus-1`
2. Verify response includes `message_id` + `posted_at`.
3. Open `https://brisen-lab.onrender.com/` — AID card should show unread badge count 1 within ~5s (SSE-pushed).
4. AH1 launches AID via `Terminal → Shell → New Window → AID` (verifying AC2 + AC3).
5. AID session-start drain hook fires; pulls the smoke message.
6. AID reply via `bus_post.sh lead "Smoke OK — AID on Brisen Lab live." smoke/aid-on-bus-1-ack`.
7. AH1 lead inbox shows the ack; badge state on AID card flips from "unread" to "acked" within SSE refresh window.

If any step fails, bus deputy + stop install for triage.

---

## Out-of-band Tier-B AH1 actions (post-merge, NOT b1)

b1 does NOT touch Render, 1Password, Mac launchd, or any shell-function/profile install. AH1 handles these in-session same chat turn as b1's PR merges:

| Action | Tier | Notes |
|---|---|---|
| AC1 — `mkdir -p ~/bm-aid` | A | Standing authorization. |
| AC2 — append `aid()` to `~/.zshrc` | A | Standing authorization (config edit). |
| AC3 — plistlib write `AID` profile + Director Cmd+Q+relaunch | A (plistlib) + Director manual relaunch | Per SOP fourth-pass procedure. |
| AC4 — write `~/bm-aid/CLAUDE.md` | A | Standing authorization (config file). |
| AC5 — Render env JSON merge `BRISEN_LAB_TERMINAL_KEYS["aid"]` | **B** | Per-action authorization — AH1 surfaces "Shall I PUT?" before. Uses `safe_env_put` (single-key merge mode); NEVER raw array PUT. |
| AC11 — edit `forge_snapshot_push.sh` TERMINALS | A | Standing authorization (config). |
| AC12 — wake-handler post-merge rebuild via `build.sh` | A | Standing authorization (script invocation, output is signed local `.app`). |
| AC14 — browser verification on brisen-lab cockpit | A | Standing authorization (read-only verification). |
| AC15 — end-to-end smoke + bus posts | A | Standing authorization (bus messaging is normal flow). |

## Files touched by b1 (brisen-lab repo)

| File | Change | Anchor row |
|---|---|---|
| `static/index.html` | +1 line (card article) | Row 10 |
| `static/app.js` | +2 entries (TERMINALS + LABELS) | Row 10 |
| `bus.py` | +1 token in KNOWN_CARD_SLUGS (~line 896) + 1 token in _build_terminals_response for-loop (~line 1007) | Row 11a + 11b |
| `app.py` | +1 token in TERMINALS list (~line 40) | Row 11c |
| `tests/test_a3_a8_a9_bus.py` | 2 new test functions | Row 11d |
| `tools/wake-handler/wake-handler.applescript` | +1 pair in fnMap (~line 109) | Row 13 |

## Files touched by b1 (baker-vault repo)

| File | Change | Anchor row |
|---|---|---|
| `_ops/skills/agent-bus-posting-contract/SKILL.md` | recipient line + §AID subsection | (not in SOP — agent-bus contract layer) |

## Files NOT to touch

- `~/bm-aihead1/scripts/bus_post.sh` — already has `aid` (rows 5+6 done 2026-05-10).
- `~/.claude/hooks/session-start-bus-drain.sh` — already has `aid` (row 7 done 2026-05-10).
- Anything 1Password, Render env, launchd, plistlib, shell rc, or Mac-local — those are AH1 in-session, NOT b1.
- `tools/wake-handler/build.sh` — invoked by AH1 post-merge, NOT modified.

## Quality Checkpoints (b1 ship report MUST include)

1. **Tests literal output**: `pytest tests/test_a3_a8_a9_bus.py -v` showing all tests PASS (including the 2 new AID tests). Paste the actual pytest output, not "by inspection."
2. **Static asset verification**: `grep -c '"aid"' static/app.js` returns ≥2 (TERMINALS array + LABELS dict).
3. **bus.py verification**: `grep -c '"aid"' bus.py` returns ≥2 (KNOWN_CARD_SLUGS + for-loop).
4. **app.py verification**: `grep -c '"aid"' app.py` returns ≥1 (TERMINALS list).
5. **Wake-handler verification**: `grep -c '"aid"' tools/wake-handler/wake-handler.applescript` returns ≥1 (fnMap pair).
6. **Cache-bust**: if `?v=N` query params present on app.js or index.html script/link tags, bumped by 1.
7. **No collateral edits**: `git diff --stat` should show ONLY the files listed under "Files touched by b1" above.

## Gate-1 + Gate-2 reviewer instructions (deputy)

Reviewers MUST:

1. **Load `https://brisen-lab.onrender.com/` after the brisen-lab PR merges AND AH1 Tier-B post-merge (Row 9 Render env JSON merge + redeploy) completes.** Confirm AID card renders in `.row-desks` row between researcher and CM-1.

2. **Confirm code-shape**: grep counts above all return expected. No collateral edits.

3. **Confirm test fixtures match real test structure**: open `tests/test_a3_a8_a9_bus.py`, verify the 2 new AID tests structurally mirror the researcher tests (line ~286 + ~322), not copy-paste errors.

4. **Confirm Row 11c (app.py TERMINALS) is included**: this is the third-pass foot-gun from RESEARCHER_ON_BUS_1 — if missed, forge pusher returns HTTP 400 every 30s. Verify `grep -c '"aid"' app.py` ≥1.

5. **Confirm wake-handler edit lands**: `grep -A1 '"aid"' tools/wake-handler/wake-handler.applescript` shows the pair `{"aid", "aid"}`.

6. **Confirm SOP §Bus authority block in CLAUDE.md draft (AC4)** matches AID CONTRACT v1.1 (no Tier-B, no b-code dispatch). AH1 will paste the draft CLAUDE.md content into the gate thread for review before writing to disk.

Code-shape review necessary but NOT sufficient — browser surface verification + smoke test are gate conditions.

## Risks + edge cases

1. **app.py TERMINALS skip** — explicit AC9 + grep verification covers it (RESEARCHER_ON_BUS_1 third-pass anchor).
2. **static/app.js TERMINALS skip** — explicit AC6 + grep verification covers it (HAG_WORKERS_PHASE_1 third-pass anchor).
3. **Forge pusher repo-path foot-note** — explicit AC11 uses `~/baker-vault` not `~/bm-aid` (RESEARCHER_ON_BUS_1 second-pass anchor).
4. **Terminal.app profile programmatic write trap** — AC3 uses plistlib + killall cfprefsd + Director relaunch (HAG_WORKERS_PROFILE_INSTALL fourth-pass anchor).
5. **AID skill path unverified** — brief assumes `~/baker-vault/_ops/skills/it-manager/SKILL.md` is the canonical AID skill. If deputy or AID prefers a different skill on Tier 0 (e.g. `aidennis-terminal`), AH1 + deputy confirm before AC4 lands.
6. **Bus authority discipline is human-layer** — bus_post.sh allows AID to post any topic to any recipient. AID could in principle violate Tier-A discipline (Tier-B asks, dispatches to b-codes). Acceptable trade-off (consistent with researcher model); discipline lives in CONTRACT.md.

## Estimated time

- **b1 (brisen-lab + baker-vault PRs)**: ~1-2h (mechanical from researcher template).
- **AH1 in-session (Rows 1, 2, 4, 11 + Row 3 plistlib)**: ~30 min.
- **Director relaunch (Row 3)**: ~30 sec.
- **AH1 Tier-B (Row 9 Render env + redeploy)**: ~5 min.
- **AH1 post-merge wake-handler rebuild + AC14 + AC15 smoke**: ~10 min.

Total wall-clock: ~2-3h end-to-end including deputy gate cycle.

## Complexity: Low

Mechanical install per canonical SOP. Templates from RESEARCHER_ON_BUS_1 (2026-05-22) + HAG_WORKERS_PHASE_1 (2026-05-24). Three foot-guns explicitly anchored in ACs.

## Prerequisites

- baker-master commit `346b9b9` or later (laconic install pulled into clones).
- brisen-lab repo: latest main.
- baker-vault repo: latest main (for agent-bus-posting-contract SKILL edit).

## Anchors

- Director ratification: chat 2026-05-25 ~19:15Z to deputy (via deputy bus #1128).
- Deputy routing: deputy bus #1128 (AH1 lead authors; deputy gates on PR open).
- SOP: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (Director-ratified 2026-05-22).
- Template brief: `~/bm-aihead1/briefs/BRIEF_RESEARCHER_ON_BUS_1.md` (shipped 2026-05-22).
- Third-pass anchor (app.js): HAG_WORKERS_PHASE_1 brisen-lab `c733b0b` (2026-05-24).
- Third-pass anchor (app.py): RESEARCHER_ON_BUS_1 brisen-lab `4cb949a` (2026-05-22).
- Fourth-pass anchor (Terminal profile): HAG_WORKERS_PROFILE_INSTALL same-day fix (2026-05-24).
- AID skill candidates: `~/baker-vault/_ops/skills/it-manager/SKILL.md` (primary) + `~/baker-vault/_ops/skills/aidennis-terminal/SKILL.md` (alternate — deputy to confirm).
- AID CONTRACT v1.1: `~/baker-vault/_ops/agents/aid/CONTRACT.md` (Director-ratified 2026-05-11 — design-time only; no engineering; escalates to Director on Tier-B).
- 1P key: `op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_aid/credential` (item id `ij4hsthkvsanefyu2jww4i2eiu`, created 2026-05-10).
