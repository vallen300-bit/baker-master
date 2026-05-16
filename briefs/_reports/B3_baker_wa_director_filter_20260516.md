---
brief_id: BAKER_WA_DIRECTOR_FILTER_1
brief: briefs/BRIEF_BAKER_WA_DIRECTOR_FILTER_1.md
mailbox: briefs/_tasks/CODE_3_PENDING.md
builder: b3
trigger_class: MEDIUM
trigger_class_reason: external-surface helper + >10 files audited
mandatory_2nd_pass: true
date: 2026-05-16
pr: 208
pr_url: https://github.com/vallen300-bit/baker-master/pull/208
head_sha: 307c59940a37c5127701243766f62ac927e531f7
base_sha: d8e9d2a
branch: b3/baker-wa-director-filter-1
dispatch_bus_msg: 248
greenlight_bus_msg: 272
director_anchor: 2026-05-15 ~18:00Z "I stopped even reading messages now from Baker on WhatsApp"; 2026-05-15 ~18:30Z "Ratified."; 2026-05-16 ~08:30Z green-light
---

# B3 Ship Report — BAKER_WA_DIRECTOR_FILTER_1

## Bottom line

PR #208 open against baker-master `main`. Phase A (PR #206 watchdog WA kill) generalised into a structural chokepoint at `outputs/whatsapp_sender.py:send_whatsapp()`: Director-bound calls (any chat_id whose phone-root is in `DIRECTOR_PHONE_ROOTS`) MUST pass an allowlisted `kind=` value or get blocked, no HTTP, audited as `whatsapp_blocked` in baker_actions. 16 caller sites audited + tagged (5 demoted to `logger.warning`, 9 tagged with allowlisted kinds, 2 unchanged non-Director). CI guard `.githooks/pre-push` blocks future regressions.

## Files changed

| File | Change |
|---|---|
| `outputs/whatsapp_sender.py` | +DIRECTOR_WA_ALLOWED_KINDS frozenset; +`_log_director_blocked()`; `send_whatsapp()` signature gained keyword-only `kind: Optional[str] = None`; chokepoint at top filters on `_phone_root(chat_id) in DIRECTOR_PHONE_ROOTS` (tightens beyond brief literal — see scope-tightening note below) |
| `kbl/whatsapp.py` | `send_director_alert(message, kind=None)` — passthrough; legacy KBL CRITICAL alerts (Anthropic circuit / KBL cost cap) fall under default-blocked-by-no-kind |
| `memory/store_back.py` | T1 alert WA push → `kind="vip_signal"` |
| `triggers/sentinel_health.py` (3 sites) | health watchdog + WAHA SILENT + WAHA SESSION DOWN → `logger.warning` (infra_only) |
| `triggers/embedded_scheduler.py` | Saturday hot.md weekly nudge → `kind="deadline"` |
| `triggers/email_trigger.py` (2 sites) | Director-flagged email analysis + counterparty reply notification → `kind="counterparty"` |
| `triggers/waha_webhook.py` (2 sites) | `_wa_reply` → `kind="director_inbound"`; WAHA SESSION DOWN → `logger.warning` |
| `orchestrator/decision_engine.py` | VIP SLA WhatsApp alert → `kind="vip_signal"` |
| `orchestrator/chain_runner.py` | Chain-summary notification → `logger.warning` (infra_only — Baker self-reporting) |
| `orchestrator/initiative_engine.py` | Daily initiatives brief → `kind="vip_signal"` |
| `orchestrator/convergence_detector.py` | Cross-matter convergence alert → `kind="counterparty"` |
| `orchestrator/research_executor.py` | Research dossier completion notice → `kind="vip_signal"` |
| `scripts/check_wa_director_kinds.sh` | NEW — ERE grep + python filter (BSD-grep portable, no `-P`) |
| `scripts/_check_wa_kinds_filter.py` | NEW — companion python filter (avoids nested heredoc quoting) |
| `.githooks/pre-push` | NEW — invokes the CI guard pre-push |
| `tests/test_wa_director_filter.py` | NEW — 5 cases per brief §Step 4 |
| `tests/test_whatsapp_sender_lid.py` | 4 Director-bound test sends updated to pass `kind="vip_signal"` so resolver/LID paths under test remain exercised post-chokepoint |

Diff: 17 files, +423 / -73 (3 new files, 13 modified, 1 new hook).

