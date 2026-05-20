---
status: COMPLETE
brief: briefs/BRIEF_WHATSAPP_API_SENDER_PROBE_1.md
brief_id: WHATSAPP_API_SENDER_PROBE_1
target_repo: baker-master
working_dir: ~/bm-b1
working_branch: b1/whatsapp-api-sender-probe-1
matter_slug: baker-internal
cross_matter_usage: [all-matters — every desk that pulls WA via this endpoint]
dispatched_at: 2026-05-20T13:55:00Z
dispatched_by: lead
director_auth: 2026-05-20 chat — "fire it"
estimated_effort: ~10-15 builder-minutes
complexity: Low
priority: medium (Brisen Desk surfaced live; Director worked around once but pattern is generalizable)
reply_target: lead (bus topic `ship/whatsapp-api-sender-probe-1`)
merge_closeout: |
  WHATSAPP_API_SENDER_PROBE_1 merged 2026-05-20 14:18:03Z — baker-master squash f2f7aaf (PR #232).
  Render deploy dep-d86s57gjs32c738r080g LIVE 14:20:55Z.
  Post-merge live probe PASS: contact=796720083 from=2026-05-17 to=2026-05-20 returned 14 rows
  (incl. 2026-05-20 13:28 message previously invisible to all phone-substring queries).
  Gates cleared at ship: 14/14 pytest + py_compile + check_singletons + pre-commit Parts 1-4.
  Bus dispatch #609 acked; ship #610 posted; closeout #611 acked.
---

# CODE_1_PENDING — WHATSAPP_API_SENDER_PROBE_1 — 2026-05-20

## What

1-line fix to `/api/whatsapp/messages` at `outputs/dashboard.py:1047`. Add `OR sender ILIKE %s` to the WHERE clause + pass `contact` a third time in the params tuple. Closes the LID-row blindness exposed by Brisen Desk diagnostic earlier today.

## Why you (B1)

Two PRs from you today (#229, #231) landed cleanly on the Phase 4.5 / dashboard.py surface. You already have the file warm.

## Brief

Full spec: `briefs/BRIEF_WHATSAPP_API_SENDER_PROBE_1.md` (read end-to-end before starting).

## Four edits

1. `outputs/dashboard.py:1018` — Query description: "sender, sender_name OR chat_id substring (ILIKE)".
2. `outputs/dashboard.py:1026-1027` — docstring: add the LID-migration note (verbatim in brief).
3. `outputs/dashboard.py:1047` — WHERE clause: `WHERE (sender ILIKE %s OR sender_name ILIKE %s OR chat_id ILIKE %s)`.
4. `outputs/dashboard.py:1053` — params: `(f"%{contact}%", f"%{contact}%", f"%{contact}%", from_date, to_date, limit)`.

Plus 1 new test in `tests/test_whatsapp_pull_api.py`: `test_whatsapp_messages_lid_row_surfaces_via_phone_substring` — fixture with LID-shaped row (sender=`41799999999@c.us`, sender_name=chat_id=`<digits>@lid`), query with `contact='799999999'`, expect 1 row.

## Ship gate (literal)

- `pytest tests/test_whatsapp_pull_api.py -v` — full output in PR description; new test name visible.
- `python3.12 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True); print('compile OK')"` — prints `compile OK`.
- `bash scripts/check_singletons.sh` — OK.
- Pre-commit hook Parts 1-4 pass (no migration edit, no agent file add, no retired model ID, no `/env-vars` PUT).
- Diff size: ≤10 LOC in dashboard.py + ≤30 LOC in test file. Larger = scope creep, push back.

## Post-merge live probe (AH1 will run, for your awareness)

Hit deployed `/api/whatsapp/messages?contact=796720083&from=2026-05-17&to=2026-05-20` and assert count > 0. Should return ~14 rows (4 from 2026-05-18 + 9+ from 2026-05-20 + 1 historical from Sep 2025).

## Reporting

On PR open, bus-post `lead` (per `dispatched_by: lead`):

```bash
BAKER_ROLE=b1 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "ship/whatsapp-api-sender-probe-1 — PR #<N> open; pytest <X/X> green; endpoint WHERE now probes sender + sender_name + chat_id; new LID-row test added." \
  ship/whatsapp-api-sender-probe-1
```

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Heartbeat = (a) UPDATE entry in this mailbox file with ISO timestamp, OR (b) commit on working branch with `mailbox(b1): heartbeat <ISO> — <where>` pattern, OR (c) ship-report file write.

## Anchors

- Brisen Desk diagnostic: 2026-05-20 chat "WAHA capture / name-mapping gap" — 16 zero-return probes on `41796720083` / `Julia Kvashnina Stadnik`.
- Raw-query proof (AH1 2026-05-20): 4 rows at `sender='41796720083@c.us'`, `sender_name='16462794231969@lid'`, `chat_id='16462794231969@lid'`, timestamps 2026-05-18 19:01:04…19:01:55Z.
- Buggy WHERE clause: `outputs/dashboard.py:1047`.
- Director ratification: 2026-05-20 chat "fire it".
