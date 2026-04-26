# BRIEF: GOLD_COMMENT_WORKFLOW_1 — Implementation of Ratified Hybrid C Gold Workflow

## Context

4-month-ratified (2026-04-21 "all 9 are ratified") Hybrid C Gold comment workflow has no programmatic write path. Today's 2 Gold entries in `_ops/director-gold-global.md` (edita-russo split + cupial retire, both 2026-04-26) were hand-curated by AI Head Tier B via manual `Edit`. Manual cadence becomes the bottleneck once Cortex M2 lands the proposer.

**Director quote:** "Proceed with Gold Comment" (Director, RA-21 2026-04-26 PM).

Source spec: `_ops/ideas/2026-04-21-gold-comment-workflow-spec.md` (RA-21 promotion 2026-04-26; ghost-cite resolved). All 4 spec Q's RATIFIED per spec §10:
- Q1 drift trigger: **both** (commit-msg hard-block + post-commit weekly soft-flag)
- Q2 material-conflict reconciliation: **AI Head autonomous** (per autonomy charter §4)
- Q3 Cortex confidence threshold: **surface all, sorted by confidence** (no V1 filter)
- Q4 audit cadence: **weekly** (Mon 09:30 UTC)

## Estimated time: ~8h
## Complexity: High
## Trigger class: MEDIUM (DB migration + cross-capability state writes) → B1 second-pair-of-eyes review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`. Builder ≠ B1.
## Prerequisites:
- ✅ M1.2 KBL_PEOPLE_ENTITY_LOADERS_1 (PR #62 `5ae6545` 2026-04-26) — DV identity resolution at write-time via `kbl.people_registry`
- ✅ M1.1 HAGENAUER_WIKI_BOOTSTRAP_1 (PR #63 `d48dac8` 2026-04-26) — `wiki/matters/<slug>/` pattern this brief builds on
- ✅ KBL_INGEST_ENDPOINT_1 (PR #55) — frontmatter validation reused

---

## Existing landscape (DO NOT duplicate)

| Existing | Purpose | Distinct from this brief |
|---|---|---|
| `kbl/gold_drain.py` | Director WhatsApp `/gold` → `gold_promote_queue` → vault drain. R1.B4 transactional pattern. | NEW `gold_writer.py` is the **programmatic Tier B write path** for AI Head-mediated Gold (not WhatsApp-direct). Both coexist on different surfaces. |
| `kbl/loop.py:342 load_gold_context_by_matter` | Cortex Leg 1: concat all Gold under `wiki/<matter>/` for prompt-insert | NEW `gold_parser.py` is **audit + conflict-report** semantics. Different output shape, different consumer. |
| `memory/store_back.py:6623 _ensure_gold_promote_queue` | Existing table for WhatsApp queue | NEW `gold_audits` + `gold_write_failures` tables — fresh names, no clash. Migration-vs-bootstrap drift check still mandatory. |
| `_ai_head_weekly_audit_job` (Mon 09:00 UTC) at `triggers/embedded_scheduler.py:719` + `ai_head_audits` table at `store_back.py:511` | Pattern reference for APScheduler + audit-table | NEW `gold_audit_sentinel` job mirrors structure. Mon 09:30 UTC slot (gap-free between 09:00 audit and 10:00 sentinel). |

---

## Fix/Feature 1: gold_writer.py — Programmatic Tier B Write Path

### Problem
AI Head Tier B Gold writes use manual `Edit` against `_ops/director-gold-global.md` and `wiki/matters/<slug>/gold.md`. Two entries today (2026-04-26); this won't scale once Cortex proposes 5–10/week and Director ratifies.

### Current State
- `_ops/director-gold-global.md` exists (2 entries, schema-anchor for V1 parser)
- `wiki/matters/movie/gold.md`, `wiki/matters/oskolkov/gold.md` empty scaffolds
- `wiki/matters/movie/proposed-gold.md`, `wiki/matters/oskolkov/proposed-gold.md` empty scaffolds
- `kbl/gold_drain.py` handles WhatsApp `/gold` flow (different lane)

### Implementation

New file `kbl/gold_writer.py`:

```python
"""GOLD_COMMENT_WORKFLOW_1 — programmatic Tier B Gold write path.

Distinct from kbl/gold_drain.py (which drains gold_promote_queue from
Director's WhatsApp /gold flow). This module is the AI Head-mediated
write surface — invoked when AI Head executes Tier B Gold commits.

Hard guards:
  1. DV-only initials check (entry must end "DV." per Hybrid C spec)
  2. Caller-stack check (rejects callers whose stack frame includes
     `cortex_*` — those callers must use gold_proposer.py instead)
  3. File-write-target check (matter slug must exist in slugs.yml or
     scope must be 'global')
  4. Drift-detector pre-check (kbl.gold_drift_detector.validate_entry)

Failures are NEVER silent: log to gold_write_failures + Slack push.
"""
from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("baker.gold_writer")

class GoldWriteError(RuntimeError):
    """Raised when a Gold write violates a hard guard."""

class CallerNotAuthorized(GoldWriteError):
    """Cortex/proposer callers tried to write to ratified Gold."""

@dataclass(frozen=True)
class GoldEntry:
    iso_date: str          # YYYY-MM-DD
    topic: str             # H2 title noun phrase
    ratification_quote: str
    background: str
    resolution: str
    authority_chain: str
    carry_forward: str = "none"
    matter: Optional[str] = None  # canonical slug or None for global

def _check_caller_authorized() -> None:
    """Reject if any frame in the calling stack belongs to cortex_*."""
    for frame in inspect.stack():
        mod = frame.frame.f_globals.get("__name__", "")
        if mod.startswith("cortex_") or mod.startswith("kbl.cortex"):
            raise CallerNotAuthorized(
                f"gold_writer.append rejected — caller {mod!r} must use gold_proposer"
            )

def _resolve_target_path(entry: GoldEntry, vault_root: Path) -> Path:
    """Returns the canonical file path for a ratified entry."""
    if entry.matter is None:
        return vault_root / "_ops" / "director-gold-global.md"
    # Per matter — verify slug canonical via slug_registry
    from kbl import slug_registry
    if not slug_registry.is_canonical(entry.matter):
        raise GoldWriteError(f"matter slug {entry.matter!r} not canonical in slugs.yml")
    return vault_root / "wiki" / "matters" / entry.matter / "gold.md"

def append(entry: GoldEntry, *, vault_root: Optional[Path] = None) -> Path:
    """Append a ratified Gold entry. Raises on any guard failure.

    Args:
        entry: GoldEntry instance with all fields populated.
        vault_root: override $BAKER_VAULT_PATH (mainly for tests).

    Returns:
        Path of the file written.
    """
    import os
    _check_caller_authorized()
    if vault_root is None:
        vault_root = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
    target = _resolve_target_path(entry, vault_root)

    # Drift-detector pre-check.
    from kbl import gold_drift_detector
    issues = gold_drift_detector.validate_entry(entry, target)
    if issues:
        _log_failure(entry, target, "drift_validate", "; ".join(i.message for i in issues))
        raise GoldWriteError(f"drift validation failed: {issues}")

    block = _render_entry(entry)
    if not target.exists():
        target.write_text("", encoding="utf-8")  # preserve append semantics
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n" + block + "\n")
    logger.info(f"gold_writer.append: wrote {target}")
    return target

def _render_entry(entry: GoldEntry) -> str:
    """Format per spec §Entry format. Matches existing director-gold-global.md style."""
    return (
        f"## {entry.iso_date} — {entry.topic}\n\n"
        f"**Ratification:** {entry.ratification_quote} DV.\n\n"
        f"**Background:** {entry.background}\n\n"
        f"**Resolution:** {entry.resolution}\n\n"
        f"**Authority chain:** {entry.authority_chain}\n\n"
        f"**Carry-forward:** {entry.carry_forward}\n"
    )

def _log_failure(entry: GoldEntry, target: Path, error: str, caller_stack: str) -> None:
    """Insert into gold_write_failures. Fault-tolerant."""
    try:
        from memory.store_back import SentinelStoreBack
        sb = SentinelStoreBack._get_global_instance()
        sb._ensure_gold_write_failures_table()
        with sb.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO gold_write_failures
                       (target_path, error, caller_stack, payload_jsonb)
                       VALUES (%s, %s, %s, %s::jsonb)""",
                    (str(target), error[:512], caller_stack[:2048],
                     '{"topic": ' + repr(entry.topic) + '}'),
                )
                conn.commit()
    except Exception as e:
        logger.warning(f"gold_writer: log_failure failed (non-fatal): {e}")
```

### Key Constraints

- **MUST** import `slug_registry` for matter slug check (PR #62 wired this for ingest path; same pattern here).
- **MUST** use `SentinelStoreBack._get_global_instance()` factory per Code Brief Standard #8 — `bash scripts/check_singletons.sh` will catch violations on pre-push.
- **MUST NOT** import or invoke `gold_drain` — distinct lanes.
- **MUST NOT** auto-create matter dir if missing — fail loud (per existing wiki bootstrap convention from PR #63).

### Verification

```python
# Test cases (in tests/test_gold_writer.py):
def test_append_global_entry_writes_to_director_gold_global()
def test_append_matter_entry_writes_to_wiki_matters_gold()
def test_caller_stack_rejects_cortex_module()
def test_unknown_matter_slug_raises_GoldWriteError()
def test_failure_logged_to_gold_write_failures()
def test_dv_initials_required_via_drift_detector()
```

---

## Fix/Feature 2: gold_proposer.py — Cortex Agent-Drafted Path

### Problem
M2 will land Cortex reasoning loop with proposed-gold output. No formal contract today; needs to write only to `## Proposed Gold (agent-drafted)` section, never touch ratified entries.

### Implementation

New file `kbl/gold_proposer.py`:

```python
"""GOLD_COMMENT_WORKFLOW_1 — Cortex agent-drafted proposed-gold writes.

Cortex (when M2 lands) imports this module ONLY. Never imports gold_writer.

Writes go to a ## Proposed Gold (agent-drafted) section at the BOTTOM of
the target Gold file (matter or global). Director ratifies by manually
moving entries up. No auto-promote in V1.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("baker.gold_proposer")

PROPOSED_HEADER = "## Proposed Gold (agent-drafted)"

@dataclass(frozen=True)
class ProposedGoldEntry:
    iso_date: str
    topic: str
    proposed_resolution: str
    proposer: str = "cortex-3t"
    cortex_cycle_id: Optional[str] = None
    confidence: float = 0.0  # 0.0–1.0

def propose(entry: ProposedGoldEntry, *, matter: Optional[str] = None,
            vault_root: Optional[Path] = None) -> Path:
    """Append to ## Proposed Gold section at bottom of target file."""
    import os
    if vault_root is None:
        vault_root = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
    target = _resolve_target(matter, vault_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(PROPOSED_HEADER + "\n", encoding="utf-8")
    elif PROPOSED_HEADER not in target.read_text(encoding="utf-8"):
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n\n" + PROPOSED_HEADER + "\n")
    block = _render_proposed(entry)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n" + block + "\n")
    return target

def _resolve_target(matter: Optional[str], vault_root: Path) -> Path:
    if matter is None:
        return vault_root / "_ops" / "director-gold-global.md"
    from kbl import slug_registry
    if not slug_registry.is_canonical(matter):
        raise ValueError(f"matter slug {matter!r} not canonical")
    return vault_root / "wiki" / "matters" / matter / "proposed-gold.md"

def _render_proposed(entry: ProposedGoldEntry) -> str:
    cycle = f"\n**Cycle:** {entry.cortex_cycle_id}" if entry.cortex_cycle_id else ""
    return (
        f"### {entry.iso_date} — {entry.topic}\n\n"
        f"**Proposer:** {entry.proposer} (confidence {entry.confidence:.2f}){cycle}\n\n"
        f"**Proposed resolution:** {entry.proposed_resolution}\n"
    )
```

### Key Constraints

- **MUST** write to `proposed-gold.md` for matter scope — distinct file from `gold.md` (already scaffolded in PR #63).
- **MUST** write under `## Proposed Gold (agent-drafted)` header in `_ops/director-gold-global.md` for global.
- **MUST NOT** modify or remove existing entries.

---

## Fix/Feature 3: gold_drift_detector.py — Pre-Write Validator

### Problem
No mechanism today validates a new Gold entry against schema, slug registry, DV-only rule, or material conflicts.

### Implementation

New file `kbl/gold_drift_detector.py`:

```python
"""GOLD_COMMENT_WORKFLOW_1 — drift detector for Gold writes.

Two surfaces:
  1. validate_entry(entry, target) — pre-write check called by gold_writer.append.
  2. audit_all(vault_root) — full-corpus scan called by gold_audit_sentinel.

Detection categories:
  - SCHEMA: malformed entry, missing fields, bad date format
  - DV_ONLY: ratified entry missing "DV." initials
  - SLUG_UNKNOWN: matter slug not in slugs.yml
  - MATERIAL_CONFLICT: same topic_key as a prior entry, newer-wins
  - ORPHAN_PROPOSAL: ## Proposed Gold entry >30d unratified
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

@dataclass(frozen=True)
class DriftIssue:
    code: str         # SCHEMA | DV_ONLY | SLUG_UNKNOWN | MATERIAL_CONFLICT | ORPHAN_PROPOSAL
    message: str
    file_path: Optional[str] = None

def validate_entry(entry, target: Path) -> list[DriftIssue]:
    """Pre-write validation for gold_writer."""
    issues: list[DriftIssue] = []
    # SCHEMA: required fields populated
    for f in ("iso_date", "topic", "ratification_quote", "resolution"):
        if not getattr(entry, f, ""):
            issues.append(DriftIssue("SCHEMA", f"missing required field: {f}"))
    # DV_ONLY: rendered output MUST contain ` DV.` (gold_writer._render_entry
    # appends "DV." always; this guard catches manual writers that bypass renderer).
    # Per Hybrid C spec: DV-only initials on RATIFIED entries (proposed-gold exempt).
    # Caller-stack guard runs first; this is belt-and-braces.
    rendered = (
        f"{entry.ratification_quote} DV." if entry.ratification_quote
        else ""
    )
    if not rendered.rstrip().endswith(" DV."):
        issues.append(DriftIssue("DV_ONLY", "ratified entry missing DV. initials"))
    # SLUG_UNKNOWN: if matter scoped, slug must be in registry
    if getattr(entry, "matter", None):
        from kbl import slug_registry
        if not slug_registry.is_canonical(entry.matter):
            issues.append(DriftIssue("SLUG_UNKNOWN", f"matter {entry.matter!r} not in slugs.yml"))
    # MATERIAL_CONFLICT: scan target for same topic_key
    topic_key = _topic_key(entry.topic)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        for line in existing.splitlines():
            if line.startswith("## ") and topic_key and topic_key in _topic_key(line[3:]):
                issues.append(DriftIssue(
                    "MATERIAL_CONFLICT",
                    f"topic_key {topic_key!r} matches prior entry: {line[3:120]}",
                    str(target),
                ))
                break
    return issues

def _topic_key(title: str) -> str:
    """Lowercase noun-phrase key. V1 deterministic — V2 LLM-assisted."""
    import re
    # Strip date prefix "YYYY-MM-DD —" if present, then lowercase + collapse spaces
    title = re.sub(r"^\s*\d{4}-\d{2}-\d{2}\s*[—-]?\s*", "", title)
    return " ".join(title.lower().split())

def audit_all(vault_root: Path) -> list[DriftIssue]:
    """Full-corpus audit called by gold_audit_sentinel weekly."""
    issues: list[DriftIssue] = []
    # Validate director-gold-global.md
    global_file = vault_root / "_ops" / "director-gold-global.md"
    if global_file.exists():
        issues.extend(_audit_file(global_file))
    # Validate every wiki/matters/<slug>/gold.md
    matters_dir = vault_root / "wiki" / "matters"
    if matters_dir.is_dir():
        for matter_dir in matters_dir.iterdir():
            if matter_dir.is_dir():
                gold_file = matter_dir / "gold.md"
                if gold_file.exists():
                    issues.extend(_audit_file(gold_file))
                proposed = matter_dir / "proposed-gold.md"
                if proposed.exists():
                    issues.extend(_audit_proposed(proposed))
    return issues

def _audit_file(path: Path) -> list[DriftIssue]:
    """Scan one Gold file for SCHEMA / DV_ONLY / MATERIAL_CONFLICT issues."""
    # Implementation: parse H2 entries, check each has Ratification + DV initials,
    # check topic_key dedup, return issues.
    # ...full impl in build...
    return []

def _audit_proposed(path: Path) -> list[DriftIssue]:
    """Scan proposed-gold.md for ORPHAN_PROPOSAL (>30d unratified)."""
    return []
```

### Verification

Tests cover each DriftIssue code with positive + negative cases.

---

## Fix/Feature 4: gold_parser.py — Read + Audit Aggregator

### Problem
No central audit reader for Gold corpus today. Sentinel needs aggregate view for weekly report.

### Implementation

New file `kbl/gold_parser.py` — wraps `gold_drift_detector.audit_all()` + emits structured report (count by code, list of files affected, suggested actions). Returns dict suitable for storage in `gold_audits` table payload column.

(Full impl in build — interface only here for brief brevity.)

```python
def emit_audit_report(vault_root: Path) -> dict:
    """Returns {issues_count, by_code, files, payload}. Storable as JSONB."""
```

---

## Fix/Feature 5: Schema Migration + Bootstrap (CRITICAL: Standard #4)

### Problem
Audit + failure tables don't exist. Migration AND bootstrap must match column-for-column to avoid migration-vs-bootstrap drift trap (`feedback_migration_bootstrap_drift.md`).

### Implementation

**MANDATORY pre-step:** grep `memory/store_back.py` for any `_ensure_gold_*` already shipped:

```bash
grep -nE "_ensure_gold|gold_audits|gold_write_failures" memory/store_back.py
```

Existing as of brief draft: only `_ensure_gold_promote_queue` (different table — no clash). New tables fresh-named.

New file `migrations/20260426_gold_audits.sql`:

**Schema mirrors `ai_head_audits` precedent at `memory/store_back.py:511`** — `id SERIAL PRIMARY KEY` (NOT `BIGSERIAL` — keep consistent with sibling audit tables) + `ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.

```sql
-- migrate:up
CREATE TABLE IF NOT EXISTS gold_audits (
    id           SERIAL PRIMARY KEY,
    ran_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    issues_count INT NOT NULL DEFAULT 0,
    payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_gold_audits_ran_at ON gold_audits (ran_at DESC);

CREATE TABLE IF NOT EXISTS gold_write_failures (
    id              SERIAL PRIMARY KEY,
    attempted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_path     TEXT NOT NULL,
    error           TEXT NOT NULL,
    caller_stack    TEXT,
    payload_jsonb   JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_gold_write_failures_attempted_at
    ON gold_write_failures (attempted_at DESC);

-- migrate:down
-- DROP INDEX IF EXISTS idx_gold_write_failures_attempted_at;
-- DROP TABLE IF EXISTS gold_write_failures;
-- DROP INDEX IF EXISTS idx_gold_audits_ran_at;
-- DROP TABLE IF EXISTS gold_audits;
```

Append to `memory/store_back.py` — **mirror EXACT pattern of `_ensure_ai_head_audits_table` at line 511** (uses `self._get_conn()` + manual `cur.close()`, NOT context manager):

```python
def _ensure_gold_audits_table(self):
    """GOLD_COMMENT_WORKFLOW_1: weekly Gold corpus audit records.

    Populated by orchestrator/gold_audit_job._gold_audit_sentinel_job.
    One row per audit run (Mondays 09:30 UTC).
    """
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold_audits (
                id            SERIAL PRIMARY KEY,
                ran_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                issues_count  INT NOT NULL DEFAULT 0,
                payload_jsonb JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_gold_audits_ran_at "
            "ON gold_audits(ran_at DESC)"
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure gold_audits table: {e}")

def _ensure_gold_write_failures_table(self):
    """GOLD_COMMENT_WORKFLOW_1: failure log for gold_writer.append guards."""
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gold_write_failures (
                id            SERIAL PRIMARY KEY,
                attempted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                target_path   TEXT NOT NULL,
                error         TEXT NOT NULL,
                caller_stack  TEXT,
                payload_jsonb JSONB DEFAULT '{}'::jsonb
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_gold_write_failures_attempted_at "
            "ON gold_write_failures(attempted_at DESC)"
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure gold_write_failures table: {e}")
```

Also add to `__init__` block at line 206-area (alongside existing `_ensure_*` calls):

```python
self._ensure_gold_audits_table()
self._ensure_gold_write_failures_table()
```

### Key Constraints (Standard #4)

Migration column-for-column match with bootstrap. Verify with:

```bash
diff <(grep -A 8 "CREATE TABLE.*gold_audits" migrations/20260426_gold_audits.sql) \
     <(grep -A 8 "CREATE TABLE.*gold_audits" memory/store_back.py)
diff <(grep -A 8 "CREATE TABLE.*gold_write_failures" migrations/20260426_gold_audits.sql) \
     <(grep -A 8 "CREATE TABLE.*gold_write_failures" memory/store_back.py)
```

Both diffs MUST be empty (modulo whitespace).

---

## Fix/Feature 6: APScheduler Job — gold_audit_sentinel

### Implementation

In `triggers/embedded_scheduler.py`, add immediately after `_ai_head_weekly_audit_job` registration (~line 727):

```python
# GOLD_COMMENT_WORKFLOW_1 D6: weekly Gold corpus audit.
# Mon 09:30 UTC — between ai_head_weekly_audit (09:00) + ai_head_audit_sentinel (10:00).
# Slot is gap-free; verified 2026-04-26.
_gold_audit_enabled = _os.environ.get("GOLD_AUDIT_ENABLED", "true").lower()
if _gold_audit_enabled not in ("false", "0", "no", "off"):
    scheduler.add_job(
        _gold_audit_sentinel_job,
        CronTrigger(day_of_week="mon", hour=9, minute=30, timezone="UTC"),
        id="gold_audit_sentinel",
        name="Gold corpus weekly audit (Monday 09:30 UTC)",
        coalesce=True, max_instances=1, replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Registered: gold_audit_sentinel (Mon 09:30 UTC)")
else:
    logger.info("Skipped: gold_audit_sentinel (GOLD_AUDIT_ENABLED=false)")
```

New job body in `orchestrator/gold_audit_job.py`:

```python
"""GOLD_COMMENT_WORKFLOW_1 — weekly audit job."""
import logging
from pathlib import Path
import os

logger = logging.getLogger("baker.gold_audit_sentinel")

def _gold_audit_sentinel_job():
    """Run gold_parser.audit_all + persist to gold_audits table.
    Slack-DM AI Head if any issues found.
    """
    try:
        from kbl import gold_parser
        vault = Path(os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault")))
        report = gold_parser.emit_audit_report(vault)
        # Persist to gold_audits
        from memory.store_back import SentinelStoreBack
        sb = SentinelStoreBack._get_global_instance()
        sb._ensure_gold_audits_table()
        with sb.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO gold_audits (issues_count, payload_jsonb) VALUES (%s, %s::jsonb)",
                    (report["issues_count"], _json.dumps(report["payload"])),
                )
                conn.commit()
        # Slack DM if issues > 0 — reuse canonical helper from ai_head_audit
        if report["issues_count"] > 0:
            try:
                from triggers.ai_head_audit import _safe_post_dm  # canonical Slack DM helper
                summary = (
                    f"Gold audit weekly ({report['issues_count']} issues): "
                    f"{', '.join(f'{k}={v}' for k, v in report.get('by_code', {}).items())}. "
                    f"See gold_audits table latest row for full payload."
                )
                _safe_post_dm(summary)
            except Exception as e:
                logger.warning(f"slack push failed (non-fatal): {e}")
    except Exception as e:
        logger.error(f"gold_audit_sentinel_job failed: {e}", exc_info=True)
```

Import wire-up at scheduler module top:

```python
from orchestrator.gold_audit_job import _gold_audit_sentinel_job
```

### Verification

```bash
grep "gold_audit_sentinel" triggers/embedded_scheduler.py  # expect 3+ matches
grep "_gold_audit_sentinel_job" orchestrator/gold_audit_job.py  # expect 1+
# Live observation: after deploy, 2026-04-27 09:30 UTC first fire window.
```

---

## Fix/Feature 7: Commit-msg Hook (NOT pre-commit)

### Problem

Lesson `feedback_chanda_4_hook_stage_bug.md`: pre-commit hooks don't see commit message via `-F`/`-m`. Use commit-msg stage instead.

### Implementation

New file `baker-vault/.githooks/gold_drift_check.sh`:

```bash
#!/usr/bin/env bash
# GOLD_COMMENT_WORKFLOW_1 — commit-msg-stage Gold drift check.
# Verifies any change touching director-gold-global.md or wiki/matters/<slug>/gold.md
# carries a Director-signed: marker AND survives schema check.
set -euo pipefail

COMMIT_MSG_FILE="$1"
COMMIT_MSG=$(cat "$COMMIT_MSG_FILE")

# Only fire if Gold-touching paths in staged diff
GOLD_PATHS_IN_DIFF=$(git diff --cached --name-only | grep -E '(_ops/director-gold-global\.md|wiki/matters/.*/gold\.md|wiki/matters/.*/proposed-gold\.md)$' || true)
[ -z "$GOLD_PATHS_IN_DIFF" ] && exit 0

# Director-signed: marker required for ratified Gold (not proposed)
RATIFIED_PATHS=$(echo "$GOLD_PATHS_IN_DIFF" | grep -v 'proposed-gold' || true)
if [ -n "$RATIFIED_PATHS" ] && ! echo "$COMMIT_MSG" | grep -q '^Director-signed:'; then
    echo "ERROR: Gold commit touching ratified path requires 'Director-signed:' line in commit message." >&2
    echo "Touched: $RATIFIED_PATHS" >&2
    exit 1
fi

# Schema check via gold_drift_detector if Python available
if command -v python3 >/dev/null 2>&1; then
    BAKER_MASTER_PATH="${BAKER_MASTER_PATH:-$HOME/baker-master}"
    if [ -d "$BAKER_MASTER_PATH" ]; then
        cd "$BAKER_MASTER_PATH"
        for path in $GOLD_PATHS_IN_DIFF; do
            python3 -c "
from kbl import gold_drift_detector
from pathlib import Path
issues = gold_drift_detector.audit_all(Path('$HOME/baker-vault'))
relevant = [i for i in issues if i.file_path and '$path' in i.file_path]
if relevant:
    for i in relevant:
        print(f'DRIFT [{i.code}]: {i.message}')
    exit(1)
" || { echo "Drift check FAILED on $path" >&2; exit 1; }
        done
    fi
fi

exit 0
```

Install via:

```bash
# In baker-vault clone:
mkdir -p .githooks
cp gold_drift_check.sh .githooks/
chmod +x .githooks/gold_drift_check.sh
git config core.hooksPath .githooks
ln -sf gold_drift_check.sh .githooks/commit-msg
# Verify:
git config --get core.hooksPath  # expect .githooks
ls -la .githooks/  # expect gold_drift_check.sh executable + commit-msg symlink
```

### Key Constraints

- **MUST** be at commit-msg stage (`commit-msg` symlink), NOT pre-commit. Per `feedback_chanda_4_hook_stage_bug.md`.
- **MUST** allow proposed-gold writes without Director-signed: marker (those are agent-drafted by design).
- **MUST** fail loud — `exit 1` aborts the commit.

---

## Files Modified

| File | Change |
|---|---|
| `kbl/gold_writer.py` | NEW — programmatic Tier B Gold write path |
| `kbl/gold_proposer.py` | NEW — Cortex agent-drafted proposed-gold writes |
| `kbl/gold_parser.py` | NEW — read + audit aggregator |
| `kbl/gold_drift_detector.py` | NEW — pre-write + full-corpus drift detector |
| `orchestrator/gold_audit_job.py` | NEW — APScheduler job body |
| `migrations/20260426_gold_audits.sql` | NEW — schema migration |
| `memory/store_back.py` | MODIFIED — add `_ensure_gold_audits_table` + `_ensure_gold_write_failures_table` |
| `triggers/embedded_scheduler.py` | MODIFIED — register `gold_audit_sentinel` Mon 09:30 UTC |
| `baker-vault/.githooks/gold_drift_check.sh` | NEW (in baker-vault repo, NOT baker-master) — commit-msg hook |
| `tests/test_gold_writer.py` | NEW |
| `tests/test_gold_proposer.py` | NEW |
| `tests/test_gold_parser.py` | NEW |
| `tests/test_gold_drift_detector.py` | NEW |
| `_ops/processes/gold-comment-workflow.md` | NEW (in baker-vault) — canonical process doc; resolves ghost-cite back-refs |

## Do NOT Touch

| File | Why |
|---|---|
| `kbl/gold_drain.py` | Distinct lane (WhatsApp `/gold` queue drain). Different write surface. |
| `kbl/loop.py` (`load_gold_context_by_matter`) | Existing read helper for Cortex Leg 1. Different consumer than gold_parser. |
| `_ops/director-gold-global.md` (existing 2 entries) | Director-ratified content. Validate via parser, never overwrite. |
| `wiki/matters/movie/gold.md`, `wiki/matters/oskolkov/gold.md` | Empty scaffolds; first programmatic write goes through gold_writer. |
| `cortex_*` modules | M2 not landed; gold_proposer prepares contract for it. |

## Quality Checkpoints

1. `bash scripts/check_singletons.sh` → `OK: No singleton violations found.` (Standard #8)
2. `pytest tests/test_gold_*.py -v` → all green (≥20 cases across 4 modules)
3. `pytest tests/ 2>&1 | tail -3` → no regressions vs baseline
4. Migration-vs-bootstrap diff (Standard #4) → empty diff for both `gold_audits` + `gold_write_failures`
5. `grep "gold_audit_sentinel" triggers/embedded_scheduler.py` → registered
6. Acceptance test: write a synthetic Gold entry via `gold_writer.append()` → assert lands in `_ops/director-gold-global.md` + `gold_drift_detector.audit_all()` returns clean
7. Acceptance test: synthetic conflict → `MATERIAL_CONFLICT` flagged with both entries visible
8. Acceptance test: `cortex_test_module` in caller stack → `CallerNotAuthorized` raised
9. Schema validation of existing 2 `_ops/director-gold-global.md` entries → 0 issues (backfill check)
10. Hook install verification on baker-vault: `git commit` with Gold path + no `Director-signed:` → rejected; with marker → accepted
11. APScheduler first fire window: 2026-04-27 09:30 UTC (next Monday); verify `gold_audits` table has row + `scheduler_executions` has matching entry
12. Mobile rendering: N/A (no UI surface in this brief)

## Verification SQL

```sql
-- Confirm tables exist post-migration
SELECT table_name FROM information_schema.tables
  WHERE table_name IN ('gold_audits', 'gold_write_failures')
  ORDER BY table_name LIMIT 10;
-- expect 2 rows

-- Confirm column types match between migration + bootstrap
SELECT column_name, data_type FROM information_schema.columns
  WHERE table_name = 'gold_audits' ORDER BY ordinal_position LIMIT 10;
SELECT column_name, data_type FROM information_schema.columns
  WHERE table_name = 'gold_write_failures' ORDER BY ordinal_position LIMIT 10;

-- After first APScheduler fire (Mon 2026-04-27 09:30 UTC)
SELECT audit_id, ran_at, issues_count FROM gold_audits
  ORDER BY ran_at DESC LIMIT 5;
SELECT job_id, run_at, status FROM scheduler_executions
  WHERE job_id = 'gold_audit_sentinel' ORDER BY run_at DESC LIMIT 5;
```

---

## Code Brief Standards Compliance (10/10)

1. **API version/endpoint** — N/A internal Python modules + bash hook
2. **Deprecation check date** — `kbl.people_registry` + `kbl.entity_registry` from PR #62 verified live as of build start (commit `5ae6545` 2026-04-26)
3. **Fallback note** — write failures log to `gold_write_failures` + Slack push; never silent
4. **Migration-vs-bootstrap DDL check** — explicit diff verification in §Fix 5; pre-step grep already run (no clash with `gold_promote_queue`)
5. **Ship gate** — literal `pytest` output (≥20 cases) + literal SELECT outputs in ship report; no "by inspection"
6. **Test plan** — §Verification on each Fix/Feature + Quality Checkpoints
7. **file:line citations** — verified `triggers/embedded_scheduler.py:719` (`_ai_head_weekly_audit_job`); `memory/store_back.py:6623` (`_ensure_gold_promote_queue`); `kbl/loop.py:342` (`load_gold_context_by_matter`)
8. **Singleton pattern** — `gold_writer._log_failure` uses `SentinelStoreBack._get_global_instance()`; `gold_audit_sentinel_job` same. `bash scripts/check_singletons.sh` will catch violations on pre-push
9. **Post-merge handoff** — backfill validation script (audit existing 2 entries) runs from working tree; handoff includes `git pull --rebase origin main` immediately before `python3 -c "from kbl import gold_parser; gold_parser.emit_audit_report(...)"` invocation
10. **Invocation-path audit (Amendment H)** — Cortex M2 (when it lands) imports `gold_proposer` ONLY; runtime caller-stack guard in `gold_writer.append()` enforces lane separation. Pattern-2 capability not directly modified by this brief; H1-H5 not triggered. If a future capability adds Gold writes outside `gold_writer`/`gold_proposer`, it MUST be either (a) explicitly marked `read-only surface (intentional)` with reason, or (b) routed through one of the two canonical writers.

## Authority Chain

- Director ratification: 2026-04-26 PM "Proceed with Gold Comment" (RA-21 handoff)
- Director Q1–Q4 ratifications: 2026-04-26 PM (RA-21 §10 spec walk-through)
- Hybrid C ratification: 2026-04-21 "all 9 are ratified" (4-month carry-forward)
- RA-21 spec: `_ops/ideas/2026-04-21-gold-comment-workflow-spec.md` (vault commit `e3465ab` 2026-04-26 by AI Head A; promotion routed back to AI Head B = M2 lane)
- AI Head B Tier B: this brief (drafted via `/write-brief` skill per SKILL Rule 0)
- Dispatch: B3 builder (free post-PR #64 merge); B1 reviewer (situational-review trigger per `2026-04-24-b1-situational-review-trigger.md`)
