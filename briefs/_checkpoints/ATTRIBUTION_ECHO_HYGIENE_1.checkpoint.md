# CHECKPOINT — ATTRIBUTION_ECHO_HYGIENE_1

attempt: 1
seat: b3 (dispatch #10757 + addendum #10770, claimed #10777)
branch: b3/attribution-echo-hygiene-1 (off post-#134 origin/main @59103ae, brisen-lab; pushed)
created: 2026-07-13
updated: 2026-07-13

## Brief id
ATTRIBUTION_ECHO_HYGIENE_1 — lead dispatch #10757 + addendum #10770. ONE micro-PR, 3 items.
Effort low-medium. Repo: brisen-lab.

## STATUS: BUILT + GREEN + PR #135 OPENED — awaiting codex gate → lead merge
- brisen-lab PR #135 (branch @head, off @59103ae). Codex gate requested #10779; lead #10780.
- G1 PASS: 5/5 tests green, ALL load-bearing (each verified to fail vs origin/main bus.py).
  Full suite 26f/626p = zero new failures vs true post-#134 baseline (deterministic
  failing-set diff empty; 26 = pre-existing autowake/identity isolation).
- Ship report briefs/_reports/B3_ATTRIBUTION_ECHO_HYGIENE_1_2026-07-13.md.

## Three items (all in bus.py; no schema change — columns already exist)
1. execute_obligation stored-echo on dedup: added to INSERT RETURNING + conflict re-SELECT;
   response echoes row["execute_obligation"]. source safe (from_terminal in key scope).
2. client ratify_decision insert (_ratify_decision_inner): stamps source=sender_slug /
   unattributed=is_shared_key / intent='event' per the CLIENT gate (b1 #10750).
3. daemon paths post_daemon_message + emit_audit: derive intent via _derive_intent(kind),
   incl emit_audit escalate ratify_required=command (b1 #10768).

## Note surfaced to lead (#10780)
Item 2 also stamps intent='event' on the ratify_decision row (was NULL post-#133, same
class as item 3 on a client path). Folded in since already editing that insert — lead can
split it out if he prefers item 2 strictly source/unattributed.

## Next concrete step
Await codex verdict on review/pr-135. On PASS → relay to lead for merge. On request_changes
→ hot-fix loop (new commit, never amend; re-verify; reply). Post-merge: this brief is a
hygiene follow-up (no deploy AC of its own beyond the merged bus behavior).

## Test-DB note
Local PG /tmp:5432. Isolated throwaway: createdb -h /tmp <db>,
TEST_DATABASE_URL=postgresql://localhost/<db>?host=/tmp, run, dropdb. NOT shared Neon.
Baseline = post-#134 origin/main bus.py with the attribution test file ignored (26f/626p).
Autowake/identity failures are flaky ±1 — use the deterministic same-session failing-set
diff (comm) as the authoritative zero-new-failures check, not the raw count.

## Claim discipline
Successor claims by the attempt-bump commit on THIS checkpoint. If already bumped, stand
down. At attempt >= 3, stop resuming + escalate to lead with this path + last error.