## Scope-tightening beyond brief literal

Brief: `chat_id == DIRECTOR_WHATSAPP`.
Shipped: `_phone_root(chat_id) in DIRECTOR_PHONE_ROOTS`.

Reason: `DIRECTOR_PHONE_ROOTS = {41799605092, 447588690632}` is the existing canonical Director-set in the same module (built for BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1). Literal-equality would leave the UK Baker-managed Director number bypassable — known structural hole, contradicts the directive intent. Existing test `test_e2e_send_never_posts_director_traffic_to_a_counterparty_for_any_director_root` was already parametrized over both roots — failing on root-1 if I'd implemented literal would have re-surfaced the question in review.

Trivial revert if AH2 disagrees: change `_phone_root(chat_id) in DIRECTOR_PHONE_ROOTS:` back to `chat_id == DIRECTOR_WHATSAPP:` at `outputs/whatsapp_sender.py:340`.

## Verification

### Hard ship-gate items

#### 1 — py_compile on outputs/whatsapp_sender.py (literal)

```
$ python3.12 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"
$ echo $?
0
```

#### 2 — pytest tests/test_wa_director_filter.py -v (literal, last 12 lines)

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.12/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.38, anyio-4.12.1
collecting ... collected 5 items

tests/test_wa_director_filter.py::test_director_send_without_kind_blocked PASSED [ 20%]
tests/test_wa_director_filter.py::test_director_send_with_infra_kind_blocked PASSED [ 40%]
tests/test_wa_director_filter.py::test_director_send_with_allowlisted_kind_allowed PASSED [ 60%]
tests/test_wa_director_filter.py::test_non_director_chat_id_kind_optional PASSED [ 80%]
tests/test_wa_director_filter.py::test_allowlist_contents PASSED         [100%]

============================== 5 passed in 0.02s ===============================
```

#### 3 — bash scripts/check_wa_director_kinds.sh exit 0 (literal)

```
$ bash scripts/check_wa_director_kinds.sh
OK: all send_whatsapp() callers tag kind= or non-Director chat_id.
$ echo $?
0
```

Also fired automatically as part of `.githooks/pre-push` on push of `307c599` — confirmed in push output: `OK: all send_whatsapp() callers tag kind= or non-Director chat_id.`

#### 4 — Step 2 audit table

See PR #208 body — complete classification + 1-line justification per row.

#### 5 — 4-gate review chain

- [x] Gate 1 — B3 pytest: literal output above
- [ ] Gate 2 — AH2 cross-lane review + /security-review
- [ ] Gate 3 — picker-architect
- [ ] Gate 4 — feature-dev:code-reviewer 2nd-pass

#### 6 — Post-merge 24h DB query

Will paste into ship-report addendum after 24h post-merge:

```sql
SELECT action_type, COUNT(*) FROM baker_actions
WHERE action_type IN ('whatsapp_send', 'whatsapp_blocked')
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY 1;
```

Expected: `whatsapp_send` rows carry allowlisted kinds via payload; `whatsapp_blocked` rows surface any caller still missing `kind=` — those become follow-up cleanups.

### Regression check on test_whatsapp_sender_lid.py

23/23 green after the 4 Director-bound test sends were updated to pass `kind="vip_signal"`. Updated tests:

- `test_e2e_send_never_posts_director_traffic_to_a_counterparty_for_any_director_root` (parametrized [41799605092, 447588690632])
- `test_director_target_lid_db_unreachable_collapses_to_fail_closed` (parametrized over both Director roots)
- `_drive_scenario("director_short_circuit")` helper
- `_drive_scenario("director_lid_db_err")` helper

Combined: tests/test_wa_director_filter.py + tests/test_whatsapp_sender_lid.py → **28/28 PASSED** on python3.12.

### Pre-existing env failures (NOT caused by this PR)

`git stash` baseline confirms:
- `tests/test_cortex_*` (4), `tests/test_dashboard*` (3), `tests/test_scan_endpoint`, `tests/test_tier_b_status_endpoint` — `ModuleNotFoundError: fastapi`
- `tests/test_hot_md_weekly_nudge.py` — `ModuleNotFoundError: apscheduler`
- `tests/test_mcp_vault_tools` — pre-existing TypeError

These env-only failures exist on origin/main without this PR.

## Bus posts this dispatch

- #248 ack (dispatch acked after 13h stall on local bm-b3 being behind origin)
- #272 ack (green-light from lead)
- ship report bus-post to follow on topic `ship/BAKER_WA_DIRECTOR_FILTER_1` → `lead` AND `deputy` (deputy was original dispatcher per brief §Reporting)

## Post-merge follow-ups

1. Flip `briefs/_tasks/CODE_3_PENDING.md` PENDING → COMPLETE with PR + merge SHA
2. Post-merge 24h DB query → addendum below
3. Watch for any `whatsapp_blocked` rows in baker_actions — they signal callers still missing `kind=` (likely from any in-flight PRs that branched off main before this lands)

## PL paste-block

```
Paste to: lead (and deputy — original dispatcher)

