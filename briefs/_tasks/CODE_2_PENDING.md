---
dispatch: ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1
to: b2
from: lead
dispatched_by: lead
status: PENDING
dispatched_at: 2026-05-29T06:55:00Z
authored: 2026-05-29
target_repo: baker-master (+ paired baker-vault PR)
estimated_time: ~5h
complexity: High
reply_to: lead
priority: tier-b
anchor: hag-desk bus #1280/#1281/#1282 + Director-ratified 2026-05-29 (AH1 chat)
brief_path: briefs/BRIEF_ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1.md
prior_mailbox_state: superseded — TEMPLATES_GALLERY_BAKER_INSTALL_1 shipped (PR #268 merged 2026-05-29)
---

# B2 dispatch — ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1

## TL;DR
Refactor `claimsmax/recharge_report/` to invoke the canonical `pichler-report-english` skill at runtime instead of baking a parallel 11-section markdown template. Output switches from markdown to HTML matching the Director-ratified Pichler V3 register (7 EN H2s + claim-figures + evidence-table + split-table + delta-conflict primitives). Three earlier wire fixes fold into this same refactor (adaptive thinking, report_title slot, per-section word targets).

Read full brief at `briefs/BRIEF_ENGLISH_V1_CLI_SKILL_INVOKE_REFACTOR_1.md`.

## Paired baker-vault PR (required, ship first)
- `wiki/matters/hagenauer-rg7/_templates/recharge-failure-report-template-v3.html` — replace inline content with `{{slot}}` placeholders.
- `wiki/_templates/pichler-head4-template.md` — delete (becomes dead after this refactor).

## Reply target
Bus-post `lead` (AI Head A) on ship with: baker-vault PR # + baker-master PR # + merge SHAs + AC1/AC3 verification output (literal pytest + live probe). Also write `CODE_2_RETURN.md`. Do NOT post to hag-desk directly — AH1 relays.
