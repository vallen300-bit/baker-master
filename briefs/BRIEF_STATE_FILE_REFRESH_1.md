# BRIEF: STATE_FILE_REFRESH_1 — nightly drift audit between cortex-config snapshots and authoritative state

## Context

Three drift scars in two weeks (2026-05-10 stale tracker labels, 2026-05-15 Aukera deadline 25-day stale, 2026-05-15 CYCLE_REGISTER 5-day stale → b3 duplicate dispatch) prove that derived snapshot files (Layer 2) silently drift from authoritative state (Layer 1) and there is no detection layer below "agent eyeballs it before acting." This brief ships the **3-4 week bridge** while the longer-term reconciler (BRIEF_STATE_RECONCILER_1 Phase 1) is in build, per Director ratification 2026-05-17 (6-Q mapping session + state-architecture research note `wiki/_ai-it/aid-t/library/state-architecture-best-practice-2026-05-16.md` + engineering audit `_ops/reviews/2026-05-17-ah1-engineering-audit-aid-state-architecture-note.md`).

**Scope this brief = AUDIT ONLY (read-only against the vault).** The reconciler that actually regenerates Layer 2 from Layer 1 is the separate BRIEF_STATE_RECONCILER_1. This brief detects drift; it does not fix it.

## Estimated time: ~2 builder-days
## Complexity: Low-Medium
## Prerequisites
- `BAKER_VAULT_PATH` env var already set on Render service (per `triggers/vault_scanner.py` precedent).
- APScheduler infrastructure live (`triggers/embedded_scheduler.py` already runs `vault_scanner` at 06:00 UTC daily).
- Singleton lock via `triggers/scheduler_lease.py` already gates dual-instance fires.

## API version / deprecation / fallback
- **No external API calls.** Internal filesystem scan (read-only) + ClickUp MCP write (one comment per fire; existing `mcp__baker__baker_clickup_tasks` already in fleet).
- ClickUp MCP last verified 2026-04-21 per AI Head LONGTERM.md.

---

## Problem statement (the failure mode in one paragraph)

22 `wiki/matters/<slug>/cortex-config.md` files carry Cortex Phase 2 routing config + Director-tuned thresholds + hand-curated frame. They drift from the authoritative state below them (Director ratifications in `wiki/matters/<slug>/curated/06_decisions_log.md`) because agents rewrite them by hand and forget. Today's failure mode: an agent reads a 25-day-stale cortex-config, makes a wrong decision (Aukera 25-day-stale incident), Director catches it manually. We need an automated nightly detector that surfaces drift candidates BEFORE an agent reads them wrong.

**Solution: a daily APScheduler job that reads cortex-config `updated:` field vs the latest dated decision in `curated/06_decisions_log.md`, posts drift candidates as a comment on a recurring ClickUp `drift-sentinel` task + writes a detailed report to the vault.**

---

## Current state

- `triggers/embedded_scheduler.py` — registers APScheduler jobs at FastAPI startup (`outputs/dashboard.py` calls `_register_jobs(scheduler)`); singleton lock via `triggers/scheduler_lease.py`.
- `triggers/vault_scanner.py` — the canonical precedent: daily 06:00 UTC vault scan of `_ops/agents/<desk>/tasks/active/*.md`. Has all the safety primitives we need (path-traversal protection, `BAKER_VAULT_PATH` resolution, `_parse_frontmatter`, day-boundary marker files, fault-tolerant DB writes).
- 22 cortex-config files exist at `wiki/matters/<slug>/cortex-config.md`. **8 have canonical curated/06_decisions_log.md** layout (mrci, aukera, lilienmatt, capital-call, annaberg, mo-vie-am, hagenauer-rg7, oskolkov). **14 have ad-hoc curated/ layouts** (movie, kitz, brisen-pr, claimsmax, etc.). The 8 canonical matters are where the drift class actually fires (live counterparty work, frequent ratifications); the other 14 stay manual until separate canonicalization brief.
- Director directive 2026-04-30: drift detection → ClickUp recurring task (tagged `drift-sentinel`), **NOT Slack DM**. Existing `drift-sentinel` task in BAKER space → Cortex Backlog list (ID `901523104264`) per `MEMORY.md` § Active Roadmap.

---

## Implementation

### File 1: NEW — `triggers/state_drift_audit.py` (~180 LOC)