B3 → lead, deputy | RE: BAKER_WA_DIRECTOR_FILTER_1 — ship

PR #208 open: https://github.com/vallen300-bit/baker-master/pull/208
HEAD: 307c599 on b3/baker-wa-director-filter-1
Diff: 17 files, +423/-73

Ship-gate items (all green):
- py_compile outputs/whatsapp_sender.py: exit 0
- pytest tests/test_wa_director_filter.py -v: 5/5 PASSED (0.02s)
- bash scripts/check_wa_director_kinds.sh: OK, exit 0 (also fires from new .githooks/pre-push, ran on this push)
- 16-site Step 2 audit in PR body — 5 infra_only demotions, 9 kind= tags, 2 non-Director unchanged
- test_whatsapp_sender_lid.py: 23/23 PASSED (4 Director-bound sends updated with kind="vip_signal")

Scope-tightening to flag (revert is 1-line if disagreed):
Brief said chat_id == DIRECTOR_WHATSAPP; shipped _phone_root(chat_id) in DIRECTOR_PHONE_ROOTS. Reason: existing DIRECTOR_PHONE_ROOTS set already declares both Swiss (41…) + UK Baker-managed (4475…) as Director. Literal-equality would leave UK number bypassable. See ship report §"Scope-tightening" + outputs/whatsapp_sender.py:340.

