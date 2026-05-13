---
brief_id: DEADLINE_FEEDBACK_LOOP_1
builder: B3
pr: 203
pr_url: https://github.com/vallen300-bit/baker-master/pull/203
branch: b3-deadline-feedback-loop
commit: c6bf0c6
brief_commit: eda284e
mailbox_commit: 3f1bfd3
predecessor_pr: 202 (merged 6c31b05)
state: AWAITING_REVIEW
bus_msg: 226
shipped_at: 2026-05-13T11:01Z
---

# B3 Ship Report — DEADLINE_FEEDBACK_LOOP_1

## What shipped

Phase 2 of the smart-classification arc. Opens the labeled click-feedback surface so phase 3 (Gemini classifier upgrade `SIGNAL_CLASSIFIER_TIER2_1`) has ground truth to train against.

### Part 1 — Migration

`migrations/20260513b_deadline_feedback.sql` — `deadline_feedback` table (9 cols, 3 indexes, CHECK on `feedback_type ∈ {confirm, mute, wrong_matter, wrong_deadline}`). Additive only; no FK, no cascade-delete (history-preserving for orphaned rows).

### Part 2 — Backend

- NEW `models/deadline_feedback.py`
  - `insert_feedback(...)` — fault-tolerant, rollback in except, returns `None` on degraded state.
  - `get_recent_feedback(limit=100)` — LIMIT-capped, hard ceiling 1000.
  - `VALID_FEEDBACK_TYPES` frozenset whitelist.
- NEW `POST /api/deadlines/{id}/feedback` (dashboard.py)
  - Verbs: `confirm` / `mute` / `wrong_matter` / `wrong_deadline`.
  - `confirm` → status flip to `completed` (mirrors `/complete`).
  - `mute` → status flip to `dismissed` (mirrors `/dismiss`).
  - `wrong_matter` → **no status flip; matter_slug NOT mutated on deadlines table**. Row stays visible; classifier label is corrected via the corpus row only.
  - `wrong_deadline` → status flip to `dismissed` with `dismissed_reason='wrong_deadline'` (distinct from generic dismiss so phase 3 sees the extraction-error signal).
  - 400 on unknown verb; 404 on unknown deadline.
  - `slug_normalize()` validates `corrected_matter_slug`; unknown slug → NULL in corpus row + warning log.
- NEW `GET /api/slug-registry?status=active|all` (dashboard.py) — thin wrapper over `kbl.slug_registry.active_slugs()` / `canonical_slugs()`.
- AUGMENT `/dismiss` → also writes `mute` corpus row before status flip. Feedback write wrapped in inner `try/except` so dismiss never fails on degraded feedback path.
- AUGMENT `/complete` → also writes `confirm` corpus row before status flip. Same fault-tolerance pattern.

### Part 3 — Frontend

- `outputs/static/app.js`:
  - 2 new triage pills on `cardType==='deadline'` branch (`⚠ Wrong Matter`, `✗ Not a Deadline`).
  - 4 new functions: `_deadlineWrongMatter` / `_deadlineSubmitWrongMatter` / `_deadlineWrongDeadline` / `_ensureActiveSlugsLoaded`.
  - Wrong-matter dropdown: **DOM-constructed** (`createElement` + `textContent` + `appendChild`). Zero `innerHTML` on dynamic content. Slug list cached in `window._activeSlugs` after first fetch.
