# BRIEF: RESEARCHER_FULL_CAPABILITY_PHASE1_1 — unlock full-capability research fleet (policy/method/fan-out + Gemma worker route + Librarian/CM dispatch templates)

## Context

Executes **Phase 1** of the codex-arch superseding proposal `proposal/researcher-full-capability-v2` (bus **#10567**, artifact `/Users/dimitry/bm-codex-arch/artifacts/2026-07-13-researcher-full-capability-proposal-v2.md`), lead-ratified **#10584** on explicit Director direction 2026-07-13 ("We need the best-in-class researchers", quality over cost, "open him up") + the /goal directive ("execute the dispatch from Codex Arch regarding researcher"). Authored by lead — codex-arch is app-resident and offline tonight; **the proposal §Rollout Phase 1 is the design source and is BINDING where this brief is silent.**

Researcher's ratified config still carries three now-superseded restraints: (1) fan-out hard-capped at N=3 default / N=5 escalation with per-run cost figures that read as budgets; (2) Gemma 4 excluded from fan-out lanes entirely (bus #1374), demoted to a Director-Q&A side path; (3) no sanctioned direct Librarian/CM-1..4 dispatch path, so mixed internal/external questions cannot get one coordinated evidence plan. Director superseded these 2026-07-13. **What SURVIVES: Opus 4.8 as final synthesizer (#1369 clause), mandatory `researcher-verify-citations` Step 6.5, counter-evidence lane, matter-confidentiality boundary, and every action restriction (no writes / sends / credentials / destructive ops).**

### Surface contract: N/A — docs/policy-only brief (vault markdown + one live route verification); no clickable surface, no UI, no endpoint.

dispatched_by: lead
assigned_to: b4
task_class: docs/policy unlock (vault `_ops` researcher policy + skill files) + one runtime-route verification (Gemma reachability from the researcher seat) — no daemon change, no new service, no cage edits

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites: none (vault write access via isolated worktree; researcher seat reachable for the live probe)

## Baker Agent Vault Rails
Relevant vault rails: skills-and-playbooks (research-fan-out + local-research-via-gemma + dispatch templates), memory-and-lessons (supersession anchors), verification-surfaces (live probe + POST_DEPLOY_AC).
Ignore unrelated rails: bus-and-lanes (no daemon/schema change), build-command-center (no service build), loop-runner.

Harness-V2: Context Contract + done rubric + gate plan inline.
effort: high (recommended — policy surface with supersession semantics that must not break surviving rails)

**Context Contract.** Write surface: `~/baker-vault/_ops/agents/researcher/method.md` + `orientation.md`, `_ops/skills/research-fan-out/SKILL.md` + `output-schemas.md` + NEW `dispatch-templates.md`, `_ops/skills/local-research-via-gemma/SKILL.md`. Vault writes via **isolated worktree + PR only** (shared-checkout hazard — desks switch `~/baker-vault` HEAD mid-work). Read-only grounding: the proposal artifact, bus #10567/#10573/#10584, method.md §2 WHERE + §10, ratifications #1365/#1369/#1374 (2026-05-30).

### SCOPE DEDUPE (MANDATORY)
- **Cage widening / access-lift = COWORK-AH1's lane (#10528, Director-direct):** SSRF deny-list + any-public-https + codex-HIGH+/security-review + lead-merge riders live there. This brief does NOT touch `_ops/hooks/researcher_bash_cage.sh`, any picker `settings*.json`, or any allow-list. If the Gemma route is cage-blocked, escalate (Fix 3c) — never edit.
- **Phase 2 (evidence-ledger infra) + Phase 3 (15-brief blind benchmark)** — later briefs. This brief ships the evidence-pack CONTRACT as schema doc only; no storage/validation code.
- **Researcher tranche 1-13 (order #9258) — SHIPPED.** Touch those surfaces only where ceiling/exclusion language lives.
- `research-types.md` — NOT touched (its line-144 "ceiling-hit" is the benchmark-handoff rule, unrelated; verified by grep 2026-07-13).

---

## Fix 1: method.md + orientation.md — authority + supersession

### Problem
method.md §10 fixes N=3/N=5 and carries "no Gemma, no Sonnet tier switch" via the fan-out skill reference; orientation.md lacks the full-capability authority statement.

### Current State
method.md §10 (line ~388): "Default N=3 channels, escalation N=5. Opus 4.8 synthesizer … ratified #1369". Ratification footer line ~401 cites #1365/#1369/#1374.

### Engineering Craft Gates
- Diagnose: N/A — policy edit, not a bug.
- Prototype: N/A — design ratified (#10567 + Director direction); no open design question.
- TDD/verification: applies — grep-based supersession + survivor checks (Verification 1-2) are the regression seam.

### Implementation
1. §10: replace the fixed-N sentence with dynamic worker count — start from the source map, add lanes when evidence gaps appear, stop on **evidence saturation** (no material new facts, conflicts, or source classes), never on a cost figure. KEEP the decision-rule rows (single-fact lookup → sequential; anchor-verification → sequential).
2. Every supersession edit carries an inline dated anchor, pattern: `(superseded 2026-07-13 — Director best-in-class directive, bus #10567/#10584; #1369 Opus-synthesizer clause SURVIVES)`.
3. orientation.md: add an "Authority — full-capability research principal (2026-07-13)" section: broad read + analysis capability across all approved models (Opus/Sonnet/Haiku/Gemma 4/Grok/Perplexity/Gemini) and research surfaces; dynamic worker count; **cost = telemetry, not a stop condition** (Researcher reports spend in ship posts; lead surfaces spikes; no self-imposed halt); action restrictions verbatim from proposal amendment 7 (no destructive changes, no operational commitments, no credential exposure, no unrelated confidential-data access).
4. Internal lane: matter Deep-Dive re-route to desks STAYS; add the Librarian/CM evidence lane (Fix 2) as the sanctioned mixed-question path — Researcher receives receipted evidence packs, never direct matter authority.

### Key Constraints
Do not delete the sequential 4-tier walk (still the right shape for narrow lookups). Do not touch Shape rules (SHORT/FULL). Rule 3/5 comms blocks in orientation.md stay verbatim.

### Verification
Grep ACs in ## Verification below.

---

## Fix 2: Librarian + CM-1..4 dispatch templates (NEW `_ops/skills/research-fan-out/dispatch-templates.md`)

### Problem
No sanctioned direct dispatch path Researcher → librarian / CM-1..4; proposal amendment 5 permits it.

### Current State
research-fan-out SKILL.md §3 blanket-excludes "Internal Brisen data" from fan-out; librarian/CM contracts exist but only for desk/lead callers.

### Engineering Craft Gates
- Diagnose: N/A. — Prototype: N/A (contract shape given in proposal). — TDD/verification: applies — live probe sends one librarian template and validates the returned pack (Verification 4).

### Implementation
1. New file with two template families (Researcher → librarian, Researcher → CM-N), each: narrow question + source lane/surface list + required output schema + stop condition + the contract line "return evidence, do NOT interpret".
2. Embed **evidence-pack contract v1**: copy the JSON field set from proposal §"Evidence memory and pack contract" verbatim, stamped `"schema": "evidence_pack_v1"`. Also append it to `output-schemas.md` as a companion section ("internal-lane channels return evidence_pack_v1 rows inside the base findings[] wrapper") — additive, no existing schema row changes.
3. CM partition rule (by surface / document set / date range / entity / competing hypothesis — never 4 copies of one generic prompt) copied from proposal §CM-1..4.
4. Dispatch mechanics: `scripts/bus_post.sh <librarian|CM-N> "<template>" <topic>` from the researcher seat (researcher is a bus agent; no new wiring). Note: CM slugs are case-sensitive on the bus (`CM-1`..`CM-4`).
5. Pointers: research-fan-out SKILL.md §3 internal-lane row (replacing the blanket exclusion) + method.md §2 WHERE table row → this file.

### Key Constraints
Templates are docs — no scripts, no automation. Librarian/CM retrieval-only boundaries restated inside each template (their existing contracts are an asset; do not soften).

---

## Fix 3: Gemma 4 worker route — verify, then smallest unlock

### Problem
Gemma exists locally (Ollama @ `http://localhost:11434`) but is fan-out-excluded (#1374) and possibly cage-blocked from the researcher seat.

### Current State
`local-research-via-gemma` SKILL.md: `gemma4:latest` WORKS; **`gemma4:26b` BROKEN (silent empty output — never use/pin/fallback)**. Skill predates the researcher Bash-cage ENFORCE flip; `curl` is generally cage-denied except inside vetted script paths.

### Engineering Craft Gates
- Diagnose: applies — feedback loop = run the skill's health-check + 5-word sanity call from the actual researcher seat; hypotheses: (a) cage denies curl → blocked, (b) skill path vetted → works, (c) Ollama down → restart first. Probe = the transcript of the attempt.
- Prototype: N/A. — TDD/verification: applies — live route proof or blocked-command evidence (never assumed).

### Implementation
(a) VERIFY from the researcher seat: invoke the skill's call signature (`gemma4:latest`) exactly as documented; capture pass/fail + the exact denial line if blocked.
(b) IF IT RUNS: rewrite the skill's scope from "Director-Q&A side path" to the proposal's Gemma worker roles (large-corpus read/extraction, transcript segmentation, entity/claim/date/amount extraction, many-document comparison, contradiction candidates, alternative hypotheses, independent second-model interpretation of supplied evidence). Keep verbatim: the epistemic rule (Gemma's factual output needs receipts like every model; Gemma NEVER writes the Director-facing conclusion) + the `:26b` warning. Add Gemma lane rows to fan-out SKILL.md §3 menu + §4 router (supplied-corpus / transcript / independent-interpretation lanes).
(c) IF CAGE-BLOCKED: ship all docs anyway with the Gemma lane marked `pending-cage-route (cowork-ah1 #10528)`, and post to lead the exact blocked command + a proposed vetted-wrapper spec (input: local text/transcript path; output: JSON only). Do NOT edit the cage.

### Key Constraints
Pin `gemma4:latest` in every doc/template. No model pulls, no Ollama config changes.

---

## Fix 4: research-fan-out SKILL.md — dynamic lanes + multi-family challenge

### Problem
§1/§3 carry fixed N + cost-as-budget framing + the Gemma exclusion; §4a challenge lane is single-family.

### Current State
§1: "Default N=3, escalation N=5 … ≈$0.60/$0.80". §3: Gemma excluded per #1374; Internal Brisen data excluded. §4a counter-evidence lane exists (KEEP).

### Engineering Craft Gates
Diagnose N/A · Prototype N/A · TDD/verification: applies — grep ACs + live probe.

### Implementation
1. §1/§2: N is dynamic; typical full-investigation lane list from proposal §Stage 2 as the worked example (official/primary, academic/standards, technical/GitHub, trade press, social/X, internal Baker evidence, ClaimsMax archive, media/transcript, paid/authenticated, counter-evidence, independent alternative-model). Cost figures re-labeled "telemetry reference points, not budgets".
2. §3: strike the Gemma-exclusion line (dated anchor; #1374's YouTube transcript-fetch mechanics SURVIVE); replace the internal-data exclusion with the Fix-2 internal-lane row; **1Password stays excluded** (credentials are not a research channel).
3. §4/§5: lane-escalation rule — a lane may escalate to Opus when it fails twice or turns judgment-heavy; workers get narrow question + lane + schema + stop condition, never full parent context.
4. §4a: high-stakes challenge uses **two different model families** (proposal §Stage 4) to reduce correlated error.

### Key Constraints
`validate_channel_output.py` untouched. §7 failure semantics untouched. Synthesizer stays Opus 4.8.

---

## Files Modified
- `_ops/agents/researcher/method.md` — §10 dynamic fan-out + §2 internal-lane pointer + supersession anchors
- `_ops/agents/researcher/orientation.md` — authority section (full-capability, cost=telemetry, action restrictions)
- `_ops/skills/research-fan-out/SKILL.md` — dynamic N, Gemma lanes, internal lane, multi-family challenge, cost-as-telemetry
- `_ops/skills/research-fan-out/output-schemas.md` — evidence_pack_v1 companion section (additive)
- `_ops/skills/research-fan-out/dispatch-templates.md` — NEW
- `_ops/skills/local-research-via-gemma/SKILL.md` — worker-role scope rewrite (Fix 3b) or `pending-cage-route` note (3c)

## Do NOT Touch
- `_ops/hooks/researcher_bash_cage.sh` + any picker `settings*.json` — cowork-ah1's lane (#10528)
- `_ops/agents/researcher/research-types.md` — line-144 "ceiling" is unrelated benchmark-handoff language
- `validate_channel_output.py`, `researcher-verify-citations` skill — verification rails survive untouched
- `baker-vault/slugs.yml`, any baker-master/brisen-lab code — out of scope

## Verification
1. **Supersession integrity (grep AC):** in the touched files, zero remaining matches for `N=3`/`N=5`-as-cap, `no Gemma`, cost-as-budget phrasing; every supersession edit carries the dated anchor naming what SURVIVES.
2. **Survivor grep AC:** post-edit, these strings still present — Opus 4.8 synthesizer clause (method.md §10 + fan-out SKILL), `researcher-verify-citations` mandatory language, counter-evidence lane, matter-confidentiality re-route, action restrictions, `gemma4:26b` broken warning, 1Password exclusion.
3. **Gemma route:** live pass transcript from the researcher seat OR exact blocked-command evidence + wrapper spec posted to lead. Never silently deferred.
4. **Live probe (post-merge):** dispatch researcher one SHORT fan-out exercising a non-default lane count + 1 librarian dispatch template; the returned pack validates against evidence_pack_v1 and the synthesis cites it. Researcher autowakes — run tonight; if librarian is dark, flag the half-complete probe, don't fake it.
5. `POST_DEPLOY_AC_VERDICT v1` to lead after 4.

## Quality Checkpoints
1. All pieces in ONE vault PR; worktree-isolated; no shared-checkout writes.
2. Grep ACs 1-2 pass (paste outputs in ship report).
3. Gemma route resolved (b) or escalated (c) with evidence.
4. Live probe run + AC verdict posted to lead.
5. Zero cage/settings edits (diff proves).
6. Gate plan: G1 self-verify → codex gate (effort=high) → lead line-review + merge → live probe → POST_DEPLOY_AC_VERDICT.

## Verification SQL
```sql
-- N/A — no database surface in this brief (docs/policy + live-probe only)
```