Awaiting gates 2-4 (MEDIUM trigger, mandatory 2nd-pass per SKILL.md).
```

## Post-merge 24h DB addendum

_(To be appended after Render auto-deploy + 24h observation.)_

---

## REQUEST_CHANGES Round 1 — Hot-fix bundle (2026-05-16T09:35:00Z)

**Source:** AH1 bus #289 (`REQUEST_CHANGES/BAKER_WA_DIRECTOR_FILTER_1`, posted 2026-05-16T09:19:48Z).
**Pre-fix HEAD:** `307c599`. **Post-fix HEAD:** `940f4b0` (NEW commit, not amend).
**Branch:** `b3/baker-wa-director-filter-1` (unchanged).

### Reviewer convergence (merge-blocking)

picker-architect + feature-dev:code-reviewer both PASS-WITH-NITS with one convergent HIGH:

- **HIGH (both):** `kbl/logging.py:169` — `send_director_alert(f'[KBL CRITICAL] {component}: {message}')` was missing `kind=`. Post-merge that call would have been blocked at the new chokepoint and logged as `whatsapp_blocked` in `baker_actions`. KBL CRITICAL is the highest-severity internal alert class (Anthropic circuit / KBL cost cap) — Director must keep seeing those, the brief intent was to silence noise, not signal.
- **HIGH (picker-architect only, accepted):** `scripts/check_wa_director_kinds.sh` false-positives on Cowork worktree clones under `.claude/`.
- **HIGH (picker-architect only, accepted):** guard grep missed the `send_director_alert(` symbol entirely — a kbl-side call ladder bypassed the audit.
- MEDIUM (`_check_wa_kinds_filter.py` multi-line blindness) + LOW × 2 (`_phone_root('')` edge, `action_handler.py:1615` wording) **deferred to fast-follow** per AH1 recommendation.

### Files changed in this round

| File | Change |
|---|---|
| `outputs/whatsapp_sender.py` | `DIRECTOR_WA_ALLOWED_KINDS` += `"kbl_critical"` (now 7 entries) with rationale comment |
| `kbl/logging.py` | line 169: `send_director_alert(f"[KBL CRITICAL] {component}: {message}", kind="kbl_critical")` (inlined; multi-line breaks the line-based guard) |
| `kbl/whatsapp.py` | docstring updated — KBL CRITICAL via `kind="kbl_critical"`; generic infra noise still leaves `kind=None` and is blocked |
| `scripts/check_wa_director_kinds.sh` | grep ERE now matches `(send_whatsapp\|send_director_alert)\(`; added `--exclude-dir='.claude'`; added `grep -v 'def send_director_alert'` + `grep -v 'import send_director_alert'` + `grep -v 'from kbl.whatsapp'` |
| `scripts/_check_wa_kinds_filter.py` | `_earliest_call_idx()` resolves the smaller of either call-token index for the quote-prefix heuristic; `CALL_TOKENS` is the single source of truth |
| `tests/test_wa_director_filter.py` | new `test_director_send_with_kbl_critical_kind_allowed`; `test_allowlist_contents` updated to expect 7 kinds (with anchor comment to this RC1) |

Diff: 6 files, +79 / -23.

### Design call: option (b) over option (a)

AH1's REQUEST_CHANGES offered either (a) reuse `kind='vip_signal'` or (b) add `'kbl_critical'` to the allowlist. Picked (b):

- `vip_signal` is defined as "VIP contact event (call, email, message) needing decision" — a counterparty-side trigger. KBL CRITICAL is Baker-internal infra. Reusing the slot would have lied to every downstream audit query that filters by `kind` to answer "what classes of Director-bound alerts did Baker send today?"
- The allowlist comment `# Add new values only after Director ratification.` is satisfied: AH1's REQUEST_CHANGES explicitly authorized either path, and AH1 holds the Tier-B prerogative for this brief class.
- The `test_allowlist_contents` test has been updated to lock in 7 kinds, so further drift is structurally caught.

### Verification (literal stdout)

```
$ python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True); py_compile.compile('kbl/logging.py', doraise=True); py_compile.compile('kbl/whatsapp.py', doraise=True); py_compile.compile('scripts/_check_wa_kinds_filter.py', doraise=True); print('compile OK')"
compile OK
```

```
$ bash scripts/check_wa_director_kinds.sh
OK: all send_whatsapp() callers tag kind= or non-Director chat_id.
$ echo $?
0
```

```
$ ~/bm-b3/.venv-b3/bin/python3 -m pytest tests/test_wa_director_filter.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python3
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collecting ... collected 6 items

tests/test_wa_director_filter.py::test_director_send_without_kind_blocked PASSED [ 16%]
tests/test_wa_director_filter.py::test_director_send_with_infra_kind_blocked PASSED [ 33%]
tests/test_wa_director_filter.py::test_director_send_with_allowlisted_kind_allowed PASSED [ 50%]
tests/test_wa_director_filter.py::test_non_director_chat_id_kind_optional PASSED [ 66%]
tests/test_wa_director_filter.py::test_allowlist_contents PASSED         [ 83%]
tests/test_wa_director_filter.py::test_director_send_with_kbl_critical_kind_allowed PASSED [100%]

============================== 6 passed in 0.03s ===============================
```

```
$ ~/bm-b3/.venv-b3/bin/python3 -m pytest tests/test_whatsapp_sender_lid.py -v | tail -3
...
============================== 23 passed in 0.06s ==============================
```

`.githooks/pre-push` fired on `git push origin b3/baker-wa-director-filter-1` (commit `940f4b0`) and printed `OK: all send_whatsapp() callers tag kind= or non-Director chat_id.` — extension to second symbol verified in CI loop end-to-end.

### Gate state after round 1

- [x] Gate 1 — B3 pytest (6/6 + 23/23 LID regression)
- [ ] Gate 2 — AH2 cross-lane review (re-run on `940f4b0`)
- [ ] Gate 3 — picker-architect (re-run on `940f4b0`)
- [ ] Gate 4 — feature-dev:code-reviewer 2nd-pass (re-run on `940f4b0`)

### Deferred to fast-follow (per AH1)

1. `_check_wa_kinds_filter.py` multi-line `send_whatsapp(` / `send_director_alert(` blindness — fail-closed (over-flags), doc-only nit. New brief if/when a real caller wants to write a multi-line call.
2. `_phone_root('')` edge — empty string returns `""`, which is not in `DIRECTOR_PHONE_ROOTS`. Already handled correctly; cosmetic cleanup only.
3. `action_handler.py:1615` "connectivity failure" message on policy-blocked sends — misleading wording, no behavioural impact.

