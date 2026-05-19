# Feasibility Evidence File — `~/.claude/state/feasibility-tags.json`

When an agent surfaces 4+ options to the Director, the Filter #3 contract-gate
trigger checks for explicit feasibility tags per option. If the agent has
already tagged each option (inline OR via this evidence file), the validator
call is skipped — the agent is already discipline-following.

This file is the **agent-side declaration** that all surfaced options have been
contractually scoped. Writing it before the Stop event saves a Haiku call and
~$0.001 — and tells the filter "I've done the work."

## Schema

```json
{
  "turn_id": "<ISO timestamp of the current assistant turn>",
  "options": [
    {
      "label": "<short option label e.g. M1 — MOHG-led>",
      "feasibility": "<one of: unilateral | consent-required | amendment-required | breach-required | litigation | timeline>",
      "rationale": "<<=200 chars: which contract clause / law / counterparty constraint drives the tag>"
    }
  ]
}
```

## Constraints

- **Freshness window: 5 minutes.** Files older than 5 minutes are ignored
  (timestamp = file mtime, not the `turn_id` field). Stale state must not
  carry over silently between turns.
- **Coverage: every surfaced option needs an entry.** If you surface 5 options
  but the evidence file lists 4, the trigger still fires.
- **Tag vocabulary is locked.** Any value outside the 6 allowed tags is
  treated as missing.

## Example

Agent's reply surfaces M1–M5 (MOVIE Desk T2 scenario):

```json
{
  "turn_id": "2026-05-19T14:30:00Z",
  "options": [
    {"label": "M1 — MOHG-led", "feasibility": "amendment-required", "rationale": "HMA §7.3 requires operator consent for op-model change"},
    {"label": "M2 — lease-out", "feasibility": "consent-required", "rationale": "CSA 3.13 allows F&B sublease with operator non-objection"},
    {"label": "M3 — partial closure", "feasibility": "breach-required", "rationale": "HMA §11 forbids partial closure without 12-month notice + cure period"},
    {"label": "M4 — owner-led", "feasibility": "litigation", "rationale": "would terminate HMA; MOHG already filed objection in Q2 2026"},
    {"label": "M5 — status quo", "feasibility": "unilateral", "rationale": "no change; default state under existing HMA"}
  ]
}
```

The trigger reads this file, sees all 5 surfaced options tagged with valid
feasibility values within the 5-min window, and **skips** the validator call.

## When to write it

Before producing your final assistant reply, if your reply will surface 4+
options/paths/alternatives/routes, write this file using the canonical
schema above. Path: `~/.claude/state/feasibility-tags.json`. Overwrite —
the file is single-turn state.
