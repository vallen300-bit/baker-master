# Fleet role-to-skill KEEP/DROP matrix - 2026-07-16

> **Binding ruling:** lead bus #11951. Table 0 is derived from the current
> generated identity snapshot and supersedes the brief's imprecise 12-row map.

## Scope and decision rule

- Catalog source: `SKILLS_INDEX.md` (132 indexed skills).
- `KEEP` means register the skill in that role's picker.
- `DROP` means remove it from that picker's registration and retain it behind
  the shared `skill-index` pointer on demand.
- Existing picker-local registrations found in the representative seats are
  carried into the relevant profile when the slug is in the indexed catalog.
- Local-only skills outside the 132-skill catalog are listed as preserved
  exceptions; this matrix does not authorize deleting them.
- This artifact does not edit manifests or shared skill bodies.

## Gate and dependency state

- Stage: matrix authored; independent Codex gate and lead line-read are still required.
- Rollout order: workers first, then support, then matter desks.
- `skill-index` pointer present in the shared vault: **NO**.
- **BLOCKING DEPENDENCY:** no shared `skill-index/SKILL.md` was visible at generation time; do not roll out DROP decisions until the pointer exists and its discoverability spot-check passes.

## Table 0 - Seat manifest

Identity generator entries observed: **42** (brief/ruling expected 38; drift: +4).
Every generated row is assigned exactly once below. Claude skill decisions
apply only to MEASURE rows; Codex and no-session rows are N/A.

