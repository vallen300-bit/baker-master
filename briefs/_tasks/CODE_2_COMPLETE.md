# CODE_2_PENDING — BRISEN_LAB_V2_BRIDGE_F2

**Dispatched:** 2026-05-06
**Tier:** B (no daemon code change; client-side helper + convention update)
**Repo (primary):** `vallen300-bit/baker-master`
**Branch (primary):** `b2/brisen-lab-v2-bridge-f2`
**Repo (companion, optional):** `vallen300-bit/brisen-lab`
**Branch (companion):** `b2/brisen-lab-v2-bridge-f2-authz-bools`
**Brief:** `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_F2.md` (read it first — full spec)

## Summary

Outbound auto-post script for AI Heads. Director ratified 2026-05-06 OPTION A + policy (ii). Closes the Director-as-relay loop for inter-worker dispatches; AH1/AH2 invoke `~/.baker-hooks/bus_post.sh <recipient> <body> [topic]` instead of producing paste-blocks. Sender key fetched from 1Password on demand (~200ms/call). Director-recipient explicitly blocked at script level — Director-facing chat stays paste-blocks until Stage 2 autopoll.

## What to build

NEW (baker-master):
- `scripts/bus_post.sh` — POSIX-portable Bash helper, shellcheck-clean
- `scripts/bus_post.py` — Python companion for richer payloads (multi-recipient, parent_id chains)
- `tests/test_bus_post.py` — 15 subprocess + stub-daemon tests

**V0.2 amendment 2026-05-06 (B2 boundary #7 catch):** vault-side files (`_ops/agents/aihead{1,2}/orientation.md`, `_ops/skills/ai-head/SKILL.md`) are OUT OF B2 SCOPE — they live in `~/baker-vault/_ops/` per CHANDA Inv 9. AH1-T handles vault convention update separately. AC A7 STRUCK.

EXTEND (brisen-lab, companion PR — Architect Item 5 fold per AH1-T disposition):
- `authz.py` — `is_party_to_message()` + `is_recipient_of_message()` bool-predicates on CallerContext
- `tests/test_authz_factory.py` — 4 new tests (22 → 26)

Symlinks: `~/.baker-hooks/bus_post.{sh,py}` → `scripts/bus_post.{sh,py}`.

## Two-repo split — IMPORTANT

Baker-master PR ships INDEPENDENTLY of brisen-lab companion PR. Script doesn't depend on the bool-predicates. If brisen-lab review hits issues, baker-master ships standalone; the bool-predicate fold can land later. Don't gate baker-master merge on brisen-lab.

## CRITICAL: 5-gate review chain MANDATORY

Run all reviewers in **parallel** in a single message:

1. **AH2 static review** — `feature-dev:code-reviewer` — full diff (both repos)
2. **AH2 `/security-review`** — focus on 1P key fetch, recipient validation, payload escaping, daemon URL injection
3. **picker-architect review** — script-vs-tool tradeoff, env-var policy adherence, brisen-lab fold scoping
4. **feature-dev:code-reviewer 2nd-pass** — after any review-driven changes

Tag PR `tier-b-tooling`. Link brisen-lab companion PR in baker-master PR body.

## CRITICAL: 12-slug registry hard-coded

Valid recipients (verified against `auth_lab._TERMINAL_KEYS` test fixture):
```
director (REJECTED by script), cowork-ah1, lead, deputy, architect, b1, b2, b3, b4, b5, cortex, daemon
```

`director` rejection is a load-bearing safety check — Director-facing dispatches must NOT silently land in the bus inbox until Stage 2 autopoll wires Cowork's App-side hook. AC A6 pins this.

## Acceptance criteria

- A1: shellcheck `scripts/bus_post.sh` clean
- A2: py_compile `scripts/bus_post.py` clean
- A3: `pytest tests/test_bus_post.py -v` — 15 PASS
- A4: symlinks `~/.baker-hooks/bus_post.{sh,py}` exist + executable
- A5: manual smoke (post-merge by AH1-T): `BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh b2 "F2 smoke" "v2-bridge/f2/smoke"` → HTTP 200 + valid JSON
- A6: director-recipient block verified — `bus_post.sh director "x"` exits 1 with explicit stderr
- ~~A7: orientation + SKILL update~~ — STRUCK (V0.2; vault-side, AH1-T handles)
- A8: (brisen-lab companion PR) authz.py CallerContext bool-predicates + 4 new tests PASS; ClickUp 86c9nr9dw closes on merge
- A9: brisen-lab full pytest still GREEN (no regression in 22+9 = 31 existing tests)

## Smoke test (manual, post-merge — AH1-T runs in own shell)

```bash
BAKER_ROLE=AH1 ~/.baker-hooks/bus_post.sh b2 "F2 smoke test from AH1-T at $(date -u +%FT%TZ)" "v2-bridge/f2/smoke"
LEAD_KEY=$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')
curl -s -H "X-Terminal-Key: $LEAD_KEY" https://brisen-lab.onrender.com/msg/b2 | jq '.messages[-1]'
```

Expected: posted message appears in B2's inbox.

## Ship-report

After merge, write `briefs/_reports/B2_brisen_lab_v2_bridge_f2_<YYYYMMDD>.md`: PR numbers (both repos if both shipped), merge commits, AC table all ☑, files modified, in-flight observations, V0.x amendments.

## Files modified — see brief §"Files modified"

## Do NOT touch

- `brisen-lab/bus.py` (daemon endpoints unchanged)
- `.claude/hooks/user-prompt-submit-confirm.py` (receive-side, separate lane)
- Director-facing paste-block patterns (STAYS until Stage 2)
- `~/.zshrc` launchers (separate hygiene brief if Director wants env-var purge)

## Lessons applied (in brief)

- Function signatures verified against actual `auth_lab.py` / `bus.py` before writing
- Tier B classification (no daemon code change; no new auth surface)
- Director-recipient block as load-bearing safety
- Pin-not-vacuous test on the block (AC A6)
- Two-repo split — primary PR ships standalone if companion lags
