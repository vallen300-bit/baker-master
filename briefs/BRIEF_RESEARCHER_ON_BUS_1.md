---
brief_id: RESEARCHER_ON_BUS_1
target: b1
target_repo: brisen-lab (front + server + tests) + baker-master (bus_post.sh + forge pusher + tests + drain-hook fixture) + baker-vault (agent-bus-posting-contract SKILL)
matter_slug: baker-internal
dispatched_by: lead
reply_to: lead
priority: tier-b
deadline: 2026-05-23T18:00:00Z
authored_at: 2026-05-22T13:30:00Z
template_anchor: BRIEF_HAGENAUER_DESK_ON_BUS_1 (shipped 2026-05-21 + 3 follow-on fixes 2026-05-22)
sop_anchor: ~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md
---

# BRIEF_RESEARCHER_ON_BUS_1 — wire Researcher (Cowork-App) onto Brisen Lab bus

### Surface contract (ui-surface-prebrief skill, V1) — AC10 + AC11 (front-end + server card)

1. **User action:** Director monitors Researcher activity at-a-glance via peer card on brisen-lab cockpit (read-only — heartbeat + git/mailbox state + unread badge, same pattern as hag-desk card shipped 2026-05-21).
2. **Backend route:** N/A — card uses existing `/api/v2/terminals` aggregator that pulls per-slug from `forge_snapshots` + `brisen_lab_msg`. No new route.
3. **Endpoint contract:** Existing `_build_terminals_response()` slug-loop at `bus.py:1005` reads from `forge_snapshots` keyed by `terminal_alias=researcher` once the slug is added to all three bus.py sites + snapshot pusher TERMINALS array.
4. **State location:** brisen-lab Postgres (`forge_snapshots` keyed by `terminal_alias=researcher` + `brisen_lab_msg` for bus traffic). Auto-populated once slug is server-registered (AH1 post-merge AC8+AC9) + snapshot pusher includes the slug (AC12).
5. **UI repo (= state repo):** brisen-lab (state + UI co-located, ui-surface-prebrief Rule §4 ✓). Surface: brisen-lab cockpit cards.
6. **Director surface preference:** Web cockpit (brisen-lab is the canonical peer-monitoring UI; Director-ratified pattern since cockpit ratify-panel arc 2026-05-19; hag-desk landed in same row-desks slot 2026-05-21).
7. **Gate-1+2 reviewer instruction:** Reviewers MUST load `https://brisen-lab.onrender.com/` after the brisen-lab PR merges + confirm Researcher card renders in `row-desks` next to Hag Desk (grey state acceptable pre-AC13 smoke; post-smoke it should flip to green with the smoke message). Code-shape review necessary but NOT sufficient.

Outside the card (rows 1-9, 12 — bus_post.sh + drain hook + picker CLAUDE.md + 1P/Render + forge pusher), no clickable surface — pure backend bus wiring + config + skill text.

## Problem