```python
"""BRIEF_STATE_FILE_REFRESH_1 — nightly drift audit.

Fires at 03:00 UTC daily. Scans `wiki/matters/<slug>/cortex-config.md` files
in baker-vault, classifies by curated/ layout, and for canonical-layout
matters compares cortex-config `updated:` field against the newest dated
decision in `curated/06_decisions_log.md`. Surfaces drift candidates via:
  (a) detailed markdown report → `_ops/reports/state-drift-YYYY-MM-DD.md`
  (b) one summary comment on ClickUp `drift-sentinel` recurring task

READ-ONLY against the vault. The reconciler that actually fixes drift is
a separate brief (BRIEF_STATE_RECONCILER_1).

Singleton: APScheduler is already gated by scheduler_lease.py. No additional
locking.

State file: `_ops/agents/_scanner-state/state-drift-last-run.json` — tracks
last-seen-drift-set so we only surface NEW candidates (not the same 5 every
day).

Path-traversal hardening: matter slugs must match ^[a-z0-9-]+$ + resolve
to direct subdir of wiki/matters/ (no symlink follow). Per vault_scanner.py
precedent.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger("sentinel.state_drift_audit")

SLUG_RE = re.compile(r"^[a-z0-9-]+$")
DECISION_HEADING_RE = re.compile(r"^##\s+D-\d+.*\((\d{4}-\d{2}-\d{2})\)")
DRIFT_THRESHOLD_DAYS = 7  # cortex-config older than newest decision by > N days = candidate

DRIFT_TASK_ID = "86c9k6kau"  # SAME recurring `drift-sentinel` task ID used by orchestrator/roadmap_drift_sentinel.py:40
# (Reuse the existing drift surface; comments prefixed `[state-drift]` to disambiguate from roadmap-drift.
# If Director later wants split surfaces, AH1 creates a new task + flips this constant — single line change.)


@dataclass
class MatterAuditResult:
    slug: str
    layout_class: str  # "canonical" | "non_canonical_layout" | "missing_decisions_log"
    cortex_config_updated: Optional[date] = None
    newest_decision_date: Optional[date] = None
    lag_days: Optional[int] = None
    is_drift_candidate: bool = False
    notes: list[str] = field(default_factory=list)


def _vault_root() -> Path:
    raw = os.environ.get("BAKER_VAULT_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(os.path.expanduser("~/baker-vault"))


def _matters_dir() -> Path:
    return _vault_root() / "wiki" / "matters"


def _reports_dir() -> Path:
    return _vault_root() / "_ops" / "reports"


def _scanner_state_path() -> Path:
    return _vault_root() / "_ops" / "agents" / "_scanner-state" / "state-drift-last-run.json"


def _is_safe_slug(matters_dir: Path, slug: str) -> bool:
    """Reject slugs failing regex or pointing outside wiki/matters/.

    Mirrors vault_scanner._is_safe_desk_dir pattern.
    """
    if not SLUG_RE.match(slug):
        return False
    matter_path = matters_dir / slug
    try:
        if matter_path.is_symlink():
            return False
        if not matter_path.is_dir():
            return False
        if matter_path.resolve().parent != matters_dir.resolve():
            return False
    except OSError:
        return False
    return True


def _discover_matters(matters_dir: Path) -> list[str]:
    """Return matter slugs that have a cortex-config.md file."""
    if not matters_dir.is_dir():
        return []
    out = []
    try:
        entries = sorted(os.listdir(matters_dir))
    except OSError as e:
        logger.warning("state_drift_audit: listdir failed: %s", e)
        return []
    for name in entries:
        if name.startswith("_") or name.startswith("."):
            continue
        if not _is_safe_slug(matters_dir, name):
            continue
        if (matters_dir / name / "cortex-config.md").is_file():
            out.append(name)
    return out


def _parse_frontmatter(text: str) -> Optional[dict]:
    """Parse YAML frontmatter; return None on missing/malformed."""
    if not text.startswith("---"):
        return None
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return None
    raw = text[3:end_idx]
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.warning("state_drift_audit: bad frontmatter: %s", e)
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _newest_decision_date(decisions_log_path: Path) -> Optional[date]:
    """Scan curated/06_decisions_log.md for `## D-NNN ... (YYYY-MM-DD)` heads,
    return the max date found.

    Returns None if the file has no parseable decision headings (treat as
    "missing dated decisions" — not drift, separate class)."""
    try:
        text = decisions_log_path.read_text(encoding="utf-8")
    except OSError:
        return None
    dates: list[date] = []
    for line in text.splitlines():
        m = DECISION_HEADING_RE.match(line)
        if m:
            d = _coerce_date(m.group(1))
            if d is not None:
                dates.append(d)
    return max(dates) if dates else None


def _audit_matter(matters_dir: Path, slug: str) -> MatterAuditResult:
    """Run drift audit on one matter. Returns classified result."""
    result = MatterAuditResult(slug=slug, layout_class="canonical")
    cortex_config_path = matters_dir / slug / "cortex-config.md"
    decisions_log_path = matters_dir / slug / "curated" / "06_decisions_log.md"

    # Read cortex-config frontmatter
    try:
        cc_text = cortex_config_path.read_text(encoding="utf-8")
    except OSError as e:
        result.notes.append(f"cortex-config.md unreadable: {e}")
        return result
    fm = _parse_frontmatter(cc_text)
    if fm is None:
        result.notes.append("cortex-config.md missing/malformed frontmatter")
        return result
    result.cortex_config_updated = _coerce_date(fm.get("updated"))
    if result.cortex_config_updated is None:
        result.notes.append("cortex-config frontmatter missing `updated:` field")

    # Classify layout
    if not decisions_log_path.is_file():
        result.layout_class = "non_canonical_layout"
        result.notes.append("no curated/06_decisions_log.md — needs canonicalization (separate brief)")
        return result

    # Drift check (canonical layout)
    newest = _newest_decision_date(decisions_log_path)
    if newest is None:
        result.layout_class = "missing_decisions_log"
        result.notes.append("06_decisions_log.md exists but no `## D-NNN ... (YYYY-MM-DD)` headings parsed")
        return result
    result.newest_decision_date = newest

    if result.cortex_config_updated is None:
        result.notes.append("cannot compute lag — cortex_config `updated:` missing")
        return result

    lag = (newest - result.cortex_config_updated).days
    result.lag_days = lag
    if lag > DRIFT_THRESHOLD_DAYS:
        result.is_drift_candidate = True
    return result


def _load_last_run_state() -> dict:
    path = _scanner_state_path()
    if not path.is_file():
        return {"last_run_utc": None, "seen_candidates": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("state_drift_audit: state file unreadable, treating as empty: %s", e)
        return {"last_run_utc": None, "seen_candidates": {}}


def _save_run_state(state: dict) -> None:
    path = _scanner_state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + rename
        tmp = path.with_suffix(path.suffix + ".tmp." + os.urandom(4).hex())
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("state_drift_audit: state file write failed: %s", e)


def _write_report(results: list[MatterAuditResult], today: date) -> Path:
    reports_dir = _reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"state-drift-{today.isoformat()}.md"

    lines: list[str] = [
        f"# State drift audit — {today.isoformat()}",
        "",
        f"**Run:** {datetime.now(timezone.utc).isoformat()}",
        f"**Matters scanned:** {len(results)}",
        "",
    ]

    drift = [r for r in results if r.is_drift_candidate]
    non_canonical = [r for r in results if r.layout_class == "non_canonical_layout"]
    missing_log = [r for r in results if r.layout_class == "missing_decisions_log"]
    clean = [r for r in results if r.layout_class == "canonical" and not r.is_drift_candidate and not r.notes]

    lines.append(f"## Summary")
    lines.append("")
    lines.append(f"- Drift candidates: **{len(drift)}**")
    lines.append(f"- Non-canonical layout (needs canonicalization brief): {len(non_canonical)}")
    lines.append(f"- Canonical but no dated decisions parsable: {len(missing_log)}")
    lines.append(f"- Clean (canonical + within {DRIFT_THRESHOLD_DAYS}d threshold): {len(clean)}")
    lines.append("")

    if drift:
        lines.append("## Drift candidates")
        lines.append("")
        lines.append("| Matter | cortex-config updated | newest decision | lag (days) |")
        lines.append("|---|---|---|---|")
        for r in drift:
            lines.append(
                f"| `{r.slug}` | {r.cortex_config_updated} | {r.newest_decision_date} | {r.lag_days} |"
            )
        lines.append("")

    if non_canonical:
        lines.append("## Non-canonical layout (canonicalization brief target)")
        lines.append("")
        for r in non_canonical:
            lines.append(f"- `{r.slug}` — {'; '.join(r.notes)}")
        lines.append("")

    if missing_log:
        lines.append("## Canonical layout but no parseable decisions")
        lines.append("")
        for r in missing_log:
            lines.append(f"- `{r.slug}` — {'; '.join(r.notes)}")
        lines.append("")

    # Atomic write
    tmp = report_path.with_suffix(report_path.suffix + ".tmp." + os.urandom(4).hex())
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, report_path)
    return report_path


def _post_clickup_summary(
    drift_results: list[MatterAuditResult],
    new_drift: list[str],
    report_path: Path,
    today: date,
) -> bool:
    """Post a comment to the recurring `drift-sentinel` ClickUp task.

    Uses the canonical pattern from orchestrator/roadmap_drift_sentinel.py:196-214:
    ClickUpClient._get_global_instance().post_comment(DRIFT_TASK_ID, body).
    `today` MUST be the UTC date computed by caller — never call date.today()
    here (local timezone) since the report filename uses UTC and they must agree.

    Fault-tolerant — logs warn on failure, never raises. Returns True on
    successful post, False otherwise (used by tests; not load-bearing in prod).

    Skip post when there are NO new drift candidates since last run AND no
    layout-class anomalies — keeps the comment stream signal-dense.
    """
    if not new_drift and not any(r.layout_class != "canonical" for r in drift_results):
        logger.info("state_drift_audit: no new drift since last run; skipping ClickUp post")
        return False

    # ClickUp comment body — prefixed `[state-drift]` to disambiguate from
    # roadmap-drift posts on the same task ID.
    body_lines = [
        f"**[state-drift] State drift audit — {today.isoformat()}**",
        "",
        f"New drift candidates since last run: {len(new_drift)}",
    ]
    if new_drift:
        body_lines.append("")
        for slug in new_drift:
            r = next((x for x in drift_results if x.slug == slug), None)
            if r:
                body_lines.append(
                    f"- `{r.slug}` — {r.lag_days}d behind newest decision "
                    f"({r.cortex_config_updated} vs {r.newest_decision_date})"
                )
    body_lines.append("")
    body_lines.append(f"Full report: `{report_path.relative_to(_vault_root())}`")
    body = "\n".join(body_lines)

    try:
        from clickup_client import ClickUpClient
    except Exception as e:  # noqa: BLE001 — must not crash scheduler
        logger.warning("state_drift_audit: ClickUpClient import failed: %s", e)
        return False
    try:
        client = ClickUpClient._get_global_instance()
        result = client.post_comment(DRIFT_TASK_ID, body)
    except Exception as e:  # noqa: BLE001
        logger.warning("state_drift_audit: post_comment raised: %s", e)
        return False
    if result is None:
        logger.warning(
            "state_drift_audit: post_comment returned None (HTTP error or write-cap reached)"
        )
        return False
    logger.info("state_drift_audit: ClickUp summary posted (%d new)", len(new_drift))
    return True


def run_state_drift_audit() -> None:
    """Entry point for APScheduler. Idempotent + fault-tolerant."""
    today = datetime.now(timezone.utc).date()
    matters_dir = _matters_dir()
    if not matters_dir.is_dir():
        logger.warning("state_drift_audit: matters dir not found at %s — skipping", matters_dir)
        return

    slugs = _discover_matters(matters_dir)
    logger.info("state_drift_audit: scanning %d matters", len(slugs))

    results = [_audit_matter(matters_dir, s) for s in slugs]

    # Load last-run state, detect NEW drift since last run
    state = _load_last_run_state()
    seen_candidates: dict = state.get("seen_candidates", {})

    # Key candidates by `slug:lag_bucket` — lag_bucket = lag_days // 7 to allow
    # re-alerting if lag widens (e.g., 8d → 35d) but suppress identical re-fires.
    current_keys = set()
    new_drift_slugs: list[str] = []
    for r in results:
        if r.is_drift_candidate:
            lag_bucket = (r.lag_days or 0) // 7
            key = f"{r.slug}:{lag_bucket}"
            current_keys.add(key)
            if key not in seen_candidates:
                new_drift_slugs.append(r.slug)

    # Write detailed report (always — even if no drift, useful as audit trail)
    report_path = _write_report(results, today)

    # Post ClickUp summary only for new drift since last run.
    # Pass UTC `today` explicitly — never let inside function call date.today()
    # (local timezone drift caught in 2nd-pass review).
    _post_clickup_summary(results, new_drift_slugs, report_path, today)

    # Save new state
    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["seen_candidates"] = {k: True for k in current_keys}
    _save_run_state(state)

    logger.info(
        "state_drift_audit: complete — %d drift candidates (%d new), %d non-canonical, report at %s",
        sum(1 for r in results if r.is_drift_candidate),
        len(new_drift_slugs),
        sum(1 for r in results if r.layout_class != "canonical"),
        report_path,
    )
```

### File 2: MODIFY — `triggers/embedded_scheduler.py`

Add a new `add_job` call in `_register_jobs()`, after the existing `clickup_poll` registration (line ~146) and before `dropbox_poll` (line ~150):

```python
    # STATE_FILE_REFRESH_1: nightly drift audit at 03:00 UTC (3h before vault_scanner
    # at 06:00 UTC to spread filesystem load + ClickUp writes across the night).
    # Singleton via scheduler_lease. Job is fault-tolerant — any exception
    # is logged but does not crash scheduler (try/except inside run_state_drift_audit).
    from triggers.state_drift_audit import run_state_drift_audit
    scheduler.add_job(
        run_state_drift_audit,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="state_drift_audit",
        name="State drift audit — cortex-config vs decisions_log",
        coalesce=True,
        max_instances=1,
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Registered: state_drift_audit (daily at 03:00 UTC)")
```

### File 3: NEW — `tests/test_state_drift_audit.py` (~120 LOC)

```python
"""Tests for BRIEF_STATE_FILE_REFRESH_1 — state drift audit.

