# BOX5_OUTBOUND_CLICKUP_STATUS_MAPPING_1

**Owner:** lead (AH1) · **Builder:** b-code · **Gate:** codex G3 (HIGH) → lead G4 /security-review
**Source:** b4 live canary #4894 (2026-07-01) — correlation fix (PR #448) proven live end-to-end; a *separate* new blocker surfaced.

## Problem

The outbound connector maps every ratification to one of five hardcoded ClickUp
workflow statuses (`_clickup_status()` → `Ready for Baker Relay` / `Packet Draft` /
`Waiting Reply` / `Needs Director` / `Closed`). Matter timetable lists do NOT carry
those statuses. Live proof: writing to list `901524194809` ('BB-AUK-001 Timetable',
BAKER Space) returns `400 {"err":"Status not found","ECODE":"CRTSK_001"}` — **every**
outbound ratification write to that list fails.

Zero overlap:
- List statuses: `to do, planning, in progress, at risk, update required, on hold, waiting, blocked, complete, cancelled`.
- Connector requires: `Ready for Baker Relay, Packet Draft, Waiting Reply, Needs Director, Closed`.

The connector currently degrades SAFELY on this (records `clickup_write_failed_no_id`
→ `CLICKUP_BLOCKED`, no crash, no residue) — so this is **not urgent**, but the
end-to-end write path stays blocked until fixed.

## Root cause

The connector's five statuses are a *Baker-relay workflow* vocabulary. Matter-owned
timetable lists own their own status vocab (deliberately — baden-baden-desk chose a
dedicated list so auto-generated tasks stay isolated from curated tracks). The
connector must **adapt to each list's real statuses**, not impose its own. Directive
(Rule): matter timetable lists own their status vocab.

## Design (target)

Introduce a status-resolution layer that decouples the connector's internal canonical
states from the literal ClickUp status strings, resolved per target list.

1. **Canonical states unchanged.** Keep the five internal states as the decision output
   of `_clickup_status()` — treat them as canonical keys, not literal ClickUp strings.
2. **`_resolve_clickup_status(list_id, canonical_state) -> str`.** New function. Returns
   the actual ClickUp status string to send for that list:
   - Per-list override map (keyed by `list_id`) if present, else a module-level DEFAULT
     map targeting standard ClickUp statuses.
   - DEFAULT map (b4-proposed, targets statuses present on BB-AUK-001 Timetable):
     `Ready for Baker Relay → "in progress"`, `Packet Draft → "to do"`,
     `Waiting Reply → "waiting"`, `Needs Director → "at risk"`, `Closed → "complete"`.
     (Builder: confirm these five targets are ClickUp-common defaults; adjust with
     evidence if any is not.)
3. **Config location:** module-level dicts for now (`_DEFAULT_STATUS_MAP` +
   `_PER_LIST_STATUS_MAP = {"901524194809": {...}}`). **No migration** — do NOT add a
   project_registry column this increment (keep it reversible; a config-table design is
   a later brief if more matter lists appear).
4. **Fault-tolerance preserved (HARD).** If a resolved status is still not accepted by
   the list (400 "Status not found"), the connector MUST degrade exactly as today →
   `CLICKUP_BLOCKED`, no crash, no silent drop, no residue. Never regress the safe path.
5. **Connector stays behind the existing flag.** No activation change in this brief.

## Constraints

- Surgical: touch only `orchestrator/airport_outbound_connector.py` + its test file.
- All DB/API calls wrapped in try/except (repo hard rule).
- Never write outside BAKER Space (901510186446); ≤10 writes/cycle (unchanged).
- No migration. No dashboard edits. Connector remains DARK/flagged as-is.
- `.claude/rules/python-backend.md` applies.

## Acceptance criteria

1. `_resolve_clickup_status("901524194809", <each canonical state>)` returns a status
   present in the BB-AUK-001 Timetable list vocab (the 10 listed above).
2. Unknown `list_id` → DEFAULT map applies (no KeyError, no crash).
3. A create against a list missing the resolved status still degrades to
   `CLICKUP_BLOCKED` (fault-tolerant path unchanged) — assert no exception propagates.
4. Existing 16 ACs + prior regression tests stay green.
5. `scripts/check_singletons.sh` OK; `py_compile` clean.

## TDD plan (repro-first)

1. Repro: a fixture/unit asserting the pre-fix connector sends `"Ready for Baker Relay"`
   for an approval → would 400 on a timetable-status list. Show it maps to a
   list-present status post-fix.
2. Per-state mapping test: each canonical state → a status in the timetable vocab.
3. Default-map fallback test: unknown list_id resolves via DEFAULT map.
4. Fault-tolerance regression: resolved status still absent → `CLICKUP_BLOCKED`, event
   completes, zero residue, no raise.

## Out of scope

- ClickUp-side reconfiguration of list 901524194809 (rejected — would overwrite the
  timetable vocab baden-baden-desk designed).
- project_registry schema change / config table (later brief if needed).
- Connector activation / flag flip.
- Re-running the live canary — lead orchestrates that after merge.

## Gate

G1 (builder self-verify: full box5/airport/dispatcher suite + new tests) → **codex G3,
effort HIGH** (live ClickUp write path) → **lead G4 /security-review** → lead merge →
lead re-runs b4-style live canary to close A-21 POST_DEPLOY_AC.