Researcher is currently bus-less. AH1 ↔ Researcher coordination relays through Director paste-blocks. Researcher is Cowork-App-only (no Terminal sibling, unlike AH1's lead/cowork-ah1 split), Tier A read-only authority per `~/baker-vault/_ops/agents/researcher/orientation.md`. Putting Researcher on the bus = direct routing for research briefs in, ship reports + cross-agent questions out, heartbeat-able card on cockpit.

This install follows the canonical SOP at `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (ratified 2026-05-22 from hag-desk lived-experience), modified for Cowork-App pattern (rows 2 + 3 of the wiring map are N/A — no Terminal alias, no Terminal.app profile).

## Slug + naming (Director-ratified 2026-05-22)

- Bus slug: `researcher` (clean — no cowork- prefix; there is no terminal Researcher to disambiguate against, unlike cowork-ah1 which exists alongside lead).
- Picker dir: `~/bm-researcher/` (already exists — local Mac, NOT Dropbox, NO git clone; opened via Cowork App folder picker).
- Card label: `"Researcher"` (TERMINAL_LABELS dict in app.js).
- Card slot: `row-desks` next to hag-desk (single card-desk class — peer-class to a desk in card terms).
- Forge pusher repo-path: `/Users/dimitry/bm-researcher` (Director ratified — picker dir as "home" even without git clone; mirrors hag-desk's use of `~/baker-vault` as a no-code-clone home).

## Bus authority (Director-ratified 2026-05-22)

Researcher is **send-capable, narrow topics only**:
- `ship/research-<slug>` — ship reports for completed research briefs
- `question/<target-agent>` — cross-agent dispatch questions (per `_ops/processes/cross-agent-knowledge-dispatch.md`)
- NO Tier-B asks, NO dispatch authority. Mirrors Tier-A discipline from orientation.

Discipline lives in Researcher's CLAUDE.md / orientation (human-layer), NOT in `bus_post.sh` enforcement (bus is dumb pipe — slug auth + transport only). Brief does not add topic regex to bus_post.sh.

## Acceptance criteria (testable; numbered to wiring-map rows where applicable)

### AC1 — Picker CLAUDE.md update (Row 4)

Update `~/bm-researcher/CLAUDE.md` to:
- Preserve existing Tier-0 reads: `~/.claude/CLAUDE.md` + `~/baker-vault/_ops/agents/researcher/orientation.md` + canonical Baker memory + `~/baker-vault/_ops/agents/researcher/method.md` + `~/baker-vault/_ops/agents/researcher/research-types.md`.
- Preserve first-message confirmation phrase (evidence-bound, exact): `"Researcher oriented. Read: researcher/orientation.md, MEMORY.md."`
- ADD: canonical bus_post.sh dispatch reference — `~/bm-b1/scripts/bus_post.sh` (NOT `~/Desktop/baker-code/scripts/bus_post.sh` — known-stale per SOP foot-gun #3).
- ADD: bus role wiring block — `BAKER_ROLE=researcher` env required for bus_post.sh sender + drain-hook to fire; Cowork-App launcher should set this.
- ADD: bus authority block — send-capable narrow topics only (per §Bus authority above).
- Block applies when cwd path is `/Users/dimitry/bm-researcher`.

### AC2 — bus_post.sh recipient whitelist (Row 5)

Edit `~/bm-b1/scripts/bus_post.sh:45` recipient case statement:
```
case "$RECIPIENT" in
    director|cowork-ah1|lead|deputy|architect|b1|b2|b3|b4|b5|cortex|daemon|aid|hag-desk|researcher) ;;
```
Update line 48 error message in parallel: append `researcher` to the valid-slugs list.

### AC3 — bus_post.sh sender whitelist (Row 6)

Edit `~/bm-b1/scripts/bus_post.sh:55-73` sender case — append after `hag-desk` line (~line 67):
```
    researcher|RESEARCHER)              SENDER=researcher ;;
```
Update line 70 error message in parallel: append `researcher` to the valid-roles list.

### AC4 — SessionStart drain hook (Row 7)

Edit `~/.claude/hooks/session-start-bus-drain.sh:43-62` BAKER_ROLE case — append after `hag-desk` line (~line 55):
```
    researcher|RESEARCHER)              SLUG=researcher ;;
```
Note this file is user-global (NOT in any repo). Per SOP §Post-merge §4: changes here ship via the baker-master fixture at `tests/fixtures/session-start-bus-drain.sh` (b1 edits that fixture in-PR; AH1 `cp`'s the deployed fixture to `~/.claude/hooks/` post-merge as a separate Tier-B). If the `tests/fixtures/session-start-bus-drain.sh` file exists in baker-master, b1 edits BOTH the user-global file AND the fixture in the same PR. If only the user-global exists, b1 edits the user-global directly + the brief calls out the missing fixture as a SOP-row-7 gap to be addressed.

### AC5 — agent-bus-posting-contract SKILL update (baker-vault)

Edit `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md`:
- §Recipient slugs line: append `researcher` to the list (currently ends in `hag-desk`).
- Add a §Researcher subsection (mirror §Matter desks structure) noting Researcher is bus-enabled with Tier-A send-capable narrow topics (`ship/research-*`, `question/<target>`), no Tier-B authority, picker at `~/bm-researcher/`.

### AC6 — Brisen Lab front-end (Row 10)

Edit brisen-lab repo:
- `static/index.html` line ~43 (inside `<div class="row row-desks">`): append after hag-desk article:
```html
      <article class="card card-desk" data-alias="researcher"></article>
