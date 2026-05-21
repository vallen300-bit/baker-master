---
brief_id: HAGENAUER_DESK_ON_BUS_1
target: b1
target_repo: baker-master (primary) + baker-vault (skill update) + filesystem (picker + drain hook)
matter_slug: baker-internal
dispatched_by: lead
reply_to: lead
priority: tier-b
deadline: 2026-05-22T18:00:00Z
authored_at: 2026-05-21T14:15:00Z
---

# BRIEF_HAGENAUER_DESK_ON_BUS_1 — wire Hag Desk onto Brisen Lab bus

### Surface contract: N/A — backend bus wiring + picker config + skill text edits, no clickable surface.

## Problem

Hag Desk is currently bus-less. All AH1 ↔ Hag Desk coordination relays through Director paste-blocks. With the Tuesday 2026-05-26/27 Hagenauer filing deadline + 7-item parked queue (§JJ) Hag-Desk-owned, Director-relay is the friction. Putting Hag Desk on the bus = direct routing, drain on session-open, heartbeat-able.

This is a single-desk pilot. Other matter desks (AO / MOVIE / BB / Origination / Brisen / AID-T) stay off-bus until Hagenauer-arc proves the pattern.

## Slug + naming

- Bus slug: `hag-desk` (matches short-slug convention: `lead` / `deputy` / `b1`-`b4` / `aid` / `architect` / `cortex` / `cowork-ah1`).
- Picker dir: `~/bm-hag-desk/` (mirrors `~/bm-ben/` pattern — plain folder with CLAUDE.md, no git clone).

## Acceptance criteria (testable)

1. **bus_post.sh accepts `hag-desk`** as both recipient AND sender (via `BAKER_ROLE=hag-desk`). Whitelist line + role-mapping case both updated. Path: `~/bm-b1/scripts/bus_post.sh` (baker-master).
2. **session-start-bus-drain.sh accepts `BAKER_ROLE=hag-desk`** at the case statement (~line 43). Path: `~/.claude/hooks/session-start-bus-drain.sh` (user-global, no repo — in-place edit).
3. **Picker `~/bm-hag-desk/` created** with `CLAUDE.md` containing:
   - Tier 0 mandatory reads: `~/.claude/skills/hagenauer-desk/SKILL.md` (canonical Hag Desk SKILL) + `~/baker-vault/_ops/agents/hagenauer-desk/OPERATING.md` + `~/baker-vault/_ops/agents/hagenauer-desk/filing-protocol.md` (filing protocol installed today) + canonical Baker memory at `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md`.
   - First-message confirmation phrase (evidence-bound, exact): `"Hag Desk oriented (Tier 0). Read: hagenauer-desk/SKILL.md, OPERATING.md, filing-protocol.md, MEMORY.md."`
   - Block applies when cwd path is `/Users/dimitry/bm-hag-desk`.
   - Pattern: mirror `~/bm-ben/CLAUDE.md` structure (Tier 0/1/2/3 access model + bus role wiring).
4. **agent-bus-posting-contract SKILL.md updated** at `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md` (+ Cowork mirror via inode hardlink to verify or `cp`): note Hag Desk is now bus-enabled (pilot scope — other matter desks remain off-bus pending Hagenauer-arc proof).
5. **Smoke test PASS:** from `cd ~/bm-hag-desk && BAKER_ROLE=hag-desk ~/Desktop/baker-code/scripts/bus_post.sh lead "hag-desk bus pilot online — smoke test" smoke/hag-desk-bus-pilot` → returns HTTP 200 + `message_id` + the post is visible in lead's inbox via `curl -s -H "X-Terminal-Key: $LEAD_KEY" https://brisen-lab.onrender.com/inbox/lead?since=...`. Capture the message_id in the ship report.
6. **Reverse smoke test PASS:** from `~/bm-aihead1/` (BAKER_ROLE=lead), `bus_post.sh hag-desk "ack — Hag Desk pilot live" pilot/hag-desk-online` → returns HTTP 200; confirms `hag-desk` accepted as recipient slug.

## Out of scope

- Render env update (Tier-B; **AH1 executes post-merge** — slug key generation + 1Password storage + Render PUT + redeploy + smoke fire).
- Other matter desks expansion (AO / MOVIE / BB / Origination / Brisen / AID-T).
- Hag Desk SessionStart drain hook wiring (covered by ACs 2 + 3 — drain script already exists; picker just needs to set `BAKER_ROLE=hag-desk` in env).
- Auto-heartbeat / mandatory Hag Desk bus-posting on Hag Desk state changes. Phase 2 if pilot warrants.

## Out-of-band Tier-B AH1 actions (post-merge, NOT b1)