Golden-file approach: build a temp baker-vault layout with 5 synthetic
matters (2 canonical-clean, 2 canonical-drifted, 1 non-canonical), point
BAKER_VAULT_PATH at it, run audit, assert classifications.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest


# Import the module under test
from triggers import state_drift_audit as sda


@pytest.fixture
def synth_vault(tmp_path: Path, monkeypatch):
    """Build a synthetic baker-vault and point BAKER_VAULT_PATH at it."""
    vault = tmp_path / "vault"
    matters = vault / "wiki" / "matters"
    matters.mkdir(parents=True)

    # Matter 1: canonical-clean — updated yesterday, newest decision yesterday
    _make_matter(
        matters / "clean1",
        cortex_updated="2026-05-16",
        decisions=["## D-001 — first (2026-05-16)"],
    )
    # Matter 2: canonical-clean — within threshold
    _make_matter(
        matters / "clean2",
        cortex_updated="2026-05-10",
        decisions=["## D-001 — first (2026-05-12)"],  # 2d lag, under 7d
    )
    # Matter 3: canonical-drifted — 25 days lag (Aukera-class)
    _make_matter(
        matters / "drift_aukera_class",
        cortex_updated="2026-04-22",
        decisions=["## D-001 — recent (2026-05-17)"],
    )
    # Matter 4: canonical-drifted — 8 days (just over threshold)
    _make_matter(
        matters / "drift_edge",
        cortex_updated="2026-05-09",
        decisions=["## D-001 — recent (2026-05-17)"],
    )
    # Matter 5: non-canonical (no curated/06_decisions_log.md)
    _make_matter(
        matters / "noncanonical",
        cortex_updated="2026-05-01",
        decisions=None,
    )

    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    return vault


