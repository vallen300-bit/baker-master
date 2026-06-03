---
dispatch: MCP_INBOX_CONTRACT_FIX_1
to: b3
from: lead
dispatched_by: lead
status: COMPLETE
completed: 2026-06-03 — PR #283 merged baker-master (squash 89613c3). Gates: G0 waived (AH2 #1675 design review) + G1 lead PASS (34/34 pytest py3.12 literal + diff matches scripts/bus_post.py) + G2 light security PASS (caller's own key unchanged, daemon derives sender from key — no spoofing, no weakened check). Post-deploy AC DONE LIVE: b3 round-trip vs prod daemon (post b3->b3 msg 1679 delivered, read returned it, ack 200). Lesson #86 added. from_terminal kept as documented no-op (backward-compat).
dispatched_at: 2026-06-03T10:15:00Z
authored: 2026-06-03
brief_path: briefs/BRIEF_MCP_INBOX_CONTRACT_FIX_1.md
target_repo: baker-master
estimated_time: ~1.5h
complexity: Low-Medium
brief_version: v1 — design-reviewed by deputy/AH2 (#1675); codex-arch G0 waived (qualified reviewer; codex-arch mid-G3 on PR #282)
codex_pre_review: WAIVED — AH2/deputy diagnosed root cause + fix (#1675); AH1 verified against code
reply_to: lead
ship_topic: ship/mcp-inbox-contract-fix-1
anchor_chat: Director 2026-06-03 "go" (dispatch MCP-inbox fix). Bug surfaced by deputy #1675 — codex-arch hit it.
---

### Surface contract: N/A — backend MCP tool + tests; no clickable surface. Full block in brief Context.

# b3 dispatch — MCP_INBOX_CONTRACT_FIX_1

Read `briefs/BRIEF_MCP_INBOX_CONTRACT_FIX_1.md` end-to-end before any code. **Target repo: baker-master** (your `~/bm-b3` baker-master clone — `baker_mcp/baker_mcp_server.py` + `tests/test_brisen_lab_consumer_mcp.py`).

**The bug (verified by AH1 against the code):** `baker_inbox_post` POSTs to `/msg/{from_terminal}` (the SENDER) instead of `/msg/{recipient}` — every MCP-sent message is stored addressed to the sender and never delivered. The unit tests assert the WRONG contract, so they pass green while the tool is broken end-to-end (Lesson #8: compile-clean ≠ works). `scripts/bus_post.py` is the CANONICAL correct contract — match it exactly; do NOT touch it.

**Scope (2 files):**
- `baker_mcp/baker_mcp_server.py` — fix 3 handlers: `baker_inbox_post` (URL → `/msg/{recipient}`, body key `to_terminals` → `to`, multi-recipient per bus_post.py), `baker_inbox_read` + `baker_inbox_ack` (default URL-path terminal to the caller's OWN slug so the `X-Terminal-Key` slug matches — kills the `reader_slug_mismatch` 403).
- `tests/test_brisen_lab_consumer_mcp.py` — rewrite the drifted asserts to the correct contract + **add an end-to-end round-trip test** (post-as-A-to-B → assert captured URL path = B) so a sender/recipient swap can never pass green again.

**Constraints:** do NOT touch `scripts/bus_post.py`/`bus_post.sh` (they are correct) or the daemon's slug-key check (the 403 is correct security behavior — fix the CALLER, don't weaken the check). Don't send another terminal's key. Confirm line refs before editing (file is volatile).

**Gates:** G0 WAIVED (AH2 design review #1675). G1 lead static → G2 LIGHT security (touches bus auth — confirm no wrong-slug key / no weakened check). G3 N/A.

**Ship:** open PR on `baker-master`; bus-post `ship/mcp-inbox-contract-fix-1` to `lead`. **Do NOT merge** (AH gate). Done-rubric in ship report: task class = backend MCP contract fix; terminal state = **live round-trip delivers** (post to lead, read as lead returns it) — NOT "tests pass" (that's the exact Lesson-#8 trap this fixes).
