# CODE_3_PENDING — dispatch (supersedes prior)

dispatch: LIFECYCLE_INSERT_ATTRIBUTION_1
brief: inline in lead bus #10892 (deputy finding #10877). Micro, one PR.
to: b3
from: lead
dispatched_by: lead
ship_to: lead (ship report + gate verdicts to lead)
class: micro attribution fix (brisen-lab lifecycle.py daemon inserts)
effort: low

summary: The two lifecycle broadcast inserts (restart _atomic_session_expiry_and_audit_broadcast
+ forced-kill _atomic_forced_kill_broadcast) are the THIRD daemon direct-insert path missed by
#134/#135 — INSERT omitted source/unattributed/intent (live rows #10851/#10853/#10855 NULL).
Fixed: route through source='daemon', unattributed=FALSE, intent=_derive_intent(kind) — same as
#135 item 3. Load-bearing test on both inserts.

status: SHIPPED — brisen-lab PR #138 (commit 87610ef, off origin/main @5a22441). G1 PASS
(2/2 load-bearing green, zero new failures). Acked #10892 + claimed. Awaiting codex gate.

gate: G1 self-verify (done) -> codex on BUS -> lead merge.

## prior (superseded, completed + shipped)
HAG_FILER_HARNESS_RETROFIT_1 (#10892 supersedes; that arc closed earlier).
