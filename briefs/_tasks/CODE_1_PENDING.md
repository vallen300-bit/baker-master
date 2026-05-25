---
dispatch: AID_ON_BUS_1
to: b1
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-05-25T20:30:00Z
authored: 2026-05-25
brief_path: /Users/dimitry/bm-aihead1/briefs/BRIEF_AID_ON_BUS_1.md
sop_anchor: /Users/dimitry/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md
template_anchor: BRIEF_RESEARCHER_ON_BUS_1 (shipped 2026-05-22)
target_repos: brisen-lab + baker-vault
estimated_time: 1-2h
complexity: Low
reply_to: lead
priority: tier-b
deadline: 2026-05-26T18:00:00Z
director_ratification: chat 2026-05-25 ~19:15Z to deputy
deputy_routing: bus #1128 (deputy gates on PR open)
---

# B1 dispatch — AID_ON_BUS_1 (install AID on Brisen Lab)

## What

Wire AID (AI Dennis) onto Brisen Lab bus + cockpit card. Slug `aid` was ratified 2026-05-10 with Rows 5, 6, 7, 8 of the 13-row install SOP done (bus_post.sh whitelists + drain hook + 1Password key). The remaining brisen-lab + baker-vault rows are b1's responsibility:

- **brisen-lab repo** (PR): Rows 10 (static/index.html + app.js card slot + label) + 11(a-d) (bus.py KNOWN_CARD_SLUGS + for-loop + app.py TERMINALS + tests) + 13 (wake-handler fnMap).
- **baker-vault repo** (PR): Row 13 (agent-bus-posting-contract SKILL update).

Mac-local rows (1, 2, 3, 4, 11 forge pusher) + Tier-B Render env (Row 9) are AH1's responsibility in coordination — NOT b1's.

Card slot: `.row-desks` row, between researcher and CM-1, per Director scope ("alongside researcher, row 4, above cortex, same size as researcher").

## Where

Full brief: `/Users/dimitry/bm-aihead1/briefs/BRIEF_AID_ON_BUS_1.md`

Read it end-to-end before starting. 15 ACs total — ACs you own are explicitly tagged "b1 owns" in the brief.

## Estimated time

~1-2h (mechanical install per canonical SOP, templates from RESEARCHER_ON_BUS_1).

## Acceptance criteria you own (b1)

- **AC6** — Brisen Lab front-end (`static/index.html` card slot + `static/app.js` TERMINALS + LABELS)
- **AC7** — `bus.py:895` KNOWN_CARD_SLUGS append `"aid"`
- **AC8** — `bus.py:1007` _build_terminals_response for-loop append `"aid"`
- **AC9** — `app.py:40` TERMINALS append `"aid"` (third-pass foot-gun — do NOT skip)
- **AC10** — `tests/test_a3_a8_a9_bus.py` add 2 new AID tests (mirror researcher pattern at lines ~286 + ~322)
- **AC12** — `tools/wake-handler/wake-handler.applescript` fnMap append `{"aid", "aid"}` pair
- **AC13** — `~/baker-vault/_ops/skills/agent-bus-posting-contract/SKILL.md` recipient line + §AID subsection

## Ship report quality bar

Your ship report MUST include literal pytest output (NOT "by inspection" — anchor lesson #8). Plus grep verification:
- `grep -c '"aid"' static/app.js` ≥ 2
- `grep -c '"aid"' bus.py` ≥ 2
- `grep -c '"aid"' app.py` ≥ 1
- `grep -c '"aid"' tools/wake-handler/wake-handler.applescript` ≥ 1
- `git diff --stat` shows only the files listed under "Files touched by b1" in the brief.

## Gates

- **Gate-2 (security-review)** + **Gate-4 (code-reviewer 2nd-pass)** — deputy runs both on PR open per ai-head-autonomy-charter §3.
- **Gate-5 (Director visual check)** — AH1 + Director after AH1 post-merge Tier-A + Tier-B (Rows 1-4, 9, 11 forge pusher, wake-handler rebuild) complete. Per AC14 + AC15 in the brief.

## Bus reply

Ship report goes to lead via bus on completion. Topic: `ship/aid-on-bus-1`. Body: PR URLs (brisen-lab + baker-vault) + commit hashes + grep verification counts + pytest literal output.

## Anchors

- Director ratification: chat 2026-05-25 ~19:15Z to deputy ("install him accordingly to Brisen Lab... alongside researcher, row 4, above cortex, same size as researcher").
- Deputy routing: deputy bus #1128 (AH1 lead authoring + dispatching; deputy gates).
- SOP: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md`.
- Template: `~/bm-aihead1/briefs/BRIEF_RESEARCHER_ON_BUS_1.md`.
- Three foot-guns explicitly anchored in ACs (app.js Row 10, app.py Row 11c, Terminal profile Row 3).
