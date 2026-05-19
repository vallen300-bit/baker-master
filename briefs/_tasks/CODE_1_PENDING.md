---
status: COMPLETE
brief_id: DASHBOARD_CORTEX_TAB_HITBOX_FIX_1
target_repo: baker-master
working_dir: ~/bm-b1
matter_slug: baker-internal
dispatched_at: 2026-05-19T13:30:00Z
completed_at: 2026-05-19T16:34:09Z
merge_sha: 269f45ad55ed4ea71320dd4a83b5b486a588ef96
pr: 224
gate_chain:
  gate_1_static: PASS (deputy bus #530)
  gate_2_security_review: PASS (AH1 /security-review — no findings)
prior_dispatch_closeout: |
  DASHBOARD_CORTEX_TAB_HITBOX_FIX_1 merged 2026-05-19 16:34Z — baker-master squash 269f45a (PR #224).
  Director-blocking ratify-panel hitbox bug resolved. Mailbox flipped COMPLETE; next dispatch overwrites.
---

# CODE_1_PENDING — COMPLETE — 2026-05-19

Hot-fix shipped + merged. CSS-only patch removing absolute-positioned `.grid-cell-count` overlay so all 4 Cortex tabs (Events/Dedup/Lint/Pending) are clickable. Director ratify-panel smoke unblocked.

No further action.
