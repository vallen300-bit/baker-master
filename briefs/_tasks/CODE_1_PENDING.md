---
dispatch: COCKPIT_CACHEBUST_TEST_REGEX_1
to: b1
from: lead
dispatched_by: cowork-ah1 (AH1)
status: COMPLETE
dispatched_at: 2026-06-05
authored: 2026-06-05
target_repo: baker-master
estimated_time: ~15-20min
complexity: trivial
reply_to: lead
priority: tier-b-lowpri
anchor: b1 POST_DEPLOY_AC_VERDICT bus #1926 — cache-bust test pins exact CSS/JS versions, re-breaks on every bump
brief_path: briefs/BRIEF_COCKPIT_CACHEBUST_TEST_REGEX_1.md
prior_mailbox_state: superseded — COCKPIT_UX_S4_S3_FIX_1 shipped (PR #299 merged 8b4822c, POST_DEPLOY_AC PASS, CODE_1 flipped COMPLETE 2026-06-05)
---

# B1 dispatch — COCKPIT_CACHEBUST_TEST_REGEX_1

Trivial test-only refactor. Full spec in `briefs/BRIEF_COCKPIT_CACHEBUST_TEST_REGEX_1.md`.

**One-liner:** In `tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html` (lines ~120-126), replace the two exact-version asserts:
```python
assert "app.js?v=123" in src
assert "style.css?v=80" in src
```
with version-agnostic regex:
```python
import re  # module-scoped, top of file if not already present
assert re.search(r"app\.js\?v=\d+", src), "app.js cache-bust param missing"
assert re.search(r"style\.css\?v=\d+", src), "style.css cache-bust param missing"
```

**Constraints:** test-only; touch NO runtime file; keep the two presence asserts (`id="cortexTabPending"`, `_cortexTab('pending')`) unchanged; regex must still FAIL if `?v=` is absent entirely (negative-check it locally).

**Gate:** G1 lead literal pytest (`python3.12 -m pytest tests/test_dashboard_cortex_ratify.py::test_pending_tab_button_in_static_index_html -v`) → light G2 → ship. No POST_DEPLOY_AC (no deploy-surface change).

**Return:** `briefs/_reports/CODE_1_RETURN.md` + PR number on bus to lead. Use `python3.12` (default python3 here is 3.9, breaks collection).


> COCKPIT_CACHEBUST_TEST_REGEX_1 merged PR #300 (afbd63d). G1 20/20 + light G2. Test-only, no AC. COMPLETE.
