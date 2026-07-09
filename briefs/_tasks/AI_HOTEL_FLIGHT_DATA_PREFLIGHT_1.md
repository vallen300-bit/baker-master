# AI_HOTEL_FLIGHT_DATA_PREFLIGHT_1

dispatched_by: lead
assigned_to: b2
task_class: diagnostic (read-only sweep)
Harness-V2: N/A — read-only data preflight, no production code, report-only output.
effort: medium

## Context

Director ordered the Origination Desk flight install (flight AI-HTL-001, main project = NVIDIA + Mandarin Oriental AI Hotel, Silicon Valley) on 2026-07-10. Per the MOVIE runbook (MO-VIE-001, canonical flight pattern), step 1 is a data preflight: verify Baker's raw stores actually hold the AI Hotel correspondence before the manifest/registry is built. Matter rooms: `wiki/matters/nvidia/` (parent), `nvidia-ai-hotel/`, `nvidia-mohg/`, `nvidia-corinthia/`. Prior internal step plan: `wiki/matters/nvidia-mohg/03_source_summaries/2026-05-14-ai-hotel-step-plan.md`.

## Problem

MOVIE's preflight (b1, PR #505) surfaced 3 HIGH data issues before launch — assume this matter has similar traps (untagged transcripts, participant identity ambiguity, channel gaps). The manifest/registry fold cannot start until raw-store reality is known.

## Task

Read-only sweep of Baker raw stores for AI Hotel / NVIDIA / MOHG correspondence:

1. **Email** (`baker_email_search` — gmail + bluewin sources): senders/keywords — NVIDIA, Mandarin Oriental, MOHG, "AI hotel", Silicon Valley, Santa Clara, Sergey Krainii, Ellie Technologies. Count hits by channel + date range; identify distinct participants (name + email).
2. **WhatsApp** (`GET /api/whatsapp/messages`): same participant set; list chat IDs + date ranges.
3. **Transcripts** (`GET /api/transcripts/by-matter/{slug}` for `nvidia`, `nvidia-ai-hotel`, `nvidia-mohg`, `nvidia-corinthia` + keyword fallback): count, dates, matter_slug tagging quality.
4. **Vault cross-check**: does raw-store reality match the matter-room inventories? Name gaps (participants in raw stores missing from rooms, and vice versa).

## Constraints

- READ-ONLY. No writes to prod tables, no vault writes, no ClickUp.
- Matter scope: AI Hotel family only. MO Prague is a SEPARATE lane — note volume if encountered but do not sweep it.
- All API calls wrapped try/except; fail loud on any store that errors — never report "clean" on a skipped store.

## Files Modified

None in production. Single new report file: `briefs/_reports/B2_AI_HOTEL_PREFLIGHT_20260710.md`.

## Verification

Every count in the report traces to an actual executed query (tool call or curl) — no "by inspection" figures. Explicit per-store statement: swept fully / partially / errored.

## Acceptance criteria

- AC1: per-channel counts (email / WA / transcripts) with date ranges, per participant.
- AC2: distinct-participant list (name, org if known, email(s), WA ID(s)) — feeds the researcher census.
- AC3: gaps + risks enumerated (missing channels, untagged transcripts, ambiguous identities), each rated HIGH/MED/LOW.
- AC4: explicit statement per store: swept fully / partially / errored.

## Done rubric

Report file written + bus post to lead on topic `flight/ai-htl-001` answering AC1-AC4.
