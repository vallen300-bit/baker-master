---
brief_id: BACKFILL_SCRIPT_ENV_PREFLIGHT_1
authored_by: lead (AH1-Terminal)
authored_at: 2026-05-22T17:35:00Z
matter_slug: baker-internal
target_repo: baker-master
priority: tier-b
tier: B
director_ratified: 2026-05-22 chat — "go" on §X batch-ratification (Group B item 24)
reply_to: lead
---

# BRIEF_BACKFILL_SCRIPT_ENV_PREFLIGHT_1

## Bottom line

`scripts/backfill_meeting_transcripts_matter_slug.py` (and any sibling that goes through `SentinelStoreBack._get_global_instance()` or directly uses `kbl/voyage_client.py` + `kbl/db.py`) silently fails with cryptic errors when env vars are missing. Heavy init requires VOYAGE_API_KEY (even for UPDATE-only paths — voyage client created in `__init__`) + split POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE (NOT `DATABASE_URL`).

Add a `_check_required_env()` pre-flight at script entry that lists all required envs in ONE clear error before init touches anything. Failure mode: 2026-05-22 ~15:40Z first `--apply` attempt failed twice before all envs were sourced from 1P — burned ~10min on cryptic `voyageai.AuthenticationError` and "DB unreachable" stacktraces.

## Context

### Surface contract: N/A — pure backend CLI script. No clickable surface. No new endpoint. Logging-only diff path.

## Director ratification

2026-05-22 chat — "go" on §X batch-ratification, Group B item 24. Concept ratified; AH1 owns design.

## Scope

**In scope:**
- `scripts/backfill_meeting_transcripts_matter_slug.py` — add `_check_required_env()` invocation at top of `main()` before any other init.
- `scripts/backfill_matter_slug.py` (the deadlines variant) — same fix, symmetric.
- New tests: env-missing case produces clear error + non-zero exit; env-present case proceeds.

**Out of scope:**
- Other one-off scripts that don't touch SentinelStoreBack. Generalization to all scripts is a future refactor — flag as candidate follow-up but DO NOT scope-creep this brief.
- Runtime-server code (`outputs/dashboard.py`, etc.) — already runs under Render envs; not the same failure mode.

## Acceptance criteria

**AC1 — Pre-flight at script entry.**
`main()` first action (before any class instantiation or DB connect) calls `_check_required_env()`. Function lives in the script itself (no shared helper module yet — keep it local v1; we'll refactor when 3+ scripts need it).

**AC2 — Required env list.**
The check fails fast if ANY of these are missing:
- `VOYAGE_API_KEY` (for voyage client at SentinelStoreBack init)
- `POSTGRES_HOST`
- `POSTGRES_PORT` (optional — default 5432; do NOT list as required)
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_SSLMODE` (if used by current connect path — verify before listing; do NOT list if unused)

Fallback handling: if `DATABASE_URL` is present, POSTGRES_* split is NOT required (mirrors kbl/db.py `_get_database_url()` precedence). The check supports either path.

**AC3 — Clear single-error report.**
Missing envs are reported as ONE error listing all missing names (not one error per env). Example output:

```
ERROR: missing required environment variables:
  - VOYAGE_API_KEY
  - POSTGRES_HOST
  - POSTGRES_DB
Set these in your shell or source from 1Password.
Examples:
  export VOYAGE_API_KEY="$(op read 'op://...')"
  export POSTGRES_HOST="..."
Exiting (no init was performed).
```

Exit code 2 (consistent with the script's other validation failures).

**AC4 — DRY-RUN skip.**
Either:
(a) the dry-run path (`python3 script.py` without args) skips the check (since dry-run may not need voyage to write to /tmp), OR
(b) the check runs regardless (uniform fail-fast behavior).

**Recommendation: (b)** — uniform behavior, simpler mental model, mirrors how the script behaves today (init runs on dry-run too). Doc the choice in code comment.

**AC5 — Both scripts patched symmetrically.**
`scripts/backfill_meeting_transcripts_matter_slug.py` + `scripts/backfill_matter_slug.py` get the same `_check_required_env()` function with identical env list. Reviewer diffs both files to confirm parity.

**AC6 — Tests.**
New file `tests/test_backfill_env_preflight.py`:
- Test 1: clear all envs → script exits 2 with single-error message naming all missing.
- Test 2: clear only VOYAGE_API_KEY → exits 2 with VOYAGE_API_KEY listed.
- Test 3: set DATABASE_URL + clear POSTGRES_* → check passes (DATABASE_URL fallback).
- Test 4: all envs present → no error from preflight (whether main() succeeds further depends on DB state, out of scope).

Use `monkeypatch.delenv` / `monkeypatch.setenv` for env manipulation. Don't touch real DB.

**AC7 — No regression in existing dry-run / apply flow.**
Existing pytest passes. Run `python3 scripts/backfill_meeting_transcripts_matter_slug.py` with full env set; confirm dry-run still produces proposal file unchanged.

## Implementation notes

Suggested function (placement: top of script, near imports, before `main()`):

```python
def _check_required_env() -> None:
    """Fail fast if required envs are missing. Lists all missing in one error."""
    required = []
    # Voyage client (used in SentinelStoreBack init)
    if not os.environ.get("VOYAGE_API_KEY"):
        required.append("VOYAGE_API_KEY")
    # Postgres: DATABASE_URL takes precedence; otherwise split vars required
    if not os.environ.get("DATABASE_URL"):
        for var in ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"):
            if not os.environ.get(var):
                required.append(var)
    if required:
        msg = (
            "ERROR: missing required environment variables:\n"
            + "\n".join(f"  - {v}" for v in required)
            + "\nSet these in your shell or source from 1Password.\n"
            + "Examples:\n"
            + "  export VOYAGE_API_KEY=\"$(op read 'op://Baker API Keys/VOYAGE_API_KEY/credential')\"\n"
            + "  # ... etc\n"
            + "Exiting (no init was performed)."
        )
        print(msg, file=sys.stderr)
        sys.exit(2)
```

Then in `main()`:

```python
def main(argv: Optional[list[str]] = None) -> int:
    _check_required_env()  # FAIL FAST before any heavy init
    args = _build_arg_parser().parse_args(argv)
    # ... rest unchanged
```

## Ship gate

- Literal `pytest` green; PR description includes pytest stdout for `tests/test_backfill_env_preflight.py`
- `bash scripts/check_singletons.sh` exits 0
- /security-review pass / NO_FINDINGS (script-only, low-surface — expect quick clear)

## Gate-1 + Gate-2 reviewer instructions

Reviewers MUST verify:
1. Both scripts get identical preflight functions (diff `scripts/backfill_meeting_transcripts_matter_slug.py` against `scripts/backfill_matter_slug.py` on the new function — should be byte-identical).
2. AC6 tests assert actual stderr content + exit code, not just function return value.
3. Run the script locally with `unset VOYAGE_API_KEY` and confirm clear error before any DB / network call is made.

## Reporting

Bus-post `lead` on PR open. Reply target per `dispatched_by` field in mailbox UPDATE.

```bash
BAKER_ROLE=bN ~/bm-bN/scripts/bus_post.sh lead \
  "ship/backfill-script-env-preflight-1 — PR #<N> open in baker-master; both backfill scripts patched + symmetric; <X> tests in test_backfill_env_preflight.py; pytest <Y/Y>; awaiting gate chain (gates 1+2 required; 3+4 skippable)." \
  ship/backfill-script-env-preflight-1
```