def _make_matter(matter_dir: Path, cortex_updated: str, decisions: list[str] | None) -> None:
    matter_dir.mkdir(parents=True)
    cc = matter_dir / "cortex-config.md"
    cc.write_text(
        f"---\ntype: matter\nslug: {matter_dir.name}\nupdated: '{cortex_updated}'\n---\n\n# Cortex Config — {matter_dir.name}\n",
        encoding="utf-8",
    )
    if decisions is not None:
        curated = matter_dir / "curated"
        curated.mkdir()
        dl = curated / "06_decisions_log.md"
        dl.write_text(
            "---\nmatter: " + matter_dir.name + "\n---\n\n# Decisions\n\n" + "\n".join(decisions) + "\n",
            encoding="utf-8",
        )


def test_discover_matters_returns_only_those_with_cortex_config(synth_vault):
    slugs = sda._discover_matters(sda._matters_dir())
    assert sorted(slugs) == ["clean1", "clean2", "drift_aukera_class", "drift_edge", "noncanonical"]


def test_audit_canonical_clean_within_threshold(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "clean2")
    assert r.layout_class == "canonical"
    assert r.is_drift_candidate is False
    assert r.lag_days == 2


def test_audit_canonical_drift_25d_flagged(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "drift_aukera_class")
    assert r.layout_class == "canonical"
    assert r.is_drift_candidate is True
    assert r.lag_days == 25


