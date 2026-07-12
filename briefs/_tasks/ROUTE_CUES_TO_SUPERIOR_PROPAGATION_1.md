# ROUTE_CUES_TO_SUPERIOR_PROPAGATION_1

**Dispatched:** 2026-07-12 · **Lane:** b3 · **Origin:** Director directive #6727 (2026-07-07) → deputy diagnosis + codex-deputy second-opinion #9160 → lead ratified split #9161.

Harness-V2: N/A — hook/orientation propagation across picker repos, no baker-master production code; probes below serve as the done gate.

## Context

Standing directive #6727: workers route permission cues to their `reports_to` superior, not Director. Deputy diagnosed why it never took (rule banked in memories only; loader injects laconic-default just for `deputy|aihead2`; end-cues Director-addressed by construction). Codex-deputy second opinion #9160 returned PASS-WITH-CHANGES with 5 binding guardrails (folded into Constraints). Deputy owns the canonical clause wording; this brief propagates it.

## Problem

Workers aim permission/GO end-cues (`👉 YOU` / `🟢 GO?`) at Director for trivial tactical decisions. Standing directive #6727 ("route permission cues to superior, not Director") exists only in agent memories — never propagated to shared/auto-loaded context. Structural cause: laconic end-cues are Director-addressed by construction, and the role-context loader only injects the laconic-default for `deputy|aihead2`.

Deputy owns the canonical-doc half (clause wording in `superior-dispatch-authority.md` + `laconic-default.md`, offline fallback, `🟢 GO? <superior> <verb object>` cue spec). **This brief is the propagation half.**

## Scope (Diagnose → build)

1. **Loader propagation:** `.claude/hooks/session-start-role.sh` (per picker repo) appends laconic-default only for `deputy|aihead2`. Extend per-role injection so every Director-facing/bus seat receives the routing clause once deputy lands it in `laconic-default.md`. Enumerate picker repos affected before editing (multi-repo — at minimum bm-aihead1, bm-aihead2, b1–b4, researcher; verify others via forge/registry).
2. **Alias normalization:** deputy-codex seat has no `deputy-codex.md` role-context → gets no injection. Normalize alias → deputy role-context (or add the file).
3. **Cue grammar:** keep `🟢 GO? <superior> <verb object>` INSIDE the existing hook grammar — `~/.claude/hooks/end-cue-check.sh:121-122` accepts only `🟢 GO? <token>`. If grammar must change, update hook + its tests atomically in the same PR.
4. **Probes (acceptance):** three live probes — researcher, one b-code, deputy-codex:
   - self-generated tactical/technical Q routes to `reports_to` superior, NOT Director;
   - Tier-B/C ratify + protected asks (external-send/destructive/secret/deploy/missing-input/ambiguity) still route to Director;
   - superior-assigned work starts WITHOUT any GO ask.

## Constraints (codex guardrails — binding)

- **No authority leak:** do NOT write "escalate only Tier-C". Split: self-generated TACTICAL/TECHNICAL → `reports_to`; PROTECTED authorization asks → Director (per `technical-escalation-contract.md:36-39` + `superior-dispatch-authority.md:42-50`).
- **No silent stall:** superior down → next authorized route; direct-to-Director only for protected boundary or material impact.
- **Preserve dispatch rule:** assigned superior work is already GO.
- Coordinate with deputy on-thread (#9161) — do not draft the clause wording yourself; consume deputy's landed canonical text.

## Files Modified (expected)

- `.claude/hooks/session-start-role.sh` in each affected picker repo (enumerate first — bm-aihead1, bm-aihead2, b1–b4, researcher; verify full set via forge/registry).
- `.claude/role-context/deputy-codex.md` (new) or alias-normalization in the loader.
- `~/.claude/hooks/end-cue-check.sh` + tests ONLY if cue grammar changes (atomic same PR).
- NO edits to canonical vault docs (`superior-dispatch-authority.md`, `laconic-default.md`) — deputy's lane.

## Verification

1. Per-repo loader evidence: session-start output showing routing clause injected for each enumerated role.
2. deputy-codex seat injection proof (session-start output).
3. `end-cue-check.sh` green on `🟢 GO? <superior> <verb object>`; hook tests pass.
4. 3/3 live probes (researcher, one b-code, deputy-codex) with transcript evidence.

## Acceptance criteria

1. Loader injects routing clause for every enumerated role (list evidence per repo).
2. deputy-codex seat receives injection (proof: session-start output).
3. end-cue-check.sh passes on `🟢 GO? <superior> <verb object>`; hook tests green.
4. 3/3 probes pass with transcript evidence.
5. Report to `briefs/_reports/`, ship-post to lead on bus.

## References

- Deputy diagnosis + split: bus #9161. Codex second-opinion: #9160. Directive: #6727.
- `~/baker-vault/_ops/processes/superior-dispatch-authority.md`, `~/baker-vault/_ops/role-contexts/laconic-default.md`, `~/baker-vault/_ops/processes/technical-escalation-contract.md`.
