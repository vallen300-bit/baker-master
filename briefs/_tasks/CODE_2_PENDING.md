---
status: PENDING
brief: briefs/BRIEF_GROK_API_CAPABILITY_1.md
brief_id: GROK_API_CAPABILITY_1
trigger_class: MEDIUM (new external API surface + new MCP tools + new migration; mandatory 2nd-pass review)
target_branch: b2/grok-api-capability-1
matter_slug: baker-internal
cross_matter_usage: [all-matter-desks]
dispatched_at: 2026-05-17T11:45:43Z
dispatched_by: AH1
director_auth: 2026-05-17 chat — "Draft the brief now. Send it to B2. By bus. Don't worry about confidentiality. Let's try to use it. See what happens."
pattern_source: BRIEF_CLAIMSMAX_API_CAPABILITY_1 (commit 3cbc287)
prior_brief_state: |
  Mailbox previously held WORKER_SELFWAKE_PHASE_1 in PARKED state (Director directive 2026-05-15).
  Preserved at briefs/_tasks/CODE_2_PARKED_WORKER_SELFWAKE_20260515.md for future resume.
  Director authorized override 2026-05-17 ("Send it to B2") — Grok dispatch supersedes mailbox slot.
---

# Dispatch: GROK_API_CAPABILITY_1

B2 — full brief at `briefs/BRIEF_GROK_API_CAPABILITY_1.md`.

**TL;DR:** Wire xAI Grok Heavy API (`https://api.x.ai/v1`) into Baker as a permanent capability. Three MCP tools: `baker_grok_x_search`, `baker_grok_web_search`, `baker_grok_ask`. Mirror ClaimsMax pattern end-to-end (commit 3cbc287). Auth via `XAI_API_KEY` env var (AH1 provisions before merge). `capability_type='archive'` per ClaimsMax PR #213 C1 lesson.

**Pilot framing (Director 2026-05-17):** *"Let's try to use it. See what happens."* Not high-stakes — goal is to learn what Grok delivers in our context. Don't gold-plate. Mirror ClaimsMax structure and ship.

**Working dir:** `~/bm-b2`
**Branch:** `b2/grok-api-capability-1` off `main`
**Estimated touch:** ~6 files, ~400 LOC including tests + migration.
**Trigger class:** MEDIUM (mandatory 2nd-pass review per gate protocol — `/security-review` + `feature-dev:code-reviewer` 2nd-pass).

## Pre-flight

1. `cd ~/bm-b2 && git pull --ff-only origin main`
2. Read `briefs/BRIEF_GROK_API_CAPABILITY_1.md` end-to-end
3. Read `kbl/claimsmax_client.py` + `tools/claimsmax.py` + `migrations/20260517_claimsmax_capability_set.sql` — the exact template you're mirroring (commit 3cbc287)
4. **WebFetch `https://docs.x.ai/docs` FIRST** to verify §Scope assumptions before any coding
5. If xAI docs diverge materially from brief §Scope → bus-post `lead` topic `grok-api-spec-mismatch` BEFORE coding

## Reporting

- Bus-post `lead` on claim (topic `claim/grok-api-capability-1`)
- Bus-post `lead` on PR open (topic `pr-open/grok-api-capability-1`)
- AH1 runs `/security-review` (mandatory per Lesson #52 + trigger-class MEDIUM) + `feature-dev:code-reviewer` 2nd-pass
- AH1 sets Render env var `XAI_API_KEY` before merge (separate Tier B; runs parallel to your coding — do NOT block PR open on it)
- AH1 merges on green; runs one live smoke test against prod deploy

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
