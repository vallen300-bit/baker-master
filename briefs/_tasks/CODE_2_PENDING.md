---
status: PENDING
brief: briefs/BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md
trigger_class: TIER_A_INCIDENT_FIX_PII_LEAK_VECTOR
dispatched_at: 2026-05-08T08:10Z
dispatched_by: ai-head-b (terminal, incident-containment lane)
director_ratification: "go" (2026-05-08T08:09Z chat verbatim, ratifying brief v0.3 + B2 / PR / manual-re-enable-gate dispatch)
incident: waha-mis-route-marcus-pisani (2026-05-08)
post_mortem: ~/baker-vault/_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani.md
brief_version: 0.3
expected_pr_count: 1 (baker-master)
expected_branch_name: b2/whatsapp-recipient-resolver-fix-1
gate_to_re_enable: this brief shipped + tested + Director's verbatim "re-enable whatsapp"
---

# CODE_2_PENDING — WHATSAPP_RECIPIENT_RESOLVER_FIX_1 (PENDING)

**Dispatched:** 2026-05-08T08:10Z
**Tier:** A (PII-leak-vector incident fix; Tier-A merge gates: `/security-review` PASS + AH-side ratify)
**Repo:** `vallen300-bit/baker-master`
**Brief:** `briefs/BRIEF_WHATSAPP_RECIPIENT_RESOLVER_FIX_1.md` v0.3 — read it first, top to bottom, before opening any code. The brief contains copy-paste-ready code blocks, schema verbatim, grep-evidence block, parametrized test bodies, and an audit-row contract (`path_taken`).

## Containment context — read before touching code

Three Baker T1-Alert WhatsApp messages addressed to Director were silently mis-routed to counterparty Marcus Pisani's WhatsApp thread on the morning of 2026-05-08 between 00:02:28Z and 02:02:26Z. Item #3 was family-financial PII (Lana €650k tax tracking). Director observed at ~07:20Z; AH2-T containment GREEN at 07:32:39Z via Render env-var flip on `srv-d6dgsbctgctc73f55730`: `WAHA_BASE_URL=https://baker-waha-DISABLED-INCIDENT-2026-05-08.invalid`. Outbound WAHA is currently neutralized at the network layer.

**Your job is to fix the root-cause bug so the WAHA outbound URL can be safely restored.** Do NOT attempt to flip `WAHA_BASE_URL` back during your work — the re-enable is gated on (a) your PR merging cleanly, (b) Director's verbatim phrase `"re-enable whatsapp"`, and (c) AH2-T running the 3-smoke verification.

Full incident dossier: `~/baker-vault/_ops/incidents/2026-05-08-waha-mis-route-marcus-pisani.md`.

## What to build

**Single PR against `vallen300-bit/baker-master`:**

- `outputs/whatsapp_sender.py` — patch per brief §"Patch — outputs/whatsapp_sender.py" (Changes 1-6). Adds: `_phone_root` helper, `DIRECTOR_PHONE_ROOTS` literal frozenset, module-import sanity assert, asymmetric `_recipient_id_compatible` with tri-state `_RecipientCheck` enum, `_lid_belongs_to_phone` returning `Optional[bool]`, `_alarm_slack_lid_db_degraded` Slack hook, recipient-id assertion + `path_taken` tagging in `send_whatsapp`. Director-target sends fail-closed on LID-DB error; non-Director DEGRADED falls through with Slack alarm.
- `tests/test_whatsapp_sender_lid.py` — keep existing 6 tests passing; add the 7 new tests verbatim from brief §"New tests (7) — all must pass". Test A and Test A2 must use `@pytest.mark.parametrize("director_root", sorted(sender.DIRECTOR_PHONE_ROOTS))` so adding any new Director root automatically gets test coverage.

**Out of scope (do NOT touch in this PR):**
- `WAHA_BASE_URL`, `WHATSAPP_API_KEY`, or `DIRECTOR_WHATSAPP` constants (no value changes).
- `baker_actions` table schema (the `path_taken` field lives inside the JSONB `payload` — no migration needed).
- `whatsapp_lid_map` table population. The brief assumes the table is already populated (1,018 rows per memory). If the table is empty in your test environment, mock at the function boundary.
- `outputs/slack_notifier.py` — `_alarm_slack_lid_db_degraded` calls `post_to_channel`, which already exists. Don't refactor slack_notifier.
- `outputs/dashboard.py` — irrelevant to this fix.