def test_audit_edge_8d_flagged(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "drift_edge")
    assert r.is_drift_candidate is True


def test_audit_noncanonical_classified_not_flagged(synth_vault):
    r = sda._audit_matter(sda._matters_dir(), "noncanonical")
    assert r.layout_class == "non_canonical_layout"
    assert r.is_drift_candidate is False


def test_full_run_writes_report_and_state(synth_vault, monkeypatch):
    # Patch ClickUp helper to no-op
    posted = {"called": False}
    def _fake_post(*args, **kwargs):
        posted["called"] = True
    monkeypatch.setattr(sda, "_post_clickup_summary", _fake_post)

    sda.run_state_drift_audit()

    today = date.today()
    report = synth_vault / "_ops" / "reports" / f"state-drift-{today.isoformat()}.md"
    assert report.is_file()
    text = report.read_text()
    assert "Drift candidates: **2**" in text  # drift_aukera_class + drift_edge
    assert "drift_aukera_class" in text
    assert "noncanonical" in text  # non-canonical section present

    state_file = synth_vault / "_ops" / "agents" / "_scanner-state" / "state-drift-last-run.json"
    assert state_file.is_file()
    state = json.loads(state_file.read_text())
    assert "seen_candidates" in state
    assert posted["called"] is True


def test_second_run_no_new_drift_skips_clickup(synth_vault, monkeypatch):
    calls = []
    monkeypatch.setattr(
        sda,
        "_post_clickup_summary",
        lambda results, new_drift, report: calls.append(new_drift),
    )
    sda.run_state_drift_audit()  # populates state
    sda.run_state_drift_audit()  # second run — no change in drift bucket
    # Second call gets empty new_drift list
    assert calls[0] != []
    assert calls[1] == []


