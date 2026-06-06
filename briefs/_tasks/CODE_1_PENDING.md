---
status: PENDING
brief_id: OCR_UNREADABLE_MARKER_1
dispatch: OCR_UNREADABLE_MARKER_1
to: b1
from: lead
dispatched_by: lead
task_class: reliability guard (idempotency fix)
harness_v2: applies (small brief)
gate_plan: G1 lead literal pytest -> light G2 -> merge -> POST_DEPLOY_AC_VERDICT v1
brief_path: briefs/BRIEF_OCR_UNREADABLE_MARKER_1.md
prior_envelope: COCKPIT_CACHEBUST_TEST_REGEX_1 (PR #300 afbd63d) — COMPLETE
---

# B1 dispatch — OCR_UNREADABLE_MARKER_1

**Full spec: `briefs/BRIEF_OCR_UNREADABLE_MARKER_1.md`.** You built the OCR endpoint (PR #294); this fixes its non-idempotency — the 287 `unreadable` docs get re-selected + re-billed to Gemini every drain. Mark them terminal so they drop out of the candidate query (propose mechanism A vs B at G0). Keep a `force`/`--include-unreadable` re-attempt path. No search pollution. POST_DEPLOY_AC = one clean drain returning 0 dead candidates.
