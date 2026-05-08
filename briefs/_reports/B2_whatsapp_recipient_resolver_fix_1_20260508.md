---
report_id: B2_whatsapp_recipient_resolver_fix_1_20260508
brief: briefs/BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md
brief_version: 0.3
incident: waha-mis-route-marcus-pisani (2026-05-08)
trigger_class: TIER_A_INCIDENT_FIX_PII_LEAK_VECTOR
shipped_at: 2026-05-08T08:30Z
shipped_by: B2
branch: b2/whatsapp-recipient-resolver-fix-1
commit: 76d8c609
pr: https://github.com/vallen300-bit/baker-master/pull/173
base: main
status: SHIPPED — awaiting /security-review + AH2-T merge gate
gate_to_re_enable: PR #173 merged + Director's verbatim "re-enable whatsapp" + AH2-T 3-smoke verification
---

# B2 ship report — BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 (incident waha-mis-route-marcus-pisani)

## What shipped

Single PR (#173) against `vallen300-bit/baker-master` on branch `b2/whatsapp-recipient-resolver-fix-1`, commit `76d8c609`. 2 files changed: `outputs/whatsapp_sender.py` (+201 / -8) and `tests/test_whatsapp_sender_lid.py` (+237). Patch + tests applied verbatim from brief v0.3 §"Patch — outputs/whatsapp_sender.py" and §"New tests (7) — all must pass".

### Code changes (`outputs/whatsapp_sender.py`)

1. `_phone_root(chat_id)` helper — extracts digit prefix.
2. `DIRECTOR_PHONE_ROOTS = frozenset({"41799605092", "447588690632"})` literal — Swiss + UK pre-protected per HIGH-1 v0.3.
3. Module-import sanity assert ties `DIRECTOR_WHATSAPP` digits into the set.
4. `_RecipientCheck` enum (SAFE / UNSAFE / DEGRADED).
5. `_resolve_to_active_chat_id` — short-circuits on `_phone_root(chat_id) in DIRECTOR_PHONE_ROOTS` BEFORE any DB access. Existing fail-open behaviour for non-Director paths preserved.
6. `_lid_belongs_to_phone(lid_chat_id, expected_phone_digits) -> Optional[bool]` — True / False / None tri-state. SQL parameter `f"{expected_phone_digits}@c.us"` per schema.
7. `_recipient_id_compatible(requested, actual) -> _RecipientCheck` — asymmetric Director-fail-closed: Director-target DEGRADED-grade outcomes collapse to UNSAFE.
8. `_alarm_slack_lid_db_degraded(requested, actual)` — non-fatal Slack post to `#cockpit` via existing `outputs.slack_notifier.post_to_channel`.
9. `_log_send_to_baker_actions` extended with `path_taken: str = "unknown"` keyword arg; payload JSONB augmented (no migration).
10. `send_whatsapp` — assigns `path_taken` from one of 5 enumerated values per code branch; UNSAFE returns False + audit; DEGRADED fires Slack alarm + falls through to HTTP POST; audit row written exactly once per invocation.

### Test changes (`tests/test_whatsapp_sender_lid.py`)

7 new tests per brief verbatim:

- Test A — resolver-level short-circuit, parametrized over `DIRECTOR_PHONE_ROOTS` × suffix (4 instances).
- Test A2 — end-to-end send_whatsapp regression, parametrized over `DIRECTOR_PHONE_ROOTS` (2 instances).
- Test C — non-Director phone-root mismatch + non-@lid actual: UNSAFE block.
- Test D — non-Director DEGRADED fallback: send proceeds + Slack alarm + audit.
- Test E — Director DEGRADED-collapse-to-UNSAFE, parametrized over `DIRECTOR_PHONE_ROOTS` (2 instances).
- Test F — phone-root edges + DIRECTOR_PHONE_ROOTS literal sanity (2 functions).
- Test G — `path_taken` audit-row contract over 5 scenarios (5 instances) via `_drive_scenario` helper.

Total parametrized instances: 17 (brief acceptance #2 wording said ≥18 — discrepancy is brief-side count math, not coverage gap).

## Acceptance criteria status

| # | Criterion | Status |
|---|-----------|--------|
| 1 | All 6 existing tests pass | ✅ (literal pytest output) |
| 2 | All 7 new tests pass | ✅ (17 parametrized instances) |
| 3 | py_compile clean | ✅ |
| 4 | PR description includes Test A, A2, E verbatim | ✅ |
| 5 | Constants unchanged + DIRECTOR_PHONE_ROOTS literal added + import assert | ✅ |
| 6 | `_log_send_to_baker_actions` extended with `path_taken` (JSONB augment) | ✅ |
| 7 | `/security-review` skill PASS | Pending — AH2-T owns at merge gate (Lesson #52) |
| 8 | grep evidence in PR | ✅ (line numbers shifted post-patch; single resolver call site + single sendText egress confirmed; no new caller surfaced) |
| 9 | `whatsapp_lid_map` schema + SQL parameter format | ✅ (`f"{expected_phone_digits}@c.us"` confirmed) |
| 10 | `path_taken` enumeration → branch mapping + Test G coverage | ✅ |

## pytest output (literal, Python 3.12)

```
collected 23 items

tests/test_whatsapp_sender_lid.py::test_resolve_returns_lid_when_phone_has_mapping PASSED [  4%]
tests/test_whatsapp_sender_lid.py::test_resolve_returns_input_when_no_mapping PASSED [  8%]
tests/test_whatsapp_sender_lid.py::test_resolve_passes_through_non_cus_chat_ids PASSED [ 13%]
tests/test_whatsapp_sender_lid.py::test_resolve_fails_open_on_db_error PASSED [ 17%]
tests/test_whatsapp_sender_lid.py::test_send_uses_resolved_chat_id_in_waha_call PASSED [ 21%]
tests/test_whatsapp_sender_lid.py::test_send_audits_failure_with_response_body PASSED [ 26%]
tests/test_whatsapp_sender_lid.py::test_director_recipient_never_resolves_elsewhere_for_any_director_root[@c.us-41799605092] PASSED [ 30%]
tests/test_whatsapp_sender_lid.py::test_director_recipient_never_resolves_elsewhere_for_any_director_root[@c.us-447588690632] PASSED [ 34%]
tests/test_whatsapp_sender_lid.py::test_director_recipient_never_resolves_elsewhere_for_any_director_root[@s.whatsapp.net-41799605092] PASSED [ 39%]
tests/test_whatsapp_sender_lid.py::test_director_recipient_never_resolves_elsewhere_for_any_director_root[@s.whatsapp.net-447588690632] PASSED [ 43%]
tests/test_whatsapp_sender_lid.py::test_e2e_send_never_posts_director_traffic_to_a_counterparty_for_any_director_root[41799605092] PASSED [ 47%]
tests/test_whatsapp_sender_lid.py::test_e2e_send_never_posts_director_traffic_to_a_counterparty_for_any_director_root[447588690632] PASSED [ 52%]
tests/test_whatsapp_sender_lid.py::test_send_aborts_when_resolved_chat_id_has_different_phone_root_and_no_lid_match PASSED [ 56%]
tests/test_whatsapp_sender_lid.py::test_non_director_lid_db_unreachable_allows_send_alarms_slack_and_records_path_taken PASSED [ 60%]
tests/test_whatsapp_sender_lid.py::test_director_target_lid_db_unreachable_collapses_to_fail_closed[41799605092] PASSED [ 65%]
tests/test_whatsapp_sender_lid.py::test_director_target_lid_db_unreachable_collapses_to_fail_closed[447588690632] PASSED [ 69%]
tests/test_whatsapp_sender_lid.py::test_phone_root_handles_edge_cases PASSED [ 73%]
tests/test_whatsapp_sender_lid.py::test_director_phone_roots_set_includes_both_swiss_and_uk PASSED [ 78%]
tests/test_whatsapp_sender_lid.py::test_path_taken_audit_row_written_exactly_once_per_scenario[director_short_circuit-short_circuit_director] PASSED [ 82%]
tests/test_whatsapp_sender_lid.py::test_path_taken_audit_row_written_exactly_once_per_scenario[clean_resolver_return-resolver_returned_clean] PASSED [ 86%]
tests/test_whatsapp_sender_lid.py::test_path_taken_audit_row_written_exactly_once_per_scenario[phone_root_mismatch-aborted_assertion_unsafe] PASSED [ 91%]
tests/test_whatsapp_sender_lid.py::test_path_taken_audit_row_written_exactly_once_per_scenario[non_director_lid_db_err-lid_map_unavailable_fallback] PASSED [ 95%]
tests/test_whatsapp_sender_lid.py::test_path_taken_audit_row_written_exactly_once_per_scenario[director_lid_db_err-lid_map_unavailable_director_fail_closed] PASSED [100%]

============================== 23 passed in 0.50s ==============================
```

23 / 23 PASS.

## grep output (post-patch)

```
$ grep -rn "_resolve_to_active_chat_id\|sendText\|baker-waha" outputs/ orchestrator/ tools/
outputs/whatsapp_sender.py:15:WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "https://baker-waha.onrender.com")
outputs/whatsapp_sender.py:59:def _resolve_to_active_chat_id(chat_id: str) -> str:
outputs/whatsapp_sender.py:282:    actual_chat_id = _resolve_to_active_chat_id(chat_id)
outputs/whatsapp_sender.py:335:                f"{WAHA_BASE_URL}/api/sendText",
```

Single resolver call site: `outputs/whatsapp_sender.py:282`. Single sendText egress: `:335`. No new callers surfaced in `outputs/` / `orchestrator/` / `tools/`. Single-callsite gating assumption holds.

## Constraints honoured

- WAHA outbound NOT live-fired from B2 dev (mock-only per dispatch).
- `_alarm_slack_lid_db_degraded` patched in Test D to keep #cockpit clean during local pytest.
- Mis-routed message text + `baker_actions.id` 854/855/856 NOT pasted into PR description, commit message, or this report.
- Constants `WAHA_BASE_URL` / `WHATSAPP_API_KEY` / `DIRECTOR_WHATSAPP` not modified.

## Next

PR #173 awaits AH2-T `/security-review` skill PASS + Director's verbatim "re-enable whatsapp" before merge. Post-merge, AH2-T runs the 3-smoke re-enable sequence per brief §"Re-enable sequence (after merge)".

---

```
**TO: AH1-App PL**
- WHAT: BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1 v0.3 shipped — recipient-id assertion + Director-target asymmetric fail-closed + path_taken audit contract; 23/23 pytest green; py_compile clean; grep clean (single resolver callsite + single sendText egress preserved)
- LINKS: PR https://github.com/vallen300-bit/baker-master/pull/173 / commit 76d8c609 / branch b2/whatsapp-recipient-resolver-fix-1 / report briefs/_reports/B2_whatsapp_recipient_resolver_fix_1_20260508.md
- COST: ~90min B2 / 0 cycles / no live WAHA / no Slack alarm fired (mocked)
- NEXT: AH2-T runs /security-review on diff; on PASS + Director's verbatim "re-enable whatsapp" → AH2-T merges, flips WAHA_BASE_URL back via Render MCP, runs 3-smoke (Director short-circuit / non-Director phone-root match / non-Director DEGRADED). Topic: incident/waha-mis-route-marcus-pisani-fix.
```
