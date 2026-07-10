---
brief_id: TICKETING_BRIDGE_PRESS_DIGEST_EXCLUDE_1
attempt: 1
status: MERGED + b1 RELEASED — lead diff-reviewed + merged PR #516 (#8420); codex gate WAIVED for this change class (PR #515 precedent); codex #8419 stood down (#8422). Render deploys from main. ONLY open item = tomorrow-morning AC watch (bb-desk sees it first, lead flagged them); lane closes on that confirm. b1 owes nothing.
repo: baker-master PR #516 MERGED to main (was branch b1/press-digest-exclude)
dispatched_by: lead (#8416/#8417 dup, 2026-07-10T07:38Z), topic ticketing-bridge/keyword-misroute-mo-vie-pressespiegel
updated: 2026-07-10T07:49Z
---

# TICKETING_BRIDGE_PRESS_DIGEST_EXCLUDE_1 — checkpoint

## PROBLEM
MIO OBSERVER daily Pressespiegel (mio@observer.at, media-monitoring vendor digest) carries
"Mandarin Oriental" in its subject -> matched the airport ticketing bridge keyword lane ->
mis-ticketed onto flight aukera-annaberg every morning; bb-desk disposed WRONG_TERMINAL daily
(#8413/#8414).

## DIAGNOSIS (done)
- `build_email_ticket()` gates automated senders at `_is_automated_email_arrival()` — airport_
  ticketing_bridge.py:812 (`if _is_automated_email_arrival(arrival): return None`) — BEFORE keyword
  match. Sender is substring-matched against the HARDCODED `_SKIP_EMAIL_SENDER_PATTERNS` tuple
  (line 136: noreply@ / no-reply@ / notifications@ / notification@ / @clickup.com / @todoist.com).
- mio@observer.at wasn't listed -> reached the keyword lane -> ticketed.
- Two independent noise surfaces: the alerts->signal bridge (kbl/bridge/alerts_to_signal.py
  `_is_stoplist_noise`) ALREADY drops this sender via MARKETING_NOISE_FILTER_1 (title pattern,
  see tests/test_bridge_stop_list_additions.py:141) — but the airport bridge keeps its OWN sender
  skip list that didn't include it.

## FIX (done)
- Added "mio@observer.at" to `_SKIP_EMAIL_SENDER_PATTERNS` (airport_ticketing_bridge.py). Config
  preferred but the list is hardcoded (no env), so it's a 1-line code change -> TDD + codex gate.
- Surgical + sender-scoped — NOT a keyword change; "mandarin oriental" still tickets for every
  other sender (brief: do NOT reroute the keyword wholesale).
- Scope choice: specific address over "@observer.at" domain class (zero over-exclusion risk).
  Domain class = trivial follow-up if lead wants ALL Observer digests dropped.

## TESTS (TDD red->green, tests/test_airport_ticketing_bridge.py)
- test_press_digest_mio_observer_does_not_ticket — build_email_ticket(mio@observer.at,
  keywords=("mandarin oriental",)) -> None even with the keyword active (exact prod scenario).
- test_mio_observer_skip_is_sender_scoped_not_keyword_wide — digest automated=True; a human with
  the same keyword automated=False (surgical-scope guard).
- Regression: bridge file 11/11; broader ticketing suite 111 passed / 93 skipped (DB-gated). No DB needed.

## AC (mechanism-cited per brief)
"tomorrow morning digest does NOT mint a ticket" = build_email_ticket returns None at the automated-
sender gate for mio@observer.at BEFORE keyword match. Proven by test. Real-world confirmation is
tomorrow's digest (bb-desk observes no new WRONG_TERMINAL). No deploy-flag/POST_DEPLOY_AC needed.

## NEXT CONCRETE STEP
AWAIT codex-medium verdict on PR #516 (#8419) + lead merge. On request_changes: address -> NEW commit
(never amend) on b1/press-digest-exclude -> push -> reply codex+lead. Do NOT merge (lead does). Do NOT
broaden to a keyword reroute. Report stays on topic ticketing-bridge/keyword-misroute-mo-vie-pressespiegel.
