---
status: COMPLETE
brief: briefs/BRIEF_CLAIMSMAX_ASK_ENDPOINT_1.md
brief_id: CLAIMSMAX_ASK_ENDPOINT_1
target_repo: baker-master
matter_slug: baker-internal
dispatched_at: 2026-05-20T23:55:00Z
dispatched_by: lead
target: b4
working_branch: b4/claimsmax-ask-endpoint-1
parent_brief: CLAIMSMAX_API_CAPABILITY_1
reply_to: lead
pr: 236
shipped_at: 2026-05-21T22:01:00Z
ship_report: briefs/_reports/B4_claimsmax_ask_endpoint_1_20260521.md
---

# CODE_4_PENDING — CLAIMSMAX_ASK_ENDPOINT_1

**Brief:** `briefs/BRIEF_CLAIMSMAX_ASK_ENDPOINT_1.md`
**Working branch:** `b4/claimsmax-ask-endpoint-1`
**Parent brief:** `CLAIMSMAX_API_CAPABILITY_1` (PR #213 merged `3cbc287`).
**Pre-requisites:** none — vendor `/ask` endpoint live-verified by AH1
2026-05-20 ~23:50Z (HTTP 200, full RAG response).
**Reply target:** bus-post `lead` on PR open (per reply-to-sender rule).

**Acceptance criteria summary** (full criteria in brief):

1. Implement `ClaimsmaxClient.ask(question, claim_id=None, language="en")`
   in `kbl/claimsmax_client.py`.
2. Flip `test_ask_raises_not_implemented` → `test_ask_returns_response`
   with mocked 200 + documented shape.
3. Add `baker_claimsmax_ask` MCP tool in `tools/claimsmax.py` mirroring
   `baker_claimsmax_search` pattern.
4. Append MCP-surface test to `tests/test_claimsmax_client.py`.
5. Strip "pending vendor fix" framing from module docstrings.

**Ship gate:** literal `pytest tests/test_claimsmax_client.py -v` green +
full suite delta ≥ 0 failures vs baseline 2213 passed / 79 failed.

**Reporting:**

- On PR open: bus-post `lead` with PR number + `pytest` summary line +
  diff stats.
- Live smoke runs post-merge by AH1; failure → REQUEST_CHANGES.
