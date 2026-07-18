# B4 ship report — RESEARCHER_FULL_CAPABILITY_PHASE1_1

- **Brief:** RESEARCHER_FULL_CAPABILITY_PHASE1_1 @8bd8f274 (lead #10640 + rider #10658). Phase 1 of codex-arch researcher-full-capability-v2 (#10567, lead-ratified #10584).
- **PR:** baker-vault **#196** (`b4/researcher-full-capability-phase1`, commit 975ffb5). Worktree-isolated `/private/tmp/b4-researcher-fullcap`.
- **Reply target / gate:** lead. Gate: codex effort=high → lead line-review + merge → live probe → POST_DEPLOY_AC_VERDICT.

## Done rubric
- **Fix 1** method.md §10 dynamic worker count + §2 internal evidence-lane row; orientation.md Authority section (all-model, cost=telemetry, amendment-7 action restrictions verbatim) + 4 cost-halt reframes.
- **Fix 2** NEW dispatch-templates.md (librarian + CM-1..4 families, evidence_pack_v1 contract, CM partition rule, retrieval-only boundary) + output-schemas.md additive evidence_pack_v1 companion.
- **Fix 3** Gemma route = PATH 3c (cage-blocked). local-research-via-gemma worker-role rewrite marked `pending-cage-route (cowork-ah1 #10528)`; gemma4:latest pin + :26b warning kept; fan-out Gemma worker lanes added. Wrapper spec posted to lead. Cage NOT edited.
- **Fix 4** fan-out SKILL dynamic N + Stage-2 lane list; Gemma channel-exclusion struck (YouTube transcript mechanics survive); internal lane replaces internal-data exclusion (1Password stays excluded); §4a two-family challenge; cost→telemetry. Opus 4.8 synthesizer survives.
- **Rider piece 5** CM-1 doc-pin Haiku→Sonnet in CLAUDE.md.reference + orientation-v2.md → claude-sonnet-4-6[1m] (matches live launcher; fleet moved 2026-07-09). cm-1-design.md left (history correct).

## Verification
- **V1 supersession grep:** zero unanchored N=3/N=5-cap, blanket "no Gemma", or cost-as-budget in touched files; every supersession has a dated anchor naming survivors.
- **V2 survivors grep (all present):** Opus 4.8 synthesizer #1369, researcher-verify-citations, counter-evidence lane, matter-confidentiality re-route, action restrictions, gemma4:26b warning, 1Password exclusion.
- **V3 Gemma route:** cage-block evidence (researcher_bash_cage.sh L48/L51 + method.md §2 audit 2026-07-12); live probe dispatched to researcher #10678 (confirmatory).
- **Scope:** 8 intended files + regenerated SKILLS_INDEX.md; **zero cage/settings edits**.
- **V4 live probe:** post-merge (dispatch researcher one SHORT fan-out + 1 librarian template, validate evidence_pack_v1). Runs after merge.

## Gemma vetted-wrapper spec (Fix 3c → cowork-ah1 #10528 lane)
- **Blocked command:** `curl -s -X POST http://localhost:11434/api/generate -d '{...}'` — denied by `researcher_bash_cage.sh` (L48: curl/wget/nc not allowed; L51: research fetching via WebFetch/perplexity/Chrome).
- **Proposed wrapper** (cage-vetted exact-path, mirrors `auth_source_fetch.sh` pattern): input = a local text/transcript file path + a prompt; output = JSON only (`{response, eval_count, total_duration}`); pins `gemma4:latest`; no network egress beyond localhost:11434; read-only on the input path. Adding it is cowork-ah1's cage lane, not this PR.
