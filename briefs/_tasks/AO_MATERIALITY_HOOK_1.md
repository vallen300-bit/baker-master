# AO_MATERIALITY_HOOK_1 — enforce profile-read before AO-desk material advice

**Status:** AUTHORED — dispatch via deputy (program orchestrator). Pulled forward from AO_PROFILE_PROGRAM_1 wave 5 on Director GO 2026-07-09 PM (live MOVIE negotiation coming; profile v2.1 already good enough to gate on).
**Author:** cowork-ah1. **Routing:** `dispatched_by: deputy` — deputy assigns a B-code and receives the ship report (cowork-ah1 is App-resident, cannot monitor autonomously).
**Anchor:** Director 2026-07-09 — Option 5 ("cannot produce material advice unless he reads the profile") + materiality definition ratified with the program GO.

## Context

The AO psychological profile + reciprocity ledger now live in `wiki/matters/oskolkov/curated/` (profile v2.1, ledger v1.2, authorized-figures table — Director-corrected @443bb04, desk-only). Option 5 is ratified process (read-before-advise, write-after-contact) but **nothing enforces it** — the desk *should* consult the profile, but no gate blocks material advice that skips it. Director asked whether consultation is actually wired in; honest answer today is "convention, not enforced." This brief builds the enforcement.

Desk harness lives in the ao-desk picker (`~/bm-cowork-ao-desk/` + terminal `~/bm-ao-desk/` if present): `CLAUDE.md` + `.claude/settings.local.json`; canonical desk state in vault `_ops/agents/ao-desk/` (OPERATING.md carries the corrections back-prop). Hook precedents: `recommendation-check.sh`, `end-cue-check.sh`, `brief_sop_check.sh` — all Stop/PostToolUse gates that scan the reply/transcript and `decision:block` on violation.

## Problem

AO-desk can emit Director-facing material advice without having read the profile in-session. On a EUR 73.5M relationship with a live shadow-equity negotiation, advice ungrounded in the corrected profile + reciprocity ledger is exactly the failure the profile exists to prevent. Need a deterministic gate: material advice is blocked unless the profile was actually read this session.

## Design (recommended — builder may refine within the contract)

Two-part gate, judgment + deterministic enforcement (engineering rule: AI for judgment, code for enforcement):

1. **Materiality classification = desk self-declaration (judgment).** The desk process (SKILL/CLAUDE.md) requires every Director-facing advice reply to carry a machine-readable tag: `AO-MATERIAL: yes|no` +, when yes, `PROFILE-READ: <profile filename> as-of <commit-or-mtime>`. Materiality definition (Director-ratified v1):
   - (M1) money impact ≥ EUR 250,000;
   - (M2) any equity / security / deal-structure change;
   - (M3) any outbound draft to AO or his circle (Constantinos, Edita-as-AO-channel, Aelio admin);
   - (M4) any negotiation position or strategy call.
   Routine status / reconciliation / figure lookups = `AO-MATERIAL: no`, ungated.
2. **Enforcement = deterministic Stop hook (code).** `ao-material-profile-gate.sh` in the ao-desk picker `.claude/settings.json` Stop hook:
   - reads the assistant's final reply for the `AO-MATERIAL:` tag;
   - if tag missing on any Director-facing reply → `block` with "declare AO-MATERIAL: yes|no";
   - if `AO-MATERIAL: yes` → scan the session transcript for a `Read` tool call on a path matching the profile/ledger files in `wiki/matters/oskolkov/curated/` (profile v2.x, ledger v1.x, authorized-figures). If no such Read this session → `block` with "material AO advice requires reading the profile first: <paths>";
   - if read present → pass. Fail-open ONLY on hook-internal error (log + allow), never silently on a missing read.

## Files Modified

- `~/bm-cowork-ao-desk/.claude/hooks/ao-material-profile-gate.sh` (NEW — the gate) + terminal picker `~/bm-ao-desk/.claude/hooks/…` if that picker exists (mirror).
- `~/bm-cowork-ao-desk/.claude/settings.local.json` (+ terminal mirror) — register the Stop hook.
- ao-desk `CLAUDE.md` (picker) — the `AO-MATERIAL:` / `PROFILE-READ:` declaration rule + materiality M1–M4 definition.
- vault `_ops/agents/ao-desk/OPERATING.md` — one line: gate live, mechanism pointer (cascade back-prop).
- Test: `tests/` under the picker or a standalone bats/shell test for the hook (see Verification).

## Verification

- **Hook unit tests (deterministic, required):** (1) reply with no tag → blocked; (2) `AO-MATERIAL: no` → passes with no read; (3) `AO-MATERIAL: yes` + transcript has a profile Read → passes; (4) `AO-MATERIAL: yes` + NO profile Read → blocked; (5) hook-internal error → fail-open + logged. Feed synthetic transcripts; assert exit codes / `decision` JSON.
- **Live smoke:** in the ao-desk picker, ask a material question (e.g. "should we offer AO 51% for EUR 20M?") without reading the profile → expect block; read the profile, retry → expect pass.
- **False-positive check:** a routine "what's AO's current total?" tagged `no` must pass ungated (it's a figure lookup, not advice).
- Ship report answers the done rubric, not just "tests pass."

## Quality Checkpoints / Acceptance criteria

1. Material advice (M1–M4) is blocked unless the profile/ledger was Read in-session — proven by the unit tests + live smoke.
2. Non-material replies pass ungated (no workflow tax on routine desk ops).
3. Materiality definition M1–M4 + declaration rule documented in ao-desk CLAUDE.md.
4. Gate mirrored across both ao-desk pickers (cowork + terminal) if both exist.
5. Fail-loud: missing tag blocks; only hook-internal errors fail-open, and they log.
6. ao-desk OPERATING.md notes the gate is live (cascade back-prop clean).

## Gate plan

Standard B-code chain: codex G3 (or deputy G2 if codex busy) on the hook logic + tests → deputy verifies ship report against the done rubric → deputy confirms live smoke → merge (desk-harness change, no baker-master prod deploy). Report routes to deputy.

### Surface contract

N/A — desk-harness hook + process-doc change; no Director-facing UI surface. The only "surface" is the block message text (must name the profile paths to read).

Harness-V2: Context / Problem / Files Modified / Verification / Quality Checkpoints present; task class = small harness build; done rubric = Quality Checkpoints above; gate plan above.
