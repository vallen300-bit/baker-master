"""BRIEF_APSCHEDULER_VAULT_SCANNER_V1 — daily vault soft-task + hard-deadline scanner.

Fires at 06:00 UTC daily (APScheduler in ``embedded_scheduler.py``). Reads
soft tasks under ``~/baker-vault/_ops/agents/<desk>/tasks/active/*.md`` and
the Baker ``deadlines`` table; writes per-desk mirror files
(``today-YYYY-MM-DD.md`` + ``today.md`` + ``upcoming-deadlines.md``) and
pushes ONE consolidated Slack DM to Director (per-desk urgent DM only when
critical-priority overdue or blocker-cleared).

Singleton execution: APScheduler is already gated by the cross-process
singleton advisory lock (``triggers/scheduler_lease.py``). This job runs
only on the lock-holder replica; non-lock replicas never register jobs.

Rate cap: max 1 consolidated DM per UTC day + 1 urgent DM per desk per UTC
day. Marker file at ``~/baker-vault/_ops/agents/_scanner-state/last-run-
YYYY-MM-DD.marker`` makes the day-boundary check filesystem-authoritative
(no new DB table).

Path-traversal hardening: desk names must match ``^[a-z0-9-]+$`` and resolve
to a direct subdirectory (no symlink follow) before any file write or path
join. Anything else is rejected + logged.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("sentinel.vault_scanner")

DESK_NAME_RE = re.compile(r"^[a-z0-9-]+$")
DIRECTOR_DM_CHANNEL = "D0AFY28N030"
MAX_DEADLINES_QUERY_LIMIT = 500
MARKER_PRUNE_DAYS = 7
URGENT_DM_RATE_KEY_SUFFIX = ".urgent.marker"


def _vault_root() -> Path:
    raw = os.environ.get("BAKER_VAULT_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(os.path.expanduser("~/baker-vault"))


def _agents_dir() -> Path:
    return _vault_root() / "_ops" / "agents"


def _scanner_state_dir() -> Path:
    return _agents_dir() / "_scanner-state"


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _is_safe_desk_dir(agents_dir: Path, name: str) -> bool:
    """Validate desk-directory name + that it resolves to a direct subdir
    (no symlink follow). Returns False on path traversal / symlink / shape."""
    if not DESK_NAME_RE.match(name):
        logger.warning("vault_scanner: rejecting desk name %r (regex)", name)
        return False
    desk_path = agents_dir / name
    try:
        if desk_path.is_symlink():
            logger.warning("vault_scanner: rejecting desk %r (symlink)", name)
            return False
        if not desk_path.is_dir():
            return False
        resolved_parent = desk_path.resolve().parent
        if resolved_parent != agents_dir.resolve():
            logger.warning(
                "vault_scanner: rejecting desk %r (parent mismatch %s != %s)",
                name, resolved_parent, agents_dir.resolve(),
            )
            return False
    except OSError as e:
        logger.warning("vault_scanner: stat failed for desk %r: %s", name, e)
        return False
    return True


def _discover_desks(agents_dir: Path) -> list[str]:
    """Return desks under agents_dir that have a ``tasks/active/`` subdir."""
    if not agents_dir.is_dir():
        return []
    desks = []
    try:
        entries = sorted(os.listdir(agents_dir))
    except OSError as e:
        logger.warning("vault_scanner: listdir(%s) failed: %s", agents_dir, e)
        return []
    for name in entries:
        if name.startswith("_") or name.startswith("."):
            continue
        if not _is_safe_desk_dir(agents_dir, name):
            continue
        active = agents_dir / name / "tasks" / "active"
        if active.is_dir():
            desks.append(name)
    return desks


def _parse_frontmatter(text: str) -> Optional[dict]:
    """Return parsed YAML frontmatter dict, or None on missing/malformed."""
    if not text.startswith("---"):
        return None
    end_idx = text.find("\n---", 3)
    if end_idx == -1:
        return None
    raw = text[3:end_idx]
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        logger.warning("vault_scanner: bad YAML frontmatter: %s", e)
        return None
    return parsed if isinstance(parsed, dict) else None


def _coerce_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _bucket_task(fm: dict, today: date) -> str:
    """Bucket a task: overdue | due_today | due_soon | blocked | no_due."""
    if fm.get("status") and str(fm["status"]).lower() == "blocked":
        return "blocked"
    if fm.get("blocked_by"):
        return "blocked"
    due = _coerce_date(fm.get("due"))
    if due is None:
        return "no_due"
    if due < today:
        return "overdue"
    if due == today:
        return "due_today"
    if today < due <= today + timedelta(days=7):
        return "due_soon"
    return "no_due"


def _scan_tasks(desk_dir: Path, today: date) -> dict[str, list[dict]]:
    """Walk ``<desk>/tasks/active/*.md``, return bucketed task summaries."""
    buckets: dict[str, list[dict]] = {
        "overdue": [], "due_today": [], "due_soon": [], "blocked": [], "no_due": [],
    }
    active = desk_dir / "tasks" / "active"
    if not active.is_dir():
        return buckets
    try:
        files = sorted(active.glob("*.md"))
    except OSError as e:
        logger.warning("vault_scanner: glob(%s) failed: %s", active, e)
        return buckets
    for fpath in files:
        try:
            text = fpath.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("vault_scanner: read(%s) failed: %s", fpath, e)
            continue
        fm = _parse_frontmatter(text)
        if fm is None:
            logger.warning("vault_scanner: skip %s (missing/bad frontmatter)", fpath.name)
            continue
        bucket = _bucket_task(fm, today)
        buckets[bucket].append({
            "slug": fm.get("slug") or fpath.stem,
            "title": fm.get("title") or fm.get("slug") or fpath.stem,
            "due": _coerce_date(fm.get("due")),
            "priority": str(fm.get("priority") or "normal"),
            "blocked_by": fm.get("blocked_by"),
            "path": f"tasks/active/{fpath.name}",
        })
    return buckets


def _query_deadlines(desk: str) -> list[dict]:
    """Return active deadlines for ``assigned_to = desk`` due within 30d.

    Fault-tolerant: any DB error returns an empty list (and the caller still
    writes the today file without a deadlines section).
    """
    try:
        from models.deadlines import get_conn, put_conn
    except Exception as e:
        logger.warning("vault_scanner: deadlines import failed: %s", e)
        return []
    conn = get_conn()
    if conn is None:
        logger.warning("vault_scanner: get_conn() returned None")
        return []
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, description, due_date, priority, severity, matter_slug,
                       assigned_to, last_reminded_at, reminder_stage, is_critical
                FROM deadlines
                WHERE status = 'active'
                  AND assigned_to = %s
                  AND (due_date IS NULL OR due_date <= NOW() + INTERVAL '30 days')
                ORDER BY due_date NULLS LAST, priority
                LIMIT %s
                """,
                (desk, MAX_DEADLINES_QUERY_LIMIT),
            )
            rows = cur.fetchall()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("vault_scanner: deadlines query failed for %s: %s", desk, e)
            return []
        finally:
            cur.close()
        out: list[dict] = []
        for r in rows:
            due_dt = r[2]
            due_d = due_dt.date() if isinstance(due_dt, datetime) else _coerce_date(due_dt)
            out.append({
                "id": r[0],
                "description": r[1],
                "due_date": due_d,
                "priority": r[3] or "normal",
                "severity": r[4],
                "matter_slug": r[5],
                "assigned_to": r[6],
                "last_reminded_at": r[7],
                "reminder_stage": r[8],
                "is_critical": bool(r[9]) if r[9] is not None else False,
            })
        return out
    finally:
        try:
            put_conn(conn)
        except Exception:
            pass


def _bucket_deadlines(rows: list[dict], today: date) -> dict[str, list[dict]]:
    buckets: dict[str, list[dict]] = {
        "overdue": [], "due_today": [], "due_this_week": [], "due_this_month": [],
    }
    week_end = today + timedelta(days=7)
    month_end = today + timedelta(days=30)
    for d in rows:
        due = d.get("due_date")
        if due is None:
            continue
        if due < today:
            buckets["overdue"].append(d)
        elif due == today:
            buckets["due_today"].append(d)
        elif due <= week_end:
            buckets["due_this_week"].append(d)
        elif due <= month_end:
            buckets["due_this_month"].append(d)
    return buckets


def _has_any_items(task_buckets: dict, deadline_buckets: dict) -> bool:
    for v in task_buckets.values():
        if v:
            return True
    for v in deadline_buckets.values():
        if v:
            return True
    return False


def _section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    body = "\n".join(items)
    return f"## {title} ({len(items)})\n{body}\n"


def _format_task_line(t: dict) -> str:
    due = t.get("due")
    due_s = due.isoformat() if isinstance(due, date) else "—"
    return f"- [{t['slug']}]({t['path']}) — {t['title']} — due {due_s} — {t['priority']}"


def _format_blocked_line(t: dict) -> str:
    return f"- {t['title']} — blocked_by: {t.get('blocked_by') or '—'}"


def _format_deadline_line(d: dict) -> str:
    due = d.get("due_date")
    due_s = due.isoformat() if isinstance(due, date) else "—"
    crit = " 🔴" if d.get("is_critical") else ""
    return f"- {d['id']}: {d['description']} — due {due_s} — {d['priority']}{crit}"


def _render_today_md(
    *, desk: str, today: date, generated_at: datetime,
    task_buckets: dict, deadline_buckets: dict,
) -> str:
    header = (
        "---\n"
        f"generated_at: {generated_at.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}\n"
        f"generated_by: vault_scanner_daily\n"
        f"desk: {desk}\n"
        "warning: GENERATED FILE — do not edit by hand; changes are overwritten on next scan\n"
        "---\n\n"
        f"# Today — {desk} — {today.isoformat()}\n\n"
    )
    parts = [
        _section("Overdue tasks", [_format_task_line(t) for t in task_buckets["overdue"]]),
        _section("Due today", [_format_task_line(t) for t in task_buckets["due_today"]]),
        _section("Due this week", [_format_task_line(t) for t in task_buckets["due_soon"]]),
        _section("Blocked", [_format_blocked_line(t) for t in task_buckets["blocked"]]),
        _section(
            "Hard deadlines — overdue",
            [_format_deadline_line(d) for d in deadline_buckets["overdue"]],
        ),
        _section(
            "Hard deadlines — due today",
            [_format_deadline_line(d) for d in deadline_buckets["due_today"]],
        ),
        _section(
            "Hard deadlines — due this week",
            [_format_deadline_line(d) for d in deadline_buckets["due_this_week"]],
        ),
    ]
    return header + "\n".join(p for p in parts if p)


def _render_upcoming_md(
    *, desk: str, generated_at: datetime, deadline_rows: list[dict],
) -> str:
    header = (
        "---\n"
        f"generated_at: {generated_at.replace(microsecond=0).isoformat().replace('+00:00', 'Z')}\n"
        "generated_by: vault_scanner_daily\n"
        f"desk: {desk}\n"
        "warning: GENERATED FILE — do not edit by hand; changes are overwritten on next scan\n"
        "---\n\n"
        f"# Upcoming hard deadlines — {desk} (next 30 days)\n\n"
    )
    if not deadline_rows:
        return header + "_no active deadlines in window_\n"
    lines = [_format_deadline_line(d) for d in deadline_rows]
    return header + "\n".join(lines) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def _desk_emoji(task_buckets: dict, deadline_buckets: dict) -> str:
    if (
        deadline_buckets["overdue"] and any(d.get("is_critical") for d in deadline_buckets["overdue"])
    ) or len(deadline_buckets["overdue"]) > 7:
        return "🔴"
    if deadline_buckets["overdue"] or task_buckets["overdue"] or task_buckets["blocked"]:
        return "🟠"
    if any(v for v in task_buckets.values()) or any(v for v in deadline_buckets.values()):
        return "🟡"
    return "🟢"


def _consolidated_dm_body(
    *, today: date, per_desk: dict[str, dict],
) -> str:
    lines = [f"Daily digest — {today.isoformat()} 06:00 UTC", ""]
    for desk in sorted(per_desk.keys()):
        d = per_desk[desk]
        tb = d["task_buckets"]
        db = d["deadline_buckets"]
        emoji = _desk_emoji(tb, db)
        any_items = _has_any_items(tb, db)
        if not any_items:
            lines.append(f"{emoji} {desk}")
            lines.append("  (nothing today)")
            lines.append("")
            continue
        lines.append(f"{emoji} {desk}")
        lines.append(f"  Overdue: {len(tb['overdue'])}")
        lines.append(f"  Due today: {len(tb['due_today'])}")
        lines.append(f"  Due this week: {len(tb['due_soon'])}")
        lines.append(f"  Hard deadlines overdue: {len(db['overdue'])}")
        lines.append(f"  Hard deadlines this week: {len(db['due_this_week'])}")
        lines.append("")
    lines.append(
        f"Full per-desk view: ~/baker-vault/_ops/agents/<desk>/today-{today.isoformat()}.md"
    )
    return "\n".join(lines)


def _urgent_payload(
    *, desk: str, task_buckets: dict, deadline_buckets: dict,
) -> Optional[str]:
    """Return urgent DM body if desk has critical-priority overdue task OR
    is_critical overdue deadline; else None."""
    crit_tasks = [t for t in task_buckets["overdue"] if t.get("priority") == "critical"]
    crit_deadlines = [d for d in deadline_buckets["overdue"] if d.get("is_critical")]
    if not crit_tasks and not crit_deadlines:
        return None
    lines = [f"🔴 URGENT — {desk}", ""]
    if crit_tasks:
        lines.append(f"Critical overdue tasks ({len(crit_tasks)}):")
        for t in crit_tasks:
            lines.append(_format_task_line(t))
        lines.append("")
    if crit_deadlines:
        lines.append(f"Critical hard deadlines overdue ({len(crit_deadlines)}):")
        for d in crit_deadlines:
            lines.append(_format_deadline_line(d))
    return "\n".join(lines)


def _consolidated_marker_path(today: date) -> Path:
    return _scanner_state_dir() / f"last-run-{today.isoformat()}.marker"


def _urgent_marker_path(today: date, desk: str) -> Path:
    return _scanner_state_dir() / f"last-run-{today.isoformat()}-{desk}{URGENT_DM_RATE_KEY_SUFFIX}"


def _prune_old_markers(today: date) -> None:
    state = _scanner_state_dir()
    if not state.is_dir():
        return
    cutoff = today - timedelta(days=MARKER_PRUNE_DAYS)
    try:
        for child in state.iterdir():
            try:
                if not child.is_file():
                    continue
                name = child.name
                # Match last-run-YYYY-MM-DD prefix; if older than cutoff, prune.
                m = re.match(r"last-run-(\d{4}-\d{2}-\d{2})", name)
                if not m:
                    continue
                file_date = date.fromisoformat(m.group(1))
                if file_date < cutoff:
                    child.unlink(missing_ok=True)
            except (OSError, ValueError) as e:
                logger.warning("vault_scanner: prune skip %s: %s", child, e)
    except OSError as e:
        logger.warning("vault_scanner: prune iterdir failed: %s", e)


def _send_consolidated_dm(body: str) -> bool:
    try:
        from outputs.slack_notifier import post_to_channel
    except Exception as e:
        logger.warning("vault_scanner: slack import failed: %s", e)
        return False
    try:
        return bool(post_to_channel(DIRECTOR_DM_CHANNEL, body))
    except Exception as e:
        logger.warning("vault_scanner: post_to_channel raised: %s", e)
        return False


def run_scan() -> dict:
    """Execute one scan run. Returns a small summary dict for logging/tests.

    Idempotent within a UTC day via marker file: a second call on the same
    UTC date skips the consolidated DM (mirror files are still refreshed —
    they're cheap and disk-only).
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    vault = _vault_root()
    agents_dir = _agents_dir()
    state_dir = _scanner_state_dir()

    summary: dict = {
        "today": today.isoformat(),
        "desks_scanned": [],
        "files_written": [],
        "consolidated_dm_sent": False,
        "urgent_dms_sent": [],
        "skipped_reason": None,
    }

    if not agents_dir.is_dir():
        logger.warning("vault_scanner: agents_dir missing (%s) — abort", agents_dir)
        summary["skipped_reason"] = "agents_dir_missing"
        return summary

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("vault_scanner: state_dir mkdir failed: %s", e)

    _prune_old_markers(today)

    desks = _discover_desks(agents_dir)
    if not desks:
        logger.info("vault_scanner: no desks with tasks/active/ — early return")
        summary["skipped_reason"] = "no_desks"
        # Still drop a marker so a same-day retry skips DM rate-cap-wise (no DM
        # to send anyway, so cap is naturally respected). Don't write marker
        # here because no DM was sent — keeps marker semantically "consolidated
        # DM already happened today".
        return summary

    per_desk: dict[str, dict] = {}
    for desk in desks:
        desk_dir = agents_dir / desk
        task_buckets = _scan_tasks(desk_dir, today)
        deadline_rows = _query_deadlines(desk)
        deadline_buckets = _bucket_deadlines(deadline_rows, today)
        per_desk[desk] = {
            "task_buckets": task_buckets,
            "deadline_buckets": deadline_buckets,
            "deadline_rows": deadline_rows,
        }
        summary["desks_scanned"].append(desk)

        if _has_any_items(task_buckets, deadline_buckets):
            today_md = _render_today_md(
                desk=desk, today=today, generated_at=now,
                task_buckets=task_buckets, deadline_buckets=deadline_buckets,
            )
            today_path = desk_dir / f"today-{today.isoformat()}.md"
            stable_path = desk_dir / "today.md"
            try:
                _write_atomic(today_path, today_md)
                _write_atomic(stable_path, today_md)
                summary["files_written"].extend([str(today_path), str(stable_path)])
            except OSError as e:
                logger.warning("vault_scanner: write today file failed for %s: %s", desk, e)

        upcoming_path = desk_dir / "upcoming-deadlines.md"
        upcoming_md = _render_upcoming_md(
            desk=desk, generated_at=now, deadline_rows=deadline_rows,
        )
        try:
            _write_atomic(upcoming_path, upcoming_md)
            summary["files_written"].append(str(upcoming_path))
        except OSError as e:
            logger.warning("vault_scanner: write upcoming file failed for %s: %s", desk, e)

    # Consolidated DM — rate-capped by marker
    marker = _consolidated_marker_path(today)
    if marker.exists():
        logger.info("vault_scanner: consolidated DM already sent today (%s)", today)
    else:
        body = _consolidated_dm_body(today=today, per_desk=per_desk)
        ok = _send_consolidated_dm(body)
        if ok:
            try:
                marker.touch()
                summary["consolidated_dm_sent"] = True
            except OSError as e:
                logger.warning("vault_scanner: marker touch failed: %s", e)
                summary["consolidated_dm_sent"] = True  # DM did go out
        else:
            logger.warning("vault_scanner: consolidated DM send returned False")

    # Per-desk urgent DM (separate rate cap per desk per day)
    for desk, d in per_desk.items():
        urgent_body = _urgent_payload(
            desk=desk,
            task_buckets=d["task_buckets"],
            deadline_buckets=d["deadline_buckets"],
        )
        if urgent_body is None:
            continue
        urgent_marker = _urgent_marker_path(today, desk)
        if urgent_marker.exists():
            logger.info("vault_scanner: urgent DM already sent for %s today", desk)
            continue
        ok = _send_consolidated_dm(urgent_body)
        if ok:
            try:
                urgent_marker.touch()
            except OSError as e:
                logger.warning("vault_scanner: urgent marker touch failed (%s): %s", desk, e)
            summary["urgent_dms_sent"].append(desk)

    logger.info(
        "vault_scanner: scanned %d desks; wrote %d files; consolidated_dm=%s; urgent=%s",
        len(summary["desks_scanned"]),
        len(summary["files_written"]),
        summary["consolidated_dm_sent"],
        summary["urgent_dms_sent"],
    )
    return summary


def startup_catchup() -> bool:
    """If 06:00 UTC has passed today and the consolidated marker is absent,
    run one scan now. Returns True iff a catch-up scan ran."""
    now = datetime.now(timezone.utc)
    today = now.date()
    if now.time() < datetime.min.time().replace(hour=6):
        return False
    marker = _consolidated_marker_path(today)
    if marker.exists():
        return False
    logger.info("vault_scanner: catch-up run on startup (no marker for %s)", today)
    try:
        run_scan()
    except Exception:
        logger.exception("vault_scanner: catch-up run failed")
        return False
    return True
