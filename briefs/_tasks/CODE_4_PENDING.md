---
status: PENDING
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
round: 2
round_2_requested_at: 2026-05-21T22:30:00Z
---

# CODE_4_PENDING — CLAIMSMAX_ASK_ENDPOINT_1 (ROUND 2)

**PR:** #236 (https://github.com/vallen300-bit/baker-master/pull/236) — request-changes round 2.
**Branch:** `b4/claimsmax-ask-endpoint-1` (push on top, same branch).
**Reply target:** bus-post `lead` on push.

## Round-2 asks (from PR #236 review comment)

### MED-1 — MCP dispatch test missing omit-claim-id path

Add a second test next to `test_mcp_baker_claimsmax_ask_dispatch`:
```python
def test_mcp_baker_claimsmax_ask_dispatch_omits_claim_id(monkeypatch):
    stub = MagicMock()
    stub.ask = MagicMock(return_value=_ASK_RESPONSE_FIXTURE)
    monkeypatch.setattr(claimsmax_tools, "_get_client", lambda: stub)
    claimsmax_tools.dispatch_claimsmax("baker_claimsmax_ask", {"question": "anything"})
    stub.ask.assert_called_once_with(question="anything", claim_id=None, language="en")
```

### MED-2 — `query_terms` not asserted

In `test_ask_returns_response`, add:
```python
assert out["query_terms"] == ["pagitsch", "defect"]
```

### LOW-1 — `language` schema enum

In `tools/claimsmax.py` `baker_claimsmax_ask` Tool schema, add `"enum": ["en", "de"]` to the `language` property. (Pick this option over loosening the description — tighter contract, vendor `/ask` doc + AH1 live probe confirm `en`/`de` only.)

## Ship gate

`pytest tests/test_claimsmax_client.py -v` green; full suite delta ≥ 0 failures vs baseline.

## Reporting

Bus-post `lead` on push with the three commit shas / summary.
