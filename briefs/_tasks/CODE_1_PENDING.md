# CODE_1_PENDING — B1: REVIEW PR #68 AMEX_RECURRING_DEADLINE_1 — 2026-04-26

**Dispatcher:** AI Head B (Build-reviewer, M2 lane)
**Working dir:** `~/bm-b1`
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/68
**Branch under review:** `amex-recurring-deadline-1` (built by B3, commit `0dfed74`)
**Brief:** `briefs/BRIEF_AMEX_RECURRING_DEADLINE_1.md` (amended retroactively per Rule 0)
**Status:** OPEN — peer review (B1 cannot review own work; B3 was builder, B1 is reviewer)
**Trigger class:** **MEDIUM** (DB migration + cross-capability state writes via 3 completion-path call-site mods) per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. AI Head B holds merge until B1 APPROVE.

---

## §3 hygiene retroactive

Prior CODE_1_PENDING was COMPLETE (PR #66 GOLD review APPROVE + merge `95d99f3`). This dispatch overwrites.

## §2 pre-dispatch busy-check (Lesson #48 amendment applied)

- **Mailbox prior:** COMPLETE — PR #66 review. Idle ✓
- **Lesson #48 review-in-flight pre-check:** AI Head B verified 2026-04-26 PM:
  - `gh pr view 68 --json reviewDecision` → empty (no review started)
  - `ls briefs/_reports/B1_pr68*` → no matches (no report file)
  - PR #68 just opened by B3 (commit `0dfed74` minutes ago)
  - **Safe to dispatch — no race condition.**
- **Branch state:** `gh pr checkout 68` resolves any stale state.
- **Other B-codes:** B2 → PR #67 WIKI_LINT_1 in flight (M1 lane / AI Head A — not your concern). B3 → just shipped PR #68 (idle). B5 → CHANDA rewrite. No overlap.
- **Dispatch authorisation:** Director RA-21 2026-04-26 PM Q-resolutions + situational-review rule auto-fire (medium trigger-class).

---

## Your review job — 14 checks (1 added vs PR #66 protocol — Amendment H verification)

### 1. Scope lock — file count + paths

```bash
cd ~/bm-b1 && git fetch && gh pr checkout 68 && git pull -q
git diff --name-only main...HEAD
```

Expect at minimum:
```
briefs/_reports/B3_amex_recurring_deadline_1_20260426.md (or similar)
migrations/20260426_amex_recurrence.sql
memory/store_back.py                                (modified — bootstrap added)
orchestrator/deadline_manager.py                    (modified — compute_next_due + _maybe_respawn_recurring + auto-dismiss exclusions + dismiss UX)
triggers/clickup_trigger.py                         (modified — wire respawn at line 540)
models/deadlines.py                                 (modified — wire respawn at line 395)
requirements.txt                                    (modified — python-dateutil added)
tests/test_deadline_recurrence.py
```

Reject if: any auth/secrets module touched, vault paths in PR, or ANY completion path missing the respawn wire (Amendment H).

### 2. Python syntax on all new + modified Python files

```bash
for f in $(git diff --name-only main...HEAD | grep '\.py$'); do
  python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" || { echo "FAIL: $f"; exit 1; }
done && echo "All .py files clean."
```

### 3. Migration-vs-bootstrap drift check (Code Brief Standard #4)

```bash
diff <(grep -A 10 "ALTER TABLE deadlines\|ADD COLUMN.*recurrence" migrations/20260426_amex_recurrence.sql | sort) \
     <(grep -A 10 "ALTER TABLE deadlines\|ADD COLUMN.*recurrence" memory/store_back.py | sort)
```

Diff MUST be empty (modulo whitespace). **Any column-type or partial-index mismatch = REJECT** per `feedback_migration_bootstrap_drift.md`. Bootstrap mirror should include the 4 new columns + 2 partial indexes B3 referenced.

### 4. **Amendment H invocation-path audit (CRITICAL)**

Per amended brief §10: 3 completion paths must call `_maybe_respawn_recurring()`. Verify all 3:

```bash
grep -nE "_maybe_respawn_recurring" orchestrator/deadline_manager.py triggers/clickup_trigger.py models/deadlines.py
```

Expect: ≥1 match in EACH file. **Reject if any of the 3 missing** — that's exactly the AO PM / MOVIE AM sidebar-door bug Amendment H exists to prevent.

Additionally verify line numbers from B3 ship report:
- `orchestrator/deadline_manager.py:878` — `complete_deadline()` direct call
- `triggers/clickup_trigger.py:540` — re-uses transaction conn (per B3 ship: "re-uses transaction conn")
- `models/deadlines.py:395` — `complete_critical()` per B3 ship

### 5. Auto-dismiss exclusion verification

```bash
grep -B2 -A6 "_auto_dismiss_overdue_deadlines\|_auto_dismiss_soft_deadlines" orchestrator/deadline_manager.py | grep -E "recurrence IS NULL|AND recurrence"
```

Expect: ≥2 matches (one per auto-dismiss function). Reject if either function lacks the `AND recurrence IS NULL` guard — race window risk against Director's manual completion + child respawn.

### 6. dependency `python-dateutil` added

```bash
grep "python-dateutil\|python_dateutil" requirements.txt
python3 -c "import dateutil.relativedelta; print('dateutil OK')"  # post pip install
```

Expect: `python-dateutil>=2.8.0` (or compatible) line in requirements.txt; import succeeds.

### 7. compute_next_due() edge-case coverage

B3 ship report claims clamping for: Jan 31→Feb 28/29, Nov 30 quarterly→Feb 28/29, Feb 29 annual→Feb 28. Verify:

```bash
grep -B2 -A 20 "def compute_next_due" orchestrator/deadline_manager.py | head -40
pytest tests/test_deadline_recurrence.py -v -k "feb or leap or end_of_month or clamp" 2>&1 | tail -15
```

Expect: explicit edge cases handled in code AND tests. ≥3 leap/clamp tests passing.

### 8. _maybe_respawn_recurring idempotency + cap-rate

```bash
grep -B2 -A 30 "def _maybe_respawn_recurring" orchestrator/deadline_manager.py | head -50
pytest tests/test_deadline_recurrence.py -v -k "idempotent or cap_rate or chain_root" 2>&1 | tail -15
```

Expect: idempotency check (existing child with same anchor short-circuits); cap-rate 1/day per chain root; Slack DM via `_safe_post_dm` on cap hit; chain-root resolution (walk `parent_deadline_id` to root).

### 9. dismiss_deadline UX — scope='instance' vs 'recurrence'

```bash
grep -B2 -A 20 "def dismiss_deadline" orchestrator/deadline_manager.py | head -30
```

Expect: `scope` param with default `'instance'` (chain stays alive); `'recurrence'` flips parent's `recurrence` to NULL (halts chain). Verify behavior with test.

### 10. 26/26 tests pass + regression delta

```bash
pytest tests/test_deadline_recurrence.py -v 2>&1 | tail -30
pytest tests/ 2>&1 | tail -3
```

Expect `26 passed` for the new file (B3 reported); full suite `+26 passes, 0 new failures` per ship report.

### 11. Singleton check

```bash
bash scripts/check_singletons.sh
```

Expect: `OK: No singleton violations found.` (per Code Brief Standard #8)

### 12. Schema verification — partial indexes

B3 mentioned "2 partial indexes" alongside the 4 columns. Verify:

```bash
grep -E "CREATE.*INDEX.*deadlines.*WHERE\|CREATE.*INDEX.*recurrence" migrations/20260426_amex_recurrence.sql memory/store_back.py
```

Expect: ≥2 partial-index definitions (likely on `recurrence IS NOT NULL` + `parent_deadline_id IS NOT NULL` for chain queries).

### 13. AmEx #1438 acceptance test deferred to post-merge

B3 ship report: "Acceptance test on AmEx #1438 deferred to post-merge handoff (production DB write)". Acceptable rationale — production DB write must wait for code on main. Verify the deferred handoff is documented in B3 ship report + a follow-up Tier B step is named (post-merge AI Head B executes the AmEx conversion via `baker_raw_write` after monitoring deploy stability).

### 14. CHANDA #2 ledger atomicity (cross-capability writes)

`_maybe_respawn_recurring` writes a NEW deadline row in same transaction as the parent's status update? Or separate transaction? Verify:

```bash
grep -B5 -A 30 "_maybe_respawn_recurring" orchestrator/deadline_manager.py | head -60
```

Expect: respawn child INSERT happens in the SAME transaction as the parent's UPDATE (or with explicit handling of failure mode where parent updates but child INSERT fails — log to `deadline_recurrence_failures` table per brief §3 fallback).

---

## If 14/14 green

Post APPROVE on PR #68 (`gh pr review 68 --approve`). AI Head B merges (`gh pr merge 68 --squash --delete-branch`). §3 hygiene mark this mailbox COMPLETE post-merge.

**Post-merge handoff to AI Head B (Tier B):**
- AmEx #1438 conversion via Baker MCP `baker_raw_write`:
  ```sql
  UPDATE deadlines SET recurrence = 'monthly', recurrence_anchor_date = '2026-05-03' WHERE id = 1438 RETURNING id, recurrence, recurrence_anchor_date;
  ```
- Verify next-due math: `complete_deadline()` on a test row → child spawned with `due_date = 2026-06-03`.

## If any check fails

`gh pr review 68 --request-changes` with specific list. Route back to B3 for fix-back. Do NOT merge.

## Ship report

`briefs/_reports/B1_pr68_amex_recurring_deadline_1_review_20260426.md` — include all 14 check outputs literal. PR comment summary linking to ship report.

---

## Trigger class note

AMEX_RECURRING_DEADLINE_1 is **MEDIUM** trigger class (DB migration + 3-path cross-capability state writes per Amendment H). Situational-review rule auto-fires per `2026-04-24-b1-situational-review-trigger.md`. AI Head solo-merge would be a process violation. Hold merge until B1 APPROVE.

## Timebox

**~30–45 min.** 14 checks, mostly mechanical. Special focus on Amendment H (#4) + auto-dismiss exclusion (#5) + edge-case coverage (#7) — those are where B3's deviations / brief-amendment fixes land.

---

**Dispatch timestamp:** 2026-04-26 ~22:50 UTC
**Authority chain:** Director RA-21 2026-04-26 PM Q-resolutions + default-fallback → AI Head B brief amendment (post-PR-#66 EXPLORE) → B3 build (PR #68, commit `0dfed74`) → B1 review (this dispatch) → AI Head B merge (post-APPROVE).