def test_malformed_frontmatter_does_not_crash(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    matter = vault / "wiki" / "matters" / "broken"
    matter.mkdir(parents=True)
    (matter / "cortex-config.md").write_text("no frontmatter at all\n", encoding="utf-8")
    monkeypatch.setenv("BAKER_VAULT_PATH", str(vault))
    sda.run_state_drift_audit()  # must not raise
```

---

## Key constraints (what NOT to change)

- **Read-only against the vault.** This audit does NOT modify any cortex-config or decisions_log file. The reconciler (separate brief BRIEF_STATE_RECONCILER_1) handles fixes.
- **No DB writes** beyond the existing scheduler_executions row (via `_job_listener` in `embedded_scheduler.py`). No new tables.
- **No new external API.** Reuses ClickUp helper already in fleet. If `tools/clickup_helpers.post_comment_to_task_by_name` does not exist with that exact name, B-code resolves via `grep -rn "def post_comment" tools/` at implementation time and uses the actual signature — do NOT create a new ClickUp client.
- **No changes to `triggers/vault_scanner.py`.** Different concern (soft-tasks + hard-deadlines). Co-existing, not interleaved.
- **Drift threshold = 7 days.** Director-ratifiable later if too noisy/quiet; ship with 7d.
- **Schedule: 03:00 UTC.** 3 hours before vault_scanner (06:00 UTC) — spreads filesystem + ClickUp load across the night.
- **No Slack pushes.** Director directive 2026-04-30 — drift detection → ClickUp recurring task, NOT Slack DM.

---

## Verification

### Local pytest (ship-gate)

```bash
cd /Users/dimitry/bm-b<N>
pytest tests/test_state_drift_audit.py -v
```

**Expected: 8 passed.** Tests:
1. `test_discover_matters_returns_only_those_with_cortex_config`
2. `test_audit_canonical_clean_within_threshold`
3. `test_audit_canonical_drift_25d_flagged`
4. `test_audit_edge_8d_flagged`
5. `test_audit_noncanonical_classified_not_flagged`
6. `test_full_run_writes_report_and_state`
7. `test_second_run_no_new_drift_skips_clickup`
8. `test_malformed_frontmatter_does_not_crash`

(8 tests total. Adjusted from initial draft per code-reviewer 2nd-pass — Lesson #59 anti-drift, expected count + listed count now agree.)

### Pre-merge verification (Lesson #41 — external state)

Brief reads from baker-vault (external to baker-master repo). Before merge:

```bash
# Confirm cortex-config files exist + count
ls /Users/dimitry/baker-vault/wiki/matters/*/cortex-config.md | wc -l
# Expected: 22

# Confirm canonical layout count (matters with curated/06_decisions_log.md)
find /Users/dimitry/baker-vault/wiki/matters -name "06_decisions_log.md" | wc -l
# Expected: 8

# Confirm BAKER_VAULT_PATH set on Render
curl -s "https://api.render.com/v1/services/${RENDER_SERVICE_ID}/env-vars" \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  | jq '.[] | select(.envVar.key == "BAKER_VAULT_PATH")'
# Expected: non-empty result with the vault path
```

### Post-merge smoke test

After Render redeploys with the new job registered:

```bash
# 1. Verify job registered in scheduler logs (Render dashboard → logs)
#    Look for: "Registered: state_drift_audit (daily at 03:00 UTC)"

# 2. Manual fire from local environment (bypasses cron):
cd /Users/dimitry/bm-aihead1
python3 -c "from triggers.state_drift_audit import run_state_drift_audit; run_state_drift_audit()"

# 3. Confirm report appeared
ls -la ~/baker-vault/_ops/reports/state-drift-*.md
cat ~/baker-vault/_ops/reports/state-drift-$(date -u +%Y-%m-%d).md

# 4. Confirm at least one current Aukera-class drift candidate surfaces
#    (mrci or aukera typically — based on which matters have lag > 7d today)
grep "Drift candidates" ~/baker-vault/_ops/reports/state-drift-$(date -u +%Y-%m-%d).md
```

### First production fire verification

After 03:00 UTC fires for the first time:

```bash
# Check scheduler_executions
psql "$DATABASE_URL" -c \
  "SELECT job_id, fired_at, status FROM scheduler_executions \
   WHERE job_id='state_drift_audit' ORDER BY fired_at DESC LIMIT 5;"
# Expected: one row with status='executed'

# Check ClickUp drift-sentinel task got a comment
# (Director eyes this manually first run; subsequent runs only on NEW drift)
```

---

## Files Modified

- **NEW** `triggers/state_drift_audit.py` — drift audit module (~180 LOC)
- **MODIFY** `triggers/embedded_scheduler.py` — register `state_drift_audit` job at 03:00 UTC (add 12 lines after `clickup_poll` block)
- **NEW** `tests/test_state_drift_audit.py` — 8 golden-file tests (~120 LOC)

## Do NOT Touch

- `triggers/vault_scanner.py` — different concern (soft-tasks + deadlines). Audit runs independently.
- `wiki/matters/<slug>/cortex-config.md` — read-only this brief. Reconciler (separate) writes.
- `wiki/matters/<slug>/curated/06_decisions_log.md` — read-only.
- `scheduler_executions` table — only `_job_listener` writes (already in scheduler).
- Existing ClickUp `drift-sentinel` task — already exists per Director directive 2026-04-30; this brief posts comments to it but doesn't create/destroy.

## Quality Checkpoints

1. Pytest passes literal `8/8` — not "by inspection" (Lesson #8).
2. Singleton execution confirmed — scheduler_lease.py already gates dual-instance fires (no new lock needed).
3. Path-traversal protection mirrors `vault_scanner._is_safe_desk_dir` pattern (slug regex + symlink + parent-mismatch checks).
4. Atomic file writes for both report + state file (temp + rename).
5. Fault-tolerant — exceptions logged but do NOT raise from `run_state_drift_audit()` (scheduler must never crash on observability).
6. ClickUp post is fire-and-forget — ImportError or HTTP failure falls back to log-only.
7. State file (`state-drift-last-run.json`) is committed to baker-vault per existing `_scanner-state/` convention.
8. Report file uses Director-readable plain English summary first; tables second.

## Verification SQL

```sql
-- Confirm job fires in production
SELECT job_id, fired_at, status, error_msg
FROM scheduler_executions
WHERE job_id = 'state_drift_audit'
ORDER BY fired_at DESC
LIMIT 10;

-- Should see one execution per day starting first 03:00 UTC after merge.
-- error_msg should be NULL on healthy runs.
```

---

## Risk Register

1. **False positives** (cortex-config `updated:` field stale but content current — manual rewrite without updating frontmatter). Mitigation: report classifies as DRIFT_CANDIDATE, not definitive drift; Director-eye on first run sets thresholds.
2. **ClickUp helper name miss.** Brief references `tools.clickup_helpers.post_comment_to_task_by_name` — if not the actual function name, B-code resolves via grep at implementation time. Fault-tolerant fallback (log-only) keeps job running.
3. **Report file accumulation in `_ops/reports/`.** ~365/yr. Acceptable; Phase-1-reconciler can later add a 90-day retention sweep (separate concern).
4. **State file corruption.** Tolerated via `_load_last_run_state` JSONDecodeError handling — treats as empty state, re-fires alerts on next run.
5. **Drift threshold (7d) too noisy/quiet.** First 3-5 production days will calibrate; can flip via constant in module if Director directs.
6. **Vault filesystem unavailable on Render** (Render dynos have NO baker-vault; this only works on Mac Mini long-running worker). **Critical pre-merge check: is this scheduler job firing on Render or Mac Mini?** Per `scheduler_lease.py` convention, singleton lock holds on whichever replica is alive; if Render has no vault filesystem mount, the job no-ops with a warning ("matters dir not found"). **B-code verifies during pre-merge that this is acceptable + that the Mac Mini long-running worker is the lock-holder for the 03:00 UTC window.**

---

## Sunset / repositioning (when BRIEF_STATE_RECONCILER_1 ships)

Per AID research note + AH1 engineering audit:

- **Pre-reconciler:** this brief runs at full ~180-LOC scope. It is the only mechanical drift detector. `DRIFT_THRESHOLD_DAYS = 7` is calibrated for "agent forgets to manually refresh cortex-config" — appropriate for hand-rewritten era.
- **Post-Phase-1-reconciler (cortex-config covered) + 2 weeks observation:** explicit rescope. Reconciler runs nightly, so `updated:` should always be ≤ 1d behind newest decision. Drop `DRIFT_THRESHOLD_DAYS` from `7` to `2` (one tolerable miss). Audit comparison narrows from "is `updated:` recent enough?" to "would the reconciler produce a different cortex-config than what's committed?" (a `--dry-run` diff). Estimated rescope work: 0.5-1 builder-day. **Anchor:** architect 2nd-pass M5.
- **The diff-job code in `_audit_matter` becomes the rescoped audit logic; the scheduling + ClickUp surface + state tracking are reused as-is.** No code thrown away.

### Layer C liveness audit (architect 2nd-pass H3 — added to Phase 1 scope)

Post-Phase-1, Layer B (this audit) also checks Layer C (reconciler) is alive — closes the Mac-Mini-cron-silent-failure hole.

Add to `run_state_drift_audit()` AFTER existing audit pass:

```python
def _check_reconciler_heartbeat(today: date) -> Optional[str]:
    """Read reconciler heartbeat file written by BRIEF_STATE_RECONCILER_1's nightly cron.
    Return a human-readable warning string if heartbeat is >36h old, None if fresh
    or if reconciler not yet shipped (Phase 1 not deployed yet).

    36h tolerance allows for one missed nightly + buffer; alerts on second miss.
    """
    heartbeat = _vault_root() / "_ops" / "agents" / "_scanner-state" / "reconciler-heartbeat.json"
    if not heartbeat.is_file():
        return None  # Phase 1 not yet shipped — silent (don't false-alarm pre-reconciler)
    try:
        data = json.loads(heartbeat.read_text(encoding="utf-8"))
        last_run = datetime.fromisoformat(data["last_run_utc"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        return f"reconciler-heartbeat unreadable/malformed: {e}"
    age = datetime.now(timezone.utc) - last_run
    if age.total_seconds() > 36 * 3600:
        return (
            f"reconciler-heartbeat stale: last fired "
            f"{last_run.isoformat()} ({age.total_seconds()/3600:.1f}h ago, threshold 36h)"
        )
    return None
```

When `_check_reconciler_heartbeat` returns non-None, include it in the ClickUp post body under a `## Layer C liveness` section AND include it in the markdown report. Treats reconciler-down as a drift-class anomaly — Layer B's job.

---

## Done when

- [ ] Brief PR merged with all 8 tests green (literal pytest output).
- [ ] First 03:00 UTC fire produces `state-drift-2026-05-XX.md` report in baker-vault.
- [ ] ClickUp `drift-sentinel` task gets one summary comment (first fire baseline).
- [ ] Director eyes the first report and confirms drift threshold (7d) is right.
- [ ] PINNED §M updated to reflect Option B bridge live.