## Acceptance criteria (10 items — all 10 must be green at PR-ready time)

Reproduced verbatim from brief §"Implementation acceptance criteria":

1. All 6 existing `test_whatsapp_sender_lid.py` tests pass.
2. All 7 new tests pass (Test A, A2, C, D, E, F, G). Total parametrized instances ≥18.
3. `python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"` clean.
4. PR description includes verbatim copy of **Test A, Test A2, AND Test E** code in the test plan checklist.
5. Patch does NOT touch `WAHA_BASE_URL`, `WHATSAPP_API_KEY`, or `DIRECTOR_WHATSAPP`. Patch DOES add `DIRECTOR_PHONE_ROOTS = frozenset({"41799605092", "447588690632"})` adjacent to `DIRECTOR_WHATSAPP`, plus the module-import sanity assert.
6. Patch does NOT remove `_log_send_to_baker_actions`. Patch DOES extend it with `path_taken: str` keyword argument; existing payload structure preserved (JSONB augment, not replace).
7. `/security-review` skill PASS on the PR diff (Lesson #52 — Tier-A merges).
8. PR description includes output of:
   ```
   grep -rn "_resolve_to_active_chat_id\|sendText\|baker-waha" outputs/ orchestrator/ tools/
   ```
   Expected: exactly one resolver call site at `outputs/whatsapp_sender.py:140`; one sendText egress at `:151`. No other matches in `outputs/`, `orchestrator/`, or `tools/`. **If any other caller surfaces, stop and escalate to AH2-T before proceeding** — the recipient-id assertion design assumes single-callsite gating.
9. PR description embeds the `whatsapp_lid_map` schema verbatim per the brief schema block, and confirms `_lid_belongs_to_phone` SQL uses `f"{expected_phone_digits}@c.us"` for the `phone =` parameter.
10. PR description lists which `path_taken` value covers which code branch and confirms Test G parametrizes over all 5 paths. No code branch may write zero or >1 audit rows for a given send invocation.

## PR workflow

1. Create branch `b2/whatsapp-recipient-resolver-fix-1` off `main`.
2. Apply the patch + tests per brief.
3. Run `pytest tests/test_whatsapp_sender_lid.py -v` locally; all 6 existing + 7 new must pass (≥18 parametrized instances).
4. Run the literal grep from acceptance criterion #8; paste output into PR description.
5. Run `python3 -c "import py_compile; py_compile.compile('outputs/whatsapp_sender.py', doraise=True)"` clean.
6. Push branch, open PR titled `fix(whatsapp): recipient-id assertion + Director-target asymmetric fail-closed (incident waha-mis-route-marcus-pisani-1)`.
7. PR body must include the items from acceptance criteria #4, #8, #9, #10 (verbatim test code blocks + grep output + schema + path_taken table).
8. End your chat ship report with the fenced PL paste-block per SKILL.md §"PL ship-report contract". PL paste-block topic: `incident/waha-mis-route-marcus-pisani-fix`.

**On merge gate:** AH2-T runs `/security-review` on the PR diff (Lesson #52). Director ratifies merge. After merge, AH2-T executes the 3-smoke re-enable sequence per brief §"Re-enable sequence (after merge)".

## Coordination notes

- **Slack outbound is currently LIVE** (Director scope-narrowed the kill to WhatsApp only). `_alarm_slack_lid_db_degraded` will reach #cockpit during your tests if your test environment hits live Slack — patch it in tests as shown in brief Test D (`patch.object(sender, "_alarm_slack_lid_db_degraded")`).
- **WAHA outbound is DEAD.** Don't try to live-fire `send_whatsapp` from your B2 dev environment — `WAHA_BASE_URL` on baker-master Render is scrambled, and Render env doesn't propagate to local dev. Test entirely via mocks per brief.
- **Director's UK number (`447588690632`)** is in scope — appears in `DIRECTOR_PHONE_ROOTS` literal because the future Baker UK eSIM activation must not silently fail-open on the asymmetric Director-fail-closed branch. Pre-protected per reviewer HIGH-1 v0.3.
- **PII handling:** the 3 mis-routed message contents are referenced by `baker_actions.id` (854, 855, 856) only. **Do not paste the message text into your PR description, commit messages, or chat ship report.** That handling is locked into the brief and post-mortem; B2 follows the same constraint.

## PL ship-report

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract". PL paste-block topic: `incident/waha-mis-route-marcus-pisani-fix`.