```
- `static/app.js:9` `TERMINALS` array: append `"researcher"` →
```js
const TERMINALS = ["lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk", "researcher"];
```
- `static/app.js:11-16` `TERMINAL_LABELS` dict: add entry →
```js
  "hag-desk": "Hag Desk",
  "researcher": "Researcher",
```
- No CSS changes — `.card-desk` + `.row-desks` classes already exist from hag-desk install. Researcher card reuses both verbatim.

### AC7 — Brisen Lab server bus.py: KNOWN_CARD_SLUGS (Row 11a)

Edit `~/bm-b1-brisen-lab/bus.py:895-897` — append `"researcher"`:
```python
KNOWN_CARD_SLUGS: tuple[str, ...] = (
    "lead", "deputy", "b1", "b2", "b3", "b4", "cortex", "cowork-ah1", "hag-desk", "researcher",
)
```

### AC8 — Brisen Lab server bus.py: _build_terminals_response for-loop (Row 11b)

Edit `~/bm-b1-brisen-lab/bus.py:1005` — append `"researcher"`:
```python
for slug in ("lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk", "researcher"):
```

### AC9 — Brisen Lab server regression tests (Row 11c)

Edit `~/bm-b1-brisen-lab/tests/test_a3_a8_a9_bus.py`:
- Add `test_bus_badge_change_emitted_for_researcher` — mirror existing `test_bus_badge_change_emitted_for_hag_desk` at line ~240; substitute `hag-desk` → `researcher` throughout. Asserts posting to `researcher` emits `bus_badge_change` SSE envelope with the slug in `badges` dict.
- Add `test_v2_terminals_response_includes_researcher` — mirror existing `test_v2_terminals_response_includes_hag_desk` at line ~272. Asserts `/api/v2/terminals` response slugs list includes `researcher`.
- Both tests pattern-lifted from hag-desk fixtures shipped in PRs #27 + #28 (merged 2026-05-22).

### AC10 — Snapshot pusher TERMINALS (Row 12)

Edit `~/bm-aihead1/scripts/forge_snapshot_push.sh:61-70` TERMINALS array — append after hag-desk line:
```bash
  "researcher:/Users/dimitry/bm-researcher"