| Role | Class | Profile | Picker path | State |
|---|---|---|---|---|
| `lead` | `MEASURE-terminal` | `ai-head` | `/Users/dimitry/bm-aihead1` | OK |
| `cowork-ah1` | `MEASURE-app` | `ai-head` | `/Users/dimitry/bm-aihead1` | OK |
| `deputy` | `MEASURE-terminal` | `deputy` | `/Users/dimitry/bm-aihead2` | OK |
| `deputy-codex` | `N/A-codex` | `N/A-codex` | `/Users/dimitry/bm-aihead2` | N/A |
| `aid` | `MEASURE-terminal` | `aid` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-aidennis-t` | OK |
| `b1` | `MEASURE-terminal` | `worker` | `/Users/dimitry/bm-b1` | OK |
| `b2` | `MEASURE-terminal` | `worker` | `/Users/dimitry/bm-b2` | OK |
| `b3` | `MEASURE-terminal` | `worker` | `/Users/dimitry/bm-b3` | OK |
| `b4` | `MEASURE-terminal` | `worker` | `/Users/dimitry/bm-b4` | OK |
| `researcher` | `MEASURE-terminal` | `researcher` | `/Users/dimitry/bm-researcher` | OK |
| `codex` | `N/A-codex` | `N/A-codex` | `/Users/dimitry/baker-vault` | N/A |
| `codex-arch` | `N/A-codex` | `N/A-codex` | `/Users/dimitry/baker-vault` | N/A |
| `clerk` | `MEASURE-terminal` | `clerk` | `/Users/dimitry/bm-clerk` | OK |
| `clerk-haiku` | `MEASURE-terminal` | `clerk` | `/Users/dimitry/bm-clerk` | OK |
| `russo-ai` | `MEASURE-terminal` | `russo` | `/Users/dimitry/bm-russo-ai` | OK |
| `deep55` | `N/A-no-session` | `N/A-no-session` | `N/A` | N/A |
| `ben` | `MEASURE-app` | `ben` | `/Users/dimitry/bm-ben` | OK |
| `librarian` | `MEASURE-terminal` | `librarian` | `/Users/dimitry/bm-librarian` | OK |
| `arm` | `MEASURE-terminal` | `arm` | `/Users/dimitry/bm-arm` | OK |
| `publisher` | `MEASURE-terminal` | `publisher` | `/Users/dimitry/bm-publisher` | OK |
| `designer` | `MEASURE-terminal` | `designer` | `/Users/dimitry/bm-designer` | OK |
| `hag-desk` | `MEASURE-terminal` | `matter-common` | `/Users/dimitry/bm-hag-desk` | OK |
| `origination-desk` | `MEASURE-terminal` | `origination` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-origination-desk` | OK |
| `ao-desk` | `MEASURE-terminal` | `matter-common` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-ao-desk` | OK |
| `movie-desk` | `MEASURE-terminal` | `matter-common` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-movie-desk` | OK |
| `baden-baden-desk` | `MEASURE-terminal` | `matter-common` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-baden-baden-desk` | OK |
| `brisen-desk` | `MEASURE-terminal` | `matter-common` | `/Users/dimitry/Vallen Dropbox/Dimitry vallen/bm-brisen-desk` | OK |
| `cowork-bb-desk` | `MEASURE-app` | `matter-common` | `/Users/dimitry/BB` | OK |
| `cowork-ao-desk` | `MEASURE-app` | `matter-common` | `/Users/dimitry/AO` | OK |
| `cowork-movie-desk` | `MEASURE-app` | `matter-common` | `/Users/dimitry/MOVIE` | OK |
| `cowork-hag-desk` | `MEASURE-app` | `matter-common` | `/Users/dimitry/Hagenauer` | OK |
| `cowork-origination-desk` | `MEASURE-app` | `origination` | `/Users/dimitry/Origination` | OK |
| `cowork-researcher` | `MEASURE-app` | `researcher` | `/Users/dimitry/Researcher` | OK |
| `cowork-arm` | `MEASURE-app` | `arm` | `/Users/dimitry/ARM` | OK |
| `cowork-russo-ai` | `MEASURE-app` | `russo` | `/Users/dimitry/Russo` | OK |
| `cowork-librarian` | `MEASURE-app` | `librarian` | `/Users/dimitry/Librarian` | OK |
| `cowork-aid` | `MEASURE-app` | `aid` | `/Users/dimitry/AID` | OK |
| `CM-1` | `MEASURE-terminal` | `filing-worker` | `/Users/dimitry/bm-CM-1` | OK |
| `CM-2` | `MEASURE-terminal` | `filing-worker` | `/Users/dimitry/bm-CM-2` | OK |
| `CM-3` | `MEASURE-terminal` | `filing-worker` | `/Users/dimitry/bm-CM-3` | OK |
| `CM-4` | `MEASURE-terminal` | `filing-worker` | `/Users/dimitry/bm-CM-4` | OK |
| `hag-filer` | `MEASURE-terminal` | `filing-worker` | `/Users/dimitry/bm-hag-filer` | OK |

## Profile definitions

| Profile | Seats | Keep count | Drop count | Decision basis |
|---|---|---:|---:|---|
| `ai-head` | `lead`, `cowork-ah1` | 38 | 94 | AI Head terminal/app seat |
| `deputy` | `deputy` | 33 | 99 | Deputy terminal seat |
| `worker` | `b1`, `b2`, `b3`, `b4` | 13 | 119 | Build worker seat |
| `filing-worker` | `CM-1`, `CM-2`, `CM-3`, `CM-4`, `hag-filer` | 20 | 112 | Matter filing worker seat |
| `researcher` | `researcher`, `cowork-researcher` | 21 | 111 | Research and evidence seat |
| `matter-common` | `hag-desk`, `ao-desk`, `movie-desk`, `baden-baden-desk`, `brisen-desk`, `cowork-bb-desk`, `cowork-ao-desk`, `cowork-movie-desk`, `cowork-hag-desk` | 39 | 93 | Matter desk seat |
| `origination` | `origination-desk`, `cowork-origination-desk` | 55 | 77 | Origination desk seat |
| `aid` | `aid`, `cowork-aid` | 32 | 100 | AI Dennis / IT seat |
| `arm` | `arm`, `cowork-arm` | 21 | 111 | ARM / flight operations seat |
| `publisher` | `publisher` | 24 | 108 | Publisher seat |
| `designer` | `designer` | 21 | 111 | UI design seat |
| `librarian` | `librarian`, `cowork-librarian` | 18 | 114 | Library and evidence seat |
| `clerk` | `clerk`, `clerk-haiku` | 19 | 113 | Clerk evidence-processing seat |
| `russo` | `russo-ai`, `cowork-russo-ai` | 21 | 111 | Russo research seat |
| `ben` | `ben` | 41 | 91 | BEN finance/app seat |

## Skill decision matrix

| Skill | ai-head | deputy | worker | filing-worker | researcher | matter-common | origination | aid | arm | publisher | designer | librarian | clerk | russo | ben |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `agent-bus-posting-contract` | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP |
| `agent-onboarding-runbook` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `agent-spec-template` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `ai-head` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `ai-head-brief-and-gate` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `ai-head-memory-reference` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `ai-head-ops-reference` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `aidennis-edge-scout` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `airport-process-orchestration` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `analog-library` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer |
| `anthropic-feature-scout` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `architecture-review` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `b-code-dispatch-coordination` | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `back-of-envelope-math` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `baker-whiteboard-pass` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `brisen-balazs-powerpoint-style` | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP |
| `brisen-balazs-word-style` | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP |
| `build-pm` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `capability-extension-template` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `cascade-back-prop` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `ceo-decision-framing` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `chrome-debug-recovery` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `claimsmax-api` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer |
| `claimsmax-recharge-investigation-pipeline` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `claude-settings-forge-collision-runbook` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `clickup-research-loop` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `client-facing-research-findings` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | KEEP |
| `code-graph-search-cheapest-form` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `color-system` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `component-spec` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `correspondence-routing` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `cortex-config-template` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `cost-latency-quality-tradeoff` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `counterparty-model` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `dashboard-spa-build` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `data-visualization` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `decision-log` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `deep-module-interface-first` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `design-ingest` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `design-v2` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `desk-gmail-reach` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `devils-advocate` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `director-facing-filter-contract-validator` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `director-facing-filter-stakeholder-validator` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `director-pdf-signing` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `document-intake-to-room` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer |
| `documentation-template` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `done-rubrics-stop-gate` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `dropbox-file-delivery` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `email-send-via-mail-app` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `engineering-router-context-contract` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `eval-design` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `executive-audit-html` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `executive-memo-authoring` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `executive-memo-ellie-style` | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP |
| `field-capture-to-card` | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `first-principles-reset` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `flight-dashboard-build` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `flight-discipline` | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `flight-install-runbook` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `grok-via-xai-api` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer |
| `handoff` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `harness-setup` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `helmer-7-powers` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `html-loops` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `html-triage` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `humanality` | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `important-document` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer |
| `install-agent-to-brisen-lab` | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `install-agent-to-cowork-app` | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `it-manager` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `jtbd` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `kill-criteria-definer` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `laconic` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `layers-orient` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `layout-grid` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `local-research-via-gemma` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | KEEP |
| `long-running-task-ownership` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `matter-onboarding-runbook` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `mckinsey-report-html` | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP |
| `memo-block-plan` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `memo-body-loops` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `memo-engagement-check` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `memo-explore` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `memo-grill` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `memo-lessons` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `memo-review` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `model-selection` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `negotiation-prep` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `nvidia-style-html` | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP |
| `opportunity-framework` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `outbound-status-claim-gate` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `partner-pitch-craft` | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `pichler-report` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `pilot-training` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `pin-protocol` | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP |
| `post-deploy-ac-bus-gate` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `pre-mortem` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `presentation-deck` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `project-dashboard-spec` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `project-room-build` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `prompt-pattern-library` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `pyramid-principle` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `reliability-engineering` | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `research-fan-out` | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer |
| `research-repository` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer |
| `researcher-verify-citations` | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer |
| `responsive-design` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `sacca` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `scenario-planning` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `skill-installation` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `specialist-prompt-template` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `swot-analysis` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `three-horizons` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `time-horizon-filter` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `transcripts-by-matter` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer |
| `typography-scale` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `ui-surface-prebrief` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | KEEP |
| `ux-writing` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `v2-bridge-cutover-runbook` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `vendor-benchmark` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `verify-dashboard-render` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `wardley-mapping` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `whatsapp-pull-via-api` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP |
| `whatsapp-send-via-waha` | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP |
| `whiteboarding` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `wireframe-spec` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `worker-execution-of-matter-filing` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer |
| `write-brief` | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer |
| `writer-contract` | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP | KEEP |
| `x-twitter` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | KEEP | KEEP | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | KEEP |
| `youtube-analyze` | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | DROP-to-pointer | KEEP | DROP-to-pointer | KEEP | DROP-to-pointer |

## Local-only registrations to preserve

| Role | Profile | Local-only skill slugs |
|---|---|---|
| `clerk` | `clerk` | `clerk` |
| `clerk-haiku` | `clerk` | `clerk` |
| `ben` | `ben` | `bb-finance` |
| `hag-desk` | `matter-common` | `hagenauer-desk` |
| `origination-desk` | `origination` | `origination-desk` |
| `ao-desk` | `matter-common` | `ao-desk` |
| `movie-desk` | `matter-common` | `movie-desk` |
| `baden-baden-desk` | `matter-common` | `baden-baden-desk` |
| `brisen-desk` | `matter-common` | `brisen-desk` |

## Review notes

- The current generated snapshot contains 42 seats, not the ruling's expected 38.
  The four-row drift is preserved and named; no generated row was silently dropped.
- `N/A-codex` rows use a different loader and are footnotes, not Claude skill denominators.
- `N/A-no-session` rows have no local picker and do not receive a Claude manifest.
- AC2 and AC3 remain open until the pointer skill exists, each staged manifest is
  applied, and three dropped-skill discoverability probes pass per picker group.