- `outputs/static/index.html` — cache bump `app.js?v=112` → `?v=113`.
- `outputs/static/mobile.html` / `mobile.js` — untouched (verified clean grep — they don't render deadlines).

### Part 4 — Tests

`tests/test_deadline_feedback.py` — 9 tests:

| # | Test | Type |
|---|---|---|
| 1 | `test_valid_feedback_types_whitelist` | unit |
| 2 | `test_insert_feedback_rejects_invalid_type` | unit (monkeypatch) |
| 3 | `test_unknown_slug_normalize_returns_none` | unit (BAKER_VAULT_PATH-gated) |
| 4 | `test_insert_feedback_returns_none_on_no_connection` | unit (monkeypatch) |
| 5 | `test_insert_feedback_round_trip` | live-PG |
| 6 | `test_endpoint_writes_corpus_row` | live-PG |
| 7 | `test_endpoint_rejects_unknown_feedback_type` | live-PG |
| 8 | `test_dismiss_endpoint_writes_mute_corpus_row` | live-PG (backward-compat) |
| 9 | `test_complete_endpoint_writes_confirm_corpus_row` | live-PG (backward-compat) |

## Ship gates — literal output

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_deadline_feedback.py -v
collected 9 items

tests/test_deadline_feedback.py::test_valid_feedback_types_whitelist PASSED   [ 11%]
tests/test_deadline_feedback.py::test_insert_feedback_rejects_invalid_type PASSED [ 22%]
tests/test_deadline_feedback.py::test_unknown_slug_normalize_returns_none SKIPPED [ 33%]
tests/test_deadline_feedback.py::test_insert_feedback_returns_none_on_no_connection PASSED [ 44%]
tests/test_deadline_feedback.py::test_insert_feedback_round_trip SKIPPED       [ 55%]
tests/test_deadline_feedback.py::test_endpoint_writes_corpus_row SKIPPED       [ 66%]
tests/test_deadline_feedback.py::test_endpoint_rejects_unknown_feedback_type SKIPPED [ 77%]
tests/test_deadline_feedback.py::test_dismiss_endpoint_writes_mute_corpus_row SKIPPED [ 88%]
tests/test_deadline_feedback.py::test_complete_endpoint_writes_confirm_corpus_row SKIPPED [100%]
========================= 3 passed, 6 skipped in 0.03s =========================

(With BAKER_VAULT_PATH=/Users/dimitry/baker-vault):
========================= 4 passed, 5 skipped in 0.04s =========================
```

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.

$ python3 -c "import py_compile; py_compile.compile('models/deadline_feedback.py', doraise=True)"
$ python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"
$ python3 -c "import py_compile; py_compile.compile('tests/test_deadline_feedback.py', doraise=True)"
(all clean — no output, exit 0)
```

CI run will lift the 5 live-PG-gated tests via ephemeral Neon branch (`TEST_DATABASE_URL` auto-provisioned per repo CLAUDE.md).

## Variances from brief

- **Test #3** (`test_unknown_slug_normalize_returns_none`) gated on `BAKER_VAULT_PATH` (brief had it unconditional). Reason: `kbl.slug_registry._resolve_yaml_path()` raises if env var missing; the brief's pre-flight assumed `BAKER_VAULT_PATH` set but the test environment doesn't always have it. Test runs under CI + locally when env is set; skips cleanly otherwise.
- **Test #4** (`test_insert_feedback_returns_none_on_no_connection`) added beyond brief's 7-test floor for `no-connection` coverage of `insert_feedback`'s fault tolerance — 1 more unit test, no extra surface area.
- **Test #2 monkeypatch target** changed from `models.deadlines` to `models.deadline_feedback` namespace. Reason: `from models.deadlines import get_conn` binds the name into `deadline_feedback`'s module namespace at import time; patching the source module would not affect the consumer's local binding. Result still correct (assertion `call_count == 0` holds because invalid-type guard returns before `get_conn` is reached).
- **Test #8 + #9** (backward-compat coverage): split into 2 tests (dismiss vs complete) for symmetric coverage. Brief explicitly called out "backward-compat dismiss/complete corpus capture" in mailbox.
- **Backend fault tolerance** on augmented `/dismiss` + `/complete`: inner `try/except` around `insert_feedback` call so the corpus write can never crash the status flip. `models.deadline_feedback.insert_feedback` is already fault-tolerant internally, but the outer guard is belt + suspenders per the brief's hard constraint *"failures inside it return `None` + log; they MUST NOT raise to the calling endpoint."*

## Out of scope (NOT shipped — phase boundary)

- Phase 3 Gemini classifier upgrade (`SIGNAL_CLASSIFIER_TIER2_1`) — separate brief, gated on 2+ weeks corpus from this PR
- Phase 4 multi-dim envelope JSONB column on `deadlines` / `signal_queue` — phase 4 brief
- `_match_matter_slug()` / `orchestrator/pipeline.py` — phase 3 territory
- `outputs/static/mobile.html` / `mobile.js` — verified clean grep (0 hits for `deadline`)
- `models/deadlines.py` table-creation bootstrap — migration owns the new table

## Files modified

| Path | LOC | Type |
|---|---|---|
| `migrations/20260513b_deadline_feedback.sql` | +38 | NEW |
| `models/deadline_feedback.py` | +109 | NEW |
| `outputs/dashboard.py` | +124 / -3 | MODIFY |
| `outputs/static/app.js` | +125 | MODIFY |
| `outputs/static/index.html` | +1 / -1 | cache bump |
| `tests/test_deadline_feedback.py` | +175 | NEW |

**Total: 572 lines added, 3 removed.**

## Awaiting

4-gate chain per brief's `mandatory_2nd_pass: true` + `security_review_required: true`:

1. AH2 static review
2. AH2 `/security-review` (DB migration trigger + new endpoint with user-derived body)
3. picker-architect
4. `feature-dev:code-reviewer` agent (AH1 fires after gates 1-3)

All 4 gates must clear before merge.

## Bus

- Ship post: `msg_id=226`, topic `ship/DEADLINE_FEEDBACK_LOOP_1`, thread `955f9044-3c6e-457e-8f51-c0b9b375e23c`
