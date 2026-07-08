# BRIEF: LIBRARIAN_AGENT_INSTALL_1 — install the ratified Librarian domain agent (slug `librarian`)

## Context
Director ratified SPEC_LIBRARIAN_AGENT_v1 2026-07-08 ~17:40Z (codex-arch G0 PASS after #7416/#7433 folds).
The fleet has no internal-retrieval specialist: B-codes get misused for doc-hunts, Clerk-Qwen lookup is
unreliable, Researcher is external-web only. Anchor incident: AO_FLIGHT_BOND_SOURCE_DATE_1 (BREC2 bond
issuance date hunt had no clean seat).

Canonical spec (source of truth, READ IT FIRST):
`~/baker-vault/_ops/build/baker-os-v2/05_outputs/domain-agent-program/SPEC_LIBRARIAN_AGENT_v1.md`
Install SOP (canonical, READ SECOND): `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md`
(14-row map — this brief enumerates every row below; SOP text wins on any conflict of mechanics).

### Surface contract
- Surface: ONE new card on https://brisen-lab.onrender.com (engine-room ops view, Pattern C/D dark register — NOT a Director report surface).
- Slot: `<article class="card card-desk" data-alias="librarian"></article>` in `static/index.html`, specialist row (same row as `researcher`, immediately after it).
- Label: `LIBRARIAN` in `app.js` LABELS dict; slug appended to `app.js` TERMINALS array (order = row order).
- States: standard card contract only (heartbeat amber / unread badge blue / git+mailbox columns via snapshot pusher). No new CSS, no new interactions, no layout changes to other cards.
- Click behavior: standard wake chain (Rows 13/14) — nudge existing `~/bm-librarian` Terminal tab, else spawn via `librarian()` fn.
- Parity rule: Terminal profile name = card alias = `LIBRARIAN` (Director parity principle).
- No other UI surface is touched by this brief (no dashboards, no Director-facing pages).

## Estimated time: ~3-4h (SOP floor ~30 min is for plain desks; librarian adds cage + tests + receipt-check script)
## Complexity: Medium-High (3 repos + user-global hooks + seat cage)
## Prerequisites: none — all gates passed, spec ratified. deputy G2 + codex G3 before lead merge.

## Harness V2
- **Task class:** new-agent install (multi-repo wiring + seat cage + offline acceptance). Production-facing.
- **Context Contract:** b1 loads EXACTLY: (1) this brief, (2) SPEC_LIBRARIAN_AGENT_v1.md, (3) install-agent-to-
  brisen-lab-sop.md, (4) referenced cage patterns read-only (researcher PR #143 wrapper, hag-filer ACL guard).
  Nothing else is in-context scope; matter content is NOT needed (BREC2 hunt runs THROUGH the installed seat).
- **Done rubric (done-state class: deployed-verified):** DONE = all 3 PRs merged in SOP order + all 14 rows
  shipped-or-N/A'd + 4 seeded-violation tests literal-output PASS + crash-unacked test PASS + AC12 smoke incl.
  visual + rung-1 findings notes (8-10, receipt-check PASS, BREC2 conflicts HARD-FLAGGED) + lead
  POST_DEPLOY_AC_VERDICT posted. Anything less = NOT done; report the gap, never round up.
- **Gate plan:** see §Gate plan below (deputy G2 → codex G3 high → lead merge → Tier-B post-merge → verdict).

## Baker Agent Vault Rails
Relevant: bus-and-lanes, verification-surfaces, skills-and-playbooks, standing-contract.
Ignored: loop-runner (librarian is bus-triggered, no cron), memory-and-lessons (no auto-memory for v1).

---

## Part A — 14-row wiring map (every row addressed; SOP §"Brief authoring template" ACs apply verbatim)

- **Row 0 (AC0) pre-flight:** run existing-workspace audit (`ls ~/bm-* | grep -i libr` + Dropbox variant +
  `grep -i libr ~/.zshrc`). Expected: no prior workspace. If one surfaces, STOP and post to lead.
- **Row 1:** picker `~/bm-librarian/` via `bash scripts/install_picker_dir.sh librarian` (local, no --dropbox —
  terminal seat). Register slug in `_snapshot_path_for()` in `scripts/generate_agent_identity_artifacts.py`
  (explicit `~/bm-librarian`), run `--write`, commit regenerated artifacts. Treat generator stderr WARNING as gate.
- **Row 2:** `~/.zshrc` function `librarian()` — cd `~/bm-librarian`, `BAKER_ROLE=librarian`,
  `FORGE_TERMINAL=librarian`, git-pull-rebase soft, launch claude. Model pin: launch with Sonnet
  (`claude --model claude-sonnet-4-6`) per spec §5 — Sonnet-pinned, never self-upgrades.
- **Row 3:** Terminal.app profile "LIBRARIAN" via `.terminal` + `open` import (live menu, no relaunch).
  Name MUST equal dashboard card alias exactly.
- **Row 4:** picker `CLAUDE.md`: Tier-0 = spec §1 charter + `wiki/_library/data-surface-map.md` (cached prefix)
  + first-message confirmation phrase; dispatch protocol via `~/bm-b1/scripts/bus_post.sh` (canonical path,
  never Desktop). Include spec §1 task boundaries verbatim (no interpretation / no external web / no writes
  outside `wiki/_library/**` / ambiguous ticket → bounce).
- **Rows 5+6:** `scripts/bus_post.sh` recipient case + `BAKER_ROLE=librarian → SENDER=librarian` case.
- **Row 7:** `~/.claude/hooks/session-start-bus-drain.sh` BAKER_ROLE case + canonical fixture
  `tests/fixtures/session-start-bus-drain.sh` (both).
- **Row 8:** 1P key `BRISEN_LAB_TERMINAL_KEY_librarian` — `--category="API Credential"` with `credential=` field
  (Lesson #78 — pre-flight the category check). Lead executes post-merge (Tier-B).
- **Row 9:** Render `BRISEN_LAB_TERMINAL_KEYS` JSON + explicit POST /deploys after PUT. Lead executes post-merge.
- **Row 10:** brisen-lab front-end per Surface contract block above.
- **Row 11 (FOUR places):** `bus.py KNOWN_CARD_SLUGS` + `bus.py _build_terminals_response()` loop +
  `app.py TERMINALS` + regression tests in `tests/test_a3_a8_a9_bus.py`. Pre-flight grep per SOP.
- **Row 12:** `scripts/forge_snapshot_push.sh` TERMINALS — repo-path `~/baker-vault` (picker has no .git;
  hard rule, RESEARCHER_ON_BUS_1 anchor) + `tests/test_forge_snapshot_push.sh` case.
- **Row 13 (BOTH maps):** wake-handler `fnMap` `{"librarian","librarian"}` + `cwdForAlias` →
  `/Users/dimitry/bm-librarian`. Lead rebuilds wake-handler post-merge.
- **Row 14:** wake-listener `ALLOWED_ALIASES` + deployed-copy diff before patching. Lead kickstarts listener post-merge.
- **Plus:** agent-bus-posting-contract SKILL.md desk list — N/A — librarian is NOT a posting peer
  (G0 F1 carve-out: reply-same-thread + ack only). Document the carve-out where the list lives instead.

Three-repo PR sequencing per SOP: baker-vault first (`_ops/agents/librarian/` orientation + `wiki/_library/`
scaffold incl. `data-surface-map.md` seed + `findings/` dir), baker-master second, brisen-lab third.

## Part B — Librarian cage (spec §2 structural enforcement; this is what makes it a librarian, not a desk)

### Problem
Spec requires allow-list-by-absence: tools outside spec §1 list must be IMPOSSIBLE, not forbidden-by-prose.

### Current State
No seat config exists. Reference cages: researcher git wrapper (baker-vault PR #143), hag-filer ACL guard
(`render_acl_guard.sh` reuse pattern, b3 3f75273), publisher render ACL (shadow mode).

### Engineering Craft Gates
- Diagnose: N/A — new install, no defect.
- Prototype: N/A — spec ratified; cage patterns proven on researcher/hag-filer lanes.
- TDD: applies — seeded-violation tests (a)-(d) below written FIRST, must demonstrate the violation succeeds
  against an uncaged control config and is REJECTED against the caged seat.

### Implementation
1. `~/bm-librarian/.claude/settings.json` permissions: deny-by-default; allow ONLY the spec §1 callables
   (exact list — copy from spec, includes the #7433 `baker_clickup_tasks` fix; read-only Read/Grep/Glob;
   Bash restricted to the wrapper scripts below + curl GET to the two accessor endpoints).
2. `librarian_sql` wrapper script (`~/bm-librarian/scripts/librarian_sql.sh` → `baker_raw_query`):
   rejects any statement not starting with SELECT (after comment/whitespace strip); appends LIMIT 500
   if absent. `baker_raw_write` NOT in allow-list anywhere.
3. Vault-write cage: `baker_vault_write` helper caged to `wiki/_library/**` — PreToolUse hook rejects
   any other path (reuse hag-filer ACL guard pattern).
4. Bus carve-out (G0 F1): posting allowed ONLY via reply-same-thread (`bus_post.sh` with thread id of an
   inbound hunt ticket) + ack. Enforce in a thin wrapper (`librarian_bus_reply.sh`) that requires a thread id
   argument and validates it exists in own mailbox; raw bus_post.sh NOT in seat allow-list.
5. `internal-receipt-check` script (spec §4): `_ops/agents/librarian/librarian_receipt_check.py` (baker-vault)
   — for each claim line, re-fetch named source, confirm verbatim quote present; verify receipt block +
   MISS section present. Exit non-zero on any claim missing quote+source. Deterministic, no LLM.
6. Ack discipline (spec §2): drain wrapper acks a hunt ONLY after findings file + bus reply + receipt-check PASS
   (or explicit bounce). Seeded test: simulated crash before reply leaves ticket unacked.
7. maxTurns 40 per hunt; per-wake cap 3 hunts; queue-age >24h tripwire posts to lead (cheap check in drain wrapper).
8. Kill switch: `LIBRARIAN_DISABLED=true` env checked at seat start + in drain wrapper (2-min flip, spec §7).

### Seeded-violation tests (spec §2 — ALL FOUR mandatory, literal test output in PR)
(a) write attempt to `wiki/matters/**` → REJECTED; (b) `baker_raw_write` call → impossible (not resolvable);
(c) non-SELECT through `librarian_sql` → REJECTED; (d) bus post to NEW thread or third party → REJECTED.

### Key Constraints
- Do NOT touch researcher/publisher/hag-filer cages — reuse patterns by copy, not by edit.
- No writes outside `wiki/_library/**` + `_ops/agents/librarian/` anywhere in this install.
- Never put key material in any committed file (Row 8/9 values are lead-executed post-merge).
- Spec text is ratified — implement it, do not redesign it. Deviations → bus to lead first.

## Part C — Rung-1 offline acceptance (spec §6.1; shadow + live rungs are LATER briefs, not this one)

8-10 seeded hunts with known answers across ≥5 surfaces (email, KBL/Qdrant, ClaimsMax, transcripts, vault,
WhatsApp, SQL). **Acceptance hunt #1 = live BREC2 case exactly as spec §6.1:** BREC2 securitization-notes
issuance/subscription date + face amount + coupon, verbatim quotes (candidate: AO_MASTER
"…securitization notes (3).pdf", matter=ao); compare vs Opus €12M Gesamtgrundschuld (reg. 2020-09-28);
HARD-FLAG conflicts, do NOT decide which source controls (G0 F3). Findings note per spec §1 output format;
receipt-check PASS required. Deliver the 8-10 findings notes under `wiki/_library/findings/` as rung-1 evidence.

## Files Modified
- baker-vault: `_ops/agents/librarian/` (orientation.md, receipt-check script), `wiki/_library/` scaffold
- baker-master: `scripts/bus_post.sh`, `scripts/forge_snapshot_push.sh` + test, `scripts/generate_agent_identity_artifacts.py`
  + regenerated artifacts, `tests/fixtures/session-start-bus-drain.sh`
- brisen-lab: `static/index.html`, `static/app.js`, `bus.py`, `app.py`, `tests/test_a3_a8_a9_bus.py`,
  `tools/wake-handler/wake-handler.applescript`, `tools/wake-listener/wake-listener.py`
- local (lead-verified post-merge): `~/.zshrc`, Terminal plist, `~/.claude/hooks/session-start-bus-drain.sh`,
  `~/bm-librarian/` seat files

## Do NOT Touch
- `baker-vault/slugs.yml` — librarian is an agent, not a matter slug.
- Existing cages (researcher/hag-filer/publisher) — copy patterns, never edit their files.
- `tasks/lessons.md` existing entries — append-only.
- Clerk-Qwen lane retirement + HR directory row — Wave follow-up, NOT this brief (spec §6.3 is the LIVE rung).

## Quality Checkpoints
1. All 14 rows shipped or `N/A — reason` in the ship report; zero silent omissions.
2. Literal pytest/bash output for brisen-lab bus tests + forge pusher tests in PR description.
3. All 4 seeded-violation tests demonstrated with literal output.
4. Crash-before-reply leaves hunt UNACKED (test evidence).
5. AC12 smoke incl. visual browser check (card renders in HTML payload).
6. Rung-1: 8-10 findings notes, receipt-check PASS each, BREC2 hunt conflicts HARD-FLAGGED not resolved.
7. Cost telemetry line present in every receipt block (spec §5).

## Verification SQL
```sql
-- after install, hunt tickets visible in bus store (brisen-lab DB):
SELECT id, from_terminal, topic, acknowledged_at FROM brisen_lab_msg
 WHERE 'librarian' = ANY(to_terminals) ORDER BY id DESC LIMIT 20;
```

## Gate plan
b1 builds → deputy G2 (on-disk verify) → codex G3 (`gate/librarian-install-g3`, recommended
reasoning_effort=high — new agent seat + cage) → lead merges 3 repos in SOP order → lead executes
Tier-B post-merge checklist (Rows 3/8/9/13/14 + pusher redeploy both hosts) → AC12 smoke →
rung-1 acceptance evidence → lead posts POST_DEPLOY_AC_VERDICT → Director notified; shadow rung scheduled.