```

### AC11 — Snapshot pusher regression test (Row 12 supporting)

Edit `~/bm-b1/tests/test_forge_snapshot_push.sh` — add **Case M** (mirror Case L "non-b-code single-clone slug — desk pattern" at lines ~668-701):
- Mirror Case L structure verbatim, substituting `case-l` → `case-m`, `hag-desk` → `researcher`, repo init in `$TMP/case-m-researcher`.
- Asserts: terminal_alias == "researcher", mailbox_status == "n/a", mailbox_brief_name empty.
- Locks in non-b-code single-clone slug contract for Researcher (same shape as Hag Desk).
- Update final line `echo "All 13 cases PASS."` → `echo "All 14 cases PASS."`.

### AC12 — Brisen Lab card render verification (Director-visible surface)

After all three PRs merge AND AH1 post-merge Tier-B (1P key + Render env + redeploy) completes:
1. AH1 fires test bus message: `BAKER_ROLE=lead ~/bm-aihead1/scripts/bus_post.sh researcher "researcher bus install — smoke test" smoke/researcher-online`. Expect HTTP 200 + message_id.
2. AH1 reverse-smoke: from a Researcher-context shell (or simulated `BAKER_ROLE=researcher`), post `ship/research-online` test message to `lead`. Expect HTTP 200.
3. AH1 loads https://brisen-lab.onrender.com/ in Chrome MCP. Expects 10 cards rendered (lead, cowork-ah1, deputy, b1-b4, hag-desk, researcher + cortex system card). Researcher card shows the smoke body in "Just shipped: …" line, badge with unacked_count for AH1's outbound smoke.
4. `/api/v2/terminals` JSON includes `{"slug": "researcher", ...}` entry with `unacked_count > 0` after smoke.

## Out of scope

- AH1 Tier-B post-merge actions — see §Out-of-band Tier-B AH1 actions below. b1 does NOT touch Render or 1Password.
- Other matter desks expansion (AO / MOVIE / BB / Origination / Brisen / AID-T) — Hag Desk + Researcher are the two bus-enabled non-AH/non-B-code agents; broader expansion ratification still pending.
- Auto-heartbeat / mandatory Researcher bus-posting on state changes. Phase 2 if pilot warrants.
- Terminal alias / Terminal.app profile (SOP rows 2-3) — N/A for Cowork-App-only agent.
- Bus_post.sh topic-regex enforcement of Researcher's narrow-topics rule — discipline lives in CLAUDE.md (human-layer), not transport.

## Out-of-band Tier-B AH1 actions (post-merge, NOT b1)

1. `KEY="$(openssl rand -hex 32)"` → generate `researcher` terminal key.
2. `op item create --vault "Baker API Keys" --category=password --title="BRISEN_LAB_TERMINAL_KEY_researcher" password="$KEY"` → 1Password store.
3. Fetch current `BRISEN_LAB_TERMINAL_KEYS` env from Render API on brisen-lab service; add `"researcher": "<key>"` entry; PUT back.
4. `POST /deploys` to brisen-lab service to apply (env PUT alone does NOT restart — known Baker gotcha per SOP foot-gun #5).
5. On MacBook AND Mac Mini (per SOP §Post-merge §3): `cd ~/bm-aihead1 && git pull --rebase origin main && FORGE_KEY="$(plutil -extract EnvironmentVariables.FORGE_KEY raw ~/Library/LaunchAgents/com.baker.forge-snapshot-push.plist)" bash scripts/install_forge_push.sh`.
6. `cp ~/bm-b1/tests/fixtures/session-start-bus-drain.sh ~/.claude/hooks/session-start-bus-drain.sh` (if AC4 fixture-pattern shipped; otherwise the user-global edit landed in-PR already).
7. AC12 end-to-end smoke (fire AH1→researcher + researcher→lead + browser card check).
8. Audit-trail bus-post to `lead` self-post with merge SHAs + smoke result. Self-ack immediately.

b1 ships AC1-AC11 + waits for AH1 to fire AC12 smoke.

## Files touched by b1

**baker-master** (~/bm-b1/):
1. `scripts/bus_post.sh` — AC2 + AC3 (whitelist + role-map case)
2. `scripts/forge_snapshot_push.sh` — AC10 (TERMINALS array)
3. `tests/test_forge_snapshot_push.sh` — AC11 (Case M)
4. `tests/fixtures/session-start-bus-drain.sh` IF it exists — AC4 (mirror of user-global edit)

**baker-vault** (fresh `/tmp/bv-researcher-on-bus/` clone per orientation):
5. `_ops/skills/agent-bus-posting-contract/SKILL.md` — AC5

**brisen-lab** (~/bm-b1-brisen-lab/):
6. `static/index.html` — AC6 (card slot in row-desks)
7. `static/app.js` — AC6 (TERMINALS + TERMINAL_LABELS)
8. `bus.py` — AC7 + AC8 (KNOWN_CARD_SLUGS + for-loop)
9. `tests/test_a3_a8_a9_bus.py` — AC9 (two regression tests)

**Filesystem (no PR — picker + user-global hook):**
10. `~/bm-researcher/CLAUDE.md` — AC1
11. `~/.claude/hooks/session-start-bus-drain.sh` — AC4 (user-global edit; capture diff in ship report)

Branch isolation:
- baker-master edits via `~/bm-b1/` branch `b1/researcher-on-bus-1`.
- baker-vault edits via fresh `/tmp/bv-researcher-on-bus/` clone, branch `b1/researcher-on-bus-1`.
- brisen-lab edits via `~/bm-b1-brisen-lab/` branch `b1/researcher-on-bus-1` (separate clone; same branch name OK across repos).

## API version / deprecation / fallback

- N/A — internal bus + filesystem + Render env. No third-party API touched.

## Migration / bootstrap DDL

- N/A — no schema change. `forge_snapshots.terminal_alias` is `text` (no enum); accepts arbitrary slug.

## Singleton pattern

- N/A — no `SentinelStoreBack` / `SentinelRetriever` instantiation.

## file:line citation verification (b1 MUST verify each at edit time)

- `~/bm-b1/scripts/bus_post.sh:45` — recipient case (current literal: `director|cowork-ah1|lead|deputy|architect|b1|b2|b3|b4|b5|cortex|daemon|aid|hag-desk`).
- `~/bm-b1/scripts/bus_post.sh:55-73` — sender case (currently ends with `hag-desk|HAG-DESK|hagenauer-desk) SENDER=hag-desk ;;` at ~line 67).
- `~/bm-b1/scripts/forge_snapshot_push.sh:61-70` — TERMINALS array (currently ends with `hag-desk:/Users/dimitry/baker-vault` at line 69).
- `~/.claude/hooks/session-start-bus-drain.sh:43-62` — BAKER_ROLE case (currently ends with `hag-desk|HAG-DESK|hagenauer-desk) SLUG=hag-desk ;;` at ~line 55).
- `~/bm-b1-brisen-lab/bus.py:895-897` — KNOWN_CARD_SLUGS tuple.
- `~/bm-b1-brisen-lab/bus.py:1005` — _build_terminals_response for-loop tuple.
- `~/bm-b1-brisen-lab/static/index.html:42-44` — row-desks div (currently 1 article: hag-desk).
- `~/bm-b1-brisen-lab/static/app.js:9` + `:11-16` — TERMINALS array + TERMINAL_LABELS dict.
- `~/bm-b1-brisen-lab/tests/test_a3_a8_a9_bus.py:240-283` — hag-desk test patterns to mirror.
- `~/bm-b1/tests/test_forge_snapshot_push.sh:668-701` — Case L pattern to mirror as Case M.

## Pre-flight grep (defends against SOP foot-gun #1 — three slug-lists)

Before authoring the bus.py edit, b1 MUST run:
```
grep -nE '"lead"\|"deputy"\|"b1"\|"hag-desk"' ~/bm-b1-brisen-lab/bus.py
```
Expect: 2 matches (KNOWN_CARD_SLUGS at ~895 + for-loop at ~1005). If more than 2, surface to AH1 before editing — there may be a new hardcoded site to address.

## Ship gate

Three PRs (one per repo):
- **baker-master PR:** literal `bash tests/test_forge_snapshot_push.sh` green output captured in ship report (14 cases PASS). Plus shellcheck/local-smoke of bus_post.sh whitelist additions (simulate with `BRISEN_LAB_TERMINAL_KEYS='{"researcher":"placeholder"}'` env — expect 401 from real server, confirms client-side whitelist accepts).
- **baker-vault PR:** AC5 SKILL.md edit only. No tests; doc-only PR. `/security-review` skip-eligible per SOP.
- **brisen-lab PR:** literal `pytest tests/test_a3_a8_a9_bus.py -v` green output in ship report (includes 2 new researcher tests + all existing pass).

For AC1 + AC4 (in-place picker + user-global hook edits): capture before/after diffs in ship report. No PR.

Ship report MUST include:
- baker-master PR # + commit anchor
- baker-vault PR # + commit anchor
- brisen-lab PR # + commit anchor
- `~/.claude/hooks/session-start-bus-drain.sh` diff
- `~/bm-researcher/CLAUDE.md` updated content (or path + line count if too long)
- `bash tests/test_forge_snapshot_push.sh` literal output (last 20 lines + PASS line for Case M)
- `pytest tests/test_a3_a8_a9_bus.py -v` literal output (last 20 lines)
- Pre-flight grep output (count check)

## Test plan

1. **Pre-flight grep check** confirms 2 hardcoded slug sites in bus.py (KNOWN_CARD_SLUGS + for-loop). If grep returns >2, escalate before edit.
2. **baker-master local validation:** with `BRISEN_LAB_TERMINAL_KEYS='{"researcher":"placeholder"}'` env, run `BAKER_ROLE=researcher ~/bm-b1/scripts/bus_post.sh lead "test" smoke/local-validation` from `~/bm-b1/`. Expect: argv validation passes; HTTPS POST 401 (placeholder key not registered server-side) — that's fine, confirms client whitelist works. Document the 401 as expected.
3. **baker-master test suite:** `bash tests/test_forge_snapshot_push.sh` → 14 cases PASS (Case M is new).
4. **brisen-lab test suite:** `pytest tests/test_a3_a8_a9_bus.py -v` → all PASS including 2 new researcher fixtures.
5. **Director-side validation (post-merge, AH1+Director):** flagged in ship report as "awaits AH1 Tier-B execution post-merge per AC12."

## Risks / counter-points

1. **Picker proliferation.** `~/bm-researcher/` already exists; this brief adds bus wiring + ~1 card slot. No new picker; net new = 1 cockpit card. Acceptable.
2. **bus.py three-slug-list trap.** This is the foot-gun from hag-desk arc (~2h debug 2026-05-22). SOP §Foot-guns documents it; the pre-flight grep + explicit AC7 + AC8 + AC9 (regression tests covering both KNOWN_CARD_SLUGS + for-loop) defends against re-occurrence.
3. **Cowork-app-only — no Terminal alias.** Unlike all prior installs (B-codes, hag-desk, AH1/AH2), Researcher is opened ONLY via Cowork App folder picker. No `~/.zshrc` function. The risk: if Director opens Cowork picker without `BAKER_ROLE=researcher` env, drain hook silently no-ops (line 60 `exit 0` per drain hook), bus_post.sh refuses sends with "BAKER_ROLE not set". Mitigation: AC1 documents that the Cowork App launcher should set `BAKER_ROLE=researcher`; if it can't, Researcher's CLAUDE.md instructs the agent to `export BAKER_ROLE=researcher` before any bus action.
4. **Researcher Tier-A discipline not enforced by bus_post.sh.** Researcher could in principle bus-post anything (Tier-B asks, dispatches) — bus is a dumb pipe. Discipline lives in orientation + CLAUDE.md. Acceptable trade-off (consistent with hag-desk model); revisit if Researcher misuses bus.
5. **Bus is now 10 slugs (was 9).** Devil's advocate note from initial design: at some point this scales poorly. Not a reason to block; refactor when 15+ slugs land.

## Gate-1 + Gate-2 reviewer instructions

Reviewers MUST load `https://brisen-lab.onrender.com/` after the brisen-lab PR merges AND AH1 Tier-B post-merge (1P key + Render env + redeploy) completes. Confirm:
- Card renders in `row-desks` next to Hag Desk (10 cards total including Cortex system card).
- Pre-smoke (AC12 not yet fired): grey state, "no bus traffic."
- Post-smoke: green state, "Just shipped: …" line with smoke body.

Code-shape review (syntactically valid HTML/JS, XSS-safe via `createElement + textContent` pattern preserved, no breaking changes to existing tests) necessary but NOT sufficient — the routing semantic must be verified by literal browser load.

## Reporting

- Bus-post `lead` on each of 3 PR opens (topic `pr-open/researcher-on-bus-1`).
- Bus-post `lead` on ship-complete with all 3 anchors + filesystem state.
- Ship report file: `briefs/_reports/B1_RESEARCHER_ON_BUS_1_20260522.md`.

## Anchors

- 2026-05-22 chat — Director "Install Researcher on Brisen Lab" + 4 ratifications (slug=researcher, row-desks placement, send-capable narrow topics, CLAUDE.md update bundled).
- Sister/template arc: HAGENAUER_DESK_ON_BUS_1 (PR #237 baker-master + PR #25 brisen-lab + PR #103 baker-vault merged 2026-05-21) + 3 follow-on fixes (PR #238 + #27 + #28 merged 2026-05-22) that produced the SOP.
- SOP canonical: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` (ratified 2026-05-22).
- COWORK_AH1_VISIBILITY precedent (Path B refactor 2026-05-18) — cowork-only agent install pattern.

## Co-Authored-By

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
