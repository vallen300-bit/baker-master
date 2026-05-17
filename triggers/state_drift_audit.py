"""BRIEF_STATE_FILE_REFRESH_1 — nightly drift audit.

Fires at 03:00 UTC daily. Scans `wiki/matters/<slug>/cortex-config.md` files
in baker-vault, classifies by curated/ layout, and for canonical-layout
matters compares cortex-config `updated:` field against the newest dated
decision in `curated/06_decisions_log.md`. Surfaces drift candidates via:
  (a) detailed markdown report -> `_ops/reports/state-drift-YYYY-MM-DD.md`
  (b) one summary comment on ClickUp `drift-sentinel` recurring task

READ-ONLY against the vault. The reconciler that actually fixes drift is
a separate brief (BRIEF_STATE_RECONCILER_1).

Singleton: APScheduler is already gated by scheduler_lease.py. No additional
locking.

State file: `_ops/agents/_scanner-state/state-drift-last-run.json` -- tracks
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

# SAME recurring `drift-sentinel` task ID used by orchestrator/roadmap_drift_sentinel.py:40.
# Comments prefixed `[state-drift]` to disambiguate from roadmap-drift posts.
# If Director later wants split surfaces, flip this constant (single-line change).
DRIFT_TASK_ID = "86c9k6kau"

# 36h tolerance allows for one missed nightly + buffer; alerts on second miss.
RECONCILER_HEARTBEAT_THRESHOLD_SECONDS = 36 * 3600


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


def _reconciler_heartbeat_path() -> Path:
    return _vault_root() / "_ops" / "agents" / "_scanner-state" / "reconciler-heartbeat.json"


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
    "missing dated decisions" -- not drift, separate class).
    """
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

    if not decisions_log_path.is_file():
        result.layout_class = "non_canonical_layout"
        result.notes.append(
            "no curated/06_decisions_log.md -- needs canonicalization (separate brief)"
        )
        return result

    newest = _newest_decision_date(decisions_log_path)
    if newest is None:
        result.layout_class = "missing_decisions_log"
        result.notes.append(
            "06_decisions_log.md exists but no `## D-NNN ... (YYYY-MM-DD)` headings parsed"
        )
        return result
    result.newest_decision_date = newest

    if result.cortex_config_updated is None:
        result.notes.append("cannot compute lag -- cortex_config `updated:` missing")
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
        tmp = path.with_suffix(path.suffix + ".tmp." + os.urandom(4).hex())
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as e:
        logger.warning("state_drift_audit: state file write failed: %s", e)