1. `openssl rand -hex 32` → generate `hag-desk` terminal key.
2. `op item create` in 1Password Brisen vault — title `baker-bus-terminal-key-hag-desk`, store key as password field.
3. Fetch current `BRISEN_LAB_TERMINAL_KEYS` env from Render API; add `"hag-desk": "<key>"` entry; PUT back.
4. `POST /deploys` to brisen-lab service to apply.
5. AH1 fires AC5 + AC6 smoke tests after deploy + records anchors.

b1 does NOT touch Render or 1Password. b1 ships AC1-AC4 + waits for AH1 to fire AC5/AC6.

## Files touched by b1

1. `~/bm-b1/scripts/bus_post.sh` (baker-master) — whitelist + role-mapping case for `hag-desk`.
2. `~/.claude/hooks/session-start-bus-drain.sh` (user-global, in-place) — case statement add.
3. `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md` (baker-vault) — Hag Desk pilot scope note.
4. `~/bm-hag-desk/CLAUDE.md` (filesystem, new dir+file) — picker.

Branch isolation: use a fresh `/tmp/bv-hag-desk-bus-pilot/` clone for any baker-vault edits per orientation. baker-master edits via `~/bm-b1/` working branch `b1/hagenauer-desk-on-bus-1`.

## API version / deprecation / fallback

- N/A — internal bus + filesystem + Render env. No third-party API touched.

## Migration / bootstrap DDL

- N/A — no schema change.

## Singleton pattern

- N/A — no `SentinelStoreBack` / `SentinelRetriever` instantiation.

## file:line citation verification

- `scripts/bus_post.sh:44` — whitelist case statement (`director|cowork-ah1|lead|deputy|architect|b1|b2|b3|b4|b5|cortex|daemon|aid`). Verify the literal at line 44 before editing.
- `scripts/bus_post.sh:54-66` — role-mapping case. Verify the existing AH1/AH2/B-code/architect/cortex/aid mappings before adding `hag-desk|HAG-DESK|hagenauer-desk` → `SENDER=hag-desk`.
- `~/.claude/hooks/session-start-bus-drain.sh:43` — case statement mirror. Verify before editing.

## Ship gate

Two PRs (one per repo touched):
- **baker-master PR:** AC1 only. CI green (no test changes; only script change). Literal smoke fire from local clone with simulated `BRISEN_LAB_TERMINAL_KEYS` (use dev mode env JSON `{"hag-desk":"test-key-12345"}`) to confirm whitelist + role-map both accept `hag-desk`. Capture stdout in ship report.
- **baker-vault PR:** AC4. Skill update. No tests.

For AC2 + AC3 (in-place user-global edits + new picker dir) — capture before/after diff + filesystem state in ship report. No PR.

Ship report MUST include:
- baker-master PR # + commit anchor
- baker-vault PR # + commit anchor
- `~/.claude/hooks/session-start-bus-drain.sh` diff
- `~/bm-hag-desk/CLAUDE.md` content (or path + line count if too long)
- Local smoke output (with placeholder key)

## Test plan

1. After bus_post.sh + drain-hook edits, run from `~/bm-b1/` with `BRISEN_LAB_TERMINAL_KEYS='{"hag-desk":"placeholder"}'` env override:
   ```
   BAKER_ROLE=hag-desk ~/bm-b1/scripts/bus_post.sh lead "test" smoke/local-validation
   ```
   Expect: argv validation passes; the actual HTTPS POST will 401 (placeholder key not registered) — that's fine, confirms client-side whitelist works. Document the 401 as expected.

2. From `~/bm-hag-desk/` (after picker CLAUDE.md is created), Director opens Cowork picker → Hag Desk session — verify Tier 0 confirmation phrase fires + drain hook reads inbox for `hag-desk`. (Director-side validation; b1 cannot fire this — flag in ship report as "awaits AH1 + Director validation post-Render-env update".)

## Risks / counter-points

1. **One-desk inconsistency.** Fleet now has `hag-desk` on bus but other 6 desks off. Acceptable per Director directive ("Hag Desk only first" per AH1 conversation 2026-05-21). Fast-follow brief expands to remaining desks if pilot clean.
2. **Picker proliferation.** `~/bm-hag-desk/` adds one more folder to Director's Cowork picker dropdown. Inevitable cost of bus enablement; same pattern that landed `bm-ben` / `bm-aihead2` / etc.
3. **Drain-hook noise.** Hag Desk sessions will get inbox-drain output at SessionStart. Standard pattern — same as all other on-bus pickers.

## Reporting

- Bus-post `lead` on PR open (each PR — baker-master + baker-vault).
- Bus-post `lead` on ship-complete with anchors.
- Ship report file: `briefs/_reports/B1_HAGENAUER_DESK_ON_BUS_1_20260521.md`.
