---
dispatch: OPUS_4_8_UPGRADE_1
to: b3
from: cowork-ah1
dispatched_by: cowork-ah1
status: PENDING
dispatched_at: 2026-05-31T09:25:00Z
authored: 2026-05-31
brief_path: briefs/BRIEF_OPUS_4_8_UPGRADE_1.md
target_repo: baker-master
estimated_time: ~2.5h
complexity: Medium
reply_to: cowork-ah1
ship_topic: ship/opus-4-8-upgrade-1
anchor_chat: Director 2026-05-31 — ratified Opus 4.8 upgrade after Anthropic 2026-05-28 release; codebase audit found 28 sites on 4-6 + cost table mispriced 3×.
supersedes: BRIEF_RESEARCHER_FANOUT_SKILL_1 (COMPLETE, ship 7efcded)
---

# b3 dispatch — OPUS_4_8_UPGRADE_1

Read `briefs/BRIEF_OPUS_4_8_UPGRADE_1.md` end-to-end before any code.

## One-line
Bump all Baker Opus calls from 4-6/4-7 to **`claude-opus-4-8`** behind a single env switch (`KBL_ANTHROPIC_MODEL`), and fix the Opus price table ($15/$75 → $5/$25).

## Load-bearing constraints (full detail in brief)
1. **One file at a time** — migrate, `py_compile`, repeat. Batch LLM migration = 19 bugs (lessons.md).
2. **Opus family only.** Do NOT touch Sonnet/Haiku/Gemma/Gemini routes (claimsmax MODEL_ROUTINE, step1_triage, step3_extract, document_pipeline._HAIKU_MODEL, retry.py health model).
3. **Env-overridable** — `KBL_ANTHROPIC_MODEL` default `claude-opus-4-8`; `=claude-opus-4-7` must revert with no redeploy. No un-overridable hardcoded 4-8.
4. **Confirm the exact `claude-opus-4-8` string** against platform.claude.com release notes before commit.
5. **Phase 2 (fast mode / effort control) is OUT OF SCOPE** — do not implement.

## Ship gate
- `pytest` literal-green (paste output — no "by inspection").
- One live Opus 4.8 call returns 200 + non-empty.
- Rollback verified (`KBL_ANTHROPIC_MODEL=claude-opus-4-7`).
- Cost calc returns $5/$25.

## Reply
PR on a `b3/opus-4-8-upgrade-1` branch; do NOT merge — AH gate first. Ship report to `briefs/_reports/B3_OPUS_4_8_UPGRADE_1_<YYYYMMDD>.md` + bus-post `lead` with topic `ship/opus-4-8-upgrade-1`. reply_target cowork-ah1.