def _check_reconciler_heartbeat(today: date) -> Optional[str]:
    """Read reconciler heartbeat file written by BRIEF_STATE_RECONCILER_1's
    nightly cron. Return a human-readable warning string if heartbeat is >36h
    old, None if fresh or if reconciler not yet shipped (Phase 1 not deployed).

    36h tolerance = one missed nightly + buffer; alerts on second miss.
    Returns None silently pre-Phase-1 ship to avoid false alarms.
    """
    heartbeat = _reconciler_heartbeat_path()
    if not heartbeat.is_file():
        return None
    try:
        data = json.loads(heartbeat.read_text(encoding="utf-8"))
        last_run = datetime.fromisoformat(data["last_run_utc"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        return f"reconciler-heartbeat unreadable/malformed: {e}"
    age = datetime.now(timezone.utc) - last_run
    if age.total_seconds() > RECONCILER_HEARTBEAT_THRESHOLD_SECONDS:
        return (
            f"reconciler-heartbeat stale: last fired "
            f"{last_run.isoformat()} ({age.total_seconds()/3600:.1f}h ago, threshold 36h)"
        )
    return None


def _write_report(
    results: list[MatterAuditResult],
    today: date,
    reconciler_warning: Optional[str] = None,
) -> Path:
    reports_dir = _reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"state-drift-{today.isoformat()}.md"

    lines: list[str] = [
        f"# State drift audit -- {today.isoformat()}",
        "",
        f"**Run:** {datetime.now(timezone.utc).isoformat()}",
        f"**Matters scanned:** {len(results)}",
        "",
    ]

    drift = [r for r in results if r.is_drift_candidate]
    non_canonical = [r for r in results if r.layout_class == "non_canonical_layout"]
    missing_log = [r for r in results if r.layout_class == "missing_decisions_log"]
    clean = [
        r for r in results
        if r.layout_class == "canonical" and not r.is_drift_candidate and not r.notes
    ]

    lines.append("## Summary")
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
            lines.append(f"- `{r.slug}` -- {'; '.join(r.notes)}")
        lines.append("")

    if missing_log:
        lines.append("## Canonical layout but no parseable decisions")
        lines.append("")
        for r in missing_log:
            lines.append(f"- `{r.slug}` -- {'; '.join(r.notes)}")
        lines.append("")

    if reconciler_warning:
        lines.append("## Layer C liveness")
        lines.append("")
        lines.append(reconciler_warning)
        lines.append("")

    tmp = report_path.with_suffix(report_path.suffix + ".tmp." + os.urandom(4).hex())
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.replace(tmp, report_path)
    return report_path


def _post_clickup_summary(
    drift_results: list[MatterAuditResult],
    new_drift: list[str],
    report_path: Path,
    today: date,
    reconciler_warning: Optional[str] = None,
) -> bool:
    """Post a comment to the recurring `drift-sentinel` ClickUp task.

    Uses the canonical pattern from orchestrator/roadmap_drift_sentinel.py:196-214:
    ClickUpClient._get_global_instance().post_comment(DRIFT_TASK_ID, body).
    `today` MUST be the UTC date computed by caller -- never call date.today()
    here (local timezone) since the report filename uses UTC and they must agree.

    Fault-tolerant -- logs warn on failure, never raises. Returns True on
    successful post, False otherwise (used by tests; not load-bearing in prod).

    Skip post when there are NO new drift candidates since last run AND no
    layout-class anomalies AND no reconciler-liveness warning -- keeps the
    comment stream signal-dense.
    """
    has_layout_anomaly = any(r.layout_class != "canonical" for r in drift_results)
    if not new_drift and not has_layout_anomaly and not reconciler_warning:
        logger.info("state_drift_audit: no new drift since last run; skipping ClickUp post")
        return False

    body_lines = [
        f"**[state-drift] State drift audit -- {today.isoformat()}**",
        "",
        f"New drift candidates since last run: {len(new_drift)}",
    ]
    if new_drift:
        body_lines.append("")
        for slug in new_drift:
            r = next((x for x in drift_results if x.slug == slug), None)
            if r:
                body_lines.append(
                    f"- `{r.slug}` -- {r.lag_days}d behind newest decision "
                    f"({r.cortex_config_updated} vs {r.newest_decision_date})"
                )
    if reconciler_warning:
        body_lines.append("")
        body_lines.append("## Layer C liveness")
        body_lines.append(reconciler_warning)
    body_lines.append("")
    try:
        rel = report_path.relative_to(_vault_root())
    except ValueError:
        rel = report_path
    body_lines.append(f"Full report: `{rel}`")
    body = "\n".join(body_lines)

    try:
        from clickup_client import ClickUpClient
    except Exception as e:  # noqa: BLE001 -- must not crash scheduler
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
        logger.warning("state_drift_audit: matters dir not found at %s -- skipping", matters_dir)
        return

    slugs = _discover_matters(matters_dir)
    logger.info("state_drift_audit: scanning %d matters", len(slugs))

    results = [_audit_matter(matters_dir, s) for s in slugs]

    state = _load_last_run_state()
    seen_candidates: dict = state.get("seen_candidates", {})

    # Key candidates by `slug:lag_bucket` -- lag_bucket = lag_days // 7 to allow
    # re-alerting if lag widens (e.g., 8d -> 35d) but suppress identical re-fires.
    current_keys = set()
    new_drift_slugs: list[str] = []
    for r in results:
        if r.is_drift_candidate:
            lag_bucket = (r.lag_days or 0) // 7
            key = f"{r.slug}:{lag_bucket}"
            current_keys.add(key)
            if key not in seen_candidates:
                new_drift_slugs.append(r.slug)

    reconciler_warning = _check_reconciler_heartbeat(today)

    report_path = _write_report(results, today, reconciler_warning)

    # Pass UTC `today` explicitly -- never let inside function call date.today()
    # (local timezone drift caught in 2nd-pass review).
    _post_clickup_summary(
        results, new_drift_slugs, report_path, today, reconciler_warning
    )

    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["seen_candidates"] = {k: True for k in current_keys}
    _save_run_state(state)

    logger.info(
        "state_drift_audit: complete -- %d drift candidates (%d new), %d non-canonical, report at %s",
        sum(1 for r in results if r.is_drift_candidate),
        len(new_drift_slugs),
        sum(1 for r in results if r.layout_class != "canonical"),
        report_path,
    )
