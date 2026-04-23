"""AI Head weekly self-audit logic.

BRIEF_AI_HEAD_WEEKLY_AUDIT_1: invoked by ``_ai_head_weekly_audit_job`` in
``triggers/embedded_scheduler.py`` on the Monday 09:00 UTC cron.

Scope: pure logic + PG write + Slack push. Scheduler registration is in
embedded_scheduler.py; this module is the body.

Read-only against the vault mirror. No vault write-back in v1 — see brief
§Deferred. Non-fatal on every failure path (weekly hedge; absence of audit
is less harmful than a scheduler crash).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("sentinel.ai_head_audit")

_AI_HEAD_PREFIX = "_ops/agents/ai-head/"
_STALE_MIRROR_THRESHOLD_SECONDS = 600  # 10 minutes
_ARCHIVE_LESSONS_WINDOW_DAYS = 7
_OPERATING_STALE_THRESHOLD_DAYS = 7
_LONGTERM_STALE_THRESHOLD_DAYS = 30

_DIRECTOR_DM_CHANNEL = "D0AFY28N030"

_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_LESSON_LINE_RE = re.compile(
    r"^\s*[-*]\s+(.+?)\s*$", re.MULTILINE
)


def run_weekly_audit() -> dict:
    """Execute one audit cycle. Returns a dict of the audit record for logging.

    Non-fatal: any step can fail independently and the others still run.
    Writes one row to ``ai_head_audits``; posts two Slack messages
    (#cockpit + Director DM); returns the record.
    """
    started_at = datetime.now(timezone.utc)
    logger.info("ai_head_audit: starting")

    mirror_info = _safe_mirror_status()

    operating_content = _safe_read(f"{_AI_HEAD_PREFIX}OPERATING.md")
    longterm_content = _safe_read(f"{_AI_HEAD_PREFIX}LONGTERM.md")
    archive_content = _safe_read(f"{_AI_HEAD_PREFIX}ARCHIVE.md")

    drift_items = _classify_drift(
        operating_content=operating_content,
        longterm_content=longterm_content,
        archive_content=archive_content,
        reference_now=started_at,
    )

    lesson_patterns = _count_recent_lesson_patterns(
        archive_content=archive_content,
        reference_now=started_at,
    )

    summary = _compose_summary(
        drift_items=drift_items,
        lesson_patterns=lesson_patterns,
        mirror_info=mirror_info,
    )

    slack_cockpit_ok = False
    slack_dm_ok = False
    record_id = _write_audit_record(
        ran_at=started_at,
        drift_items=drift_items,
        lesson_patterns=lesson_patterns,
        summary_text=summary,
        slack_cockpit_ok=slack_cockpit_ok,
        slack_dm_ok=slack_dm_ok,
        mirror_info=mirror_info,
    )

    slack_cockpit_ok = _safe_post_cockpit(summary)
    slack_dm_ok = _safe_post_dm(summary)

    _update_slack_outcomes(record_id, slack_cockpit_ok, slack_dm_ok)

    result = {
        "record_id": record_id,
        "ran_at": started_at.isoformat(),
        "drift_count": len(drift_items),
        "lesson_pattern_count": len(lesson_patterns),
        "slack_cockpit_ok": slack_cockpit_ok,
        "slack_dm_ok": slack_dm_ok,
        "mirror_stale": mirror_info.get("stale", False),
    }
    logger.info("ai_head_audit: complete %s", result)
    return result


def _safe_mirror_status() -> dict:
    """Return {last_pull_at, head_sha, stale: bool, stale_seconds: int}.

    vault_mirror.mirror_status() returns
    ``{vault_mirror_last_pull: ISO-string | None, vault_mirror_commit_sha: str | None}``
    (verified 2026-04-22 at vault_mirror.py:247).
    """
    try:
        from vault_mirror import mirror_status
        status = mirror_status()
        last_pull_iso = status.get("vault_mirror_last_pull")
        head_sha = status.get("vault_mirror_commit_sha")
        last_pull_dt: Optional[datetime] = None
        if isinstance(last_pull_iso, str):
            try:
                last_pull_dt = datetime.fromisoformat(last_pull_iso)
                if last_pull_dt.tzinfo is None:
                    last_pull_dt = last_pull_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                last_pull_dt = None
        stale_seconds = 0
        stale = False
        if last_pull_dt is not None:
            stale_seconds = int((datetime.now(timezone.utc) - last_pull_dt).total_seconds())
            stale = stale_seconds > _STALE_MIRROR_THRESHOLD_SECONDS
        if stale:
            logger.warning(
                "ai_head_audit: vault mirror stale (%ss since last pull); proceeding best-effort",
                stale_seconds,
            )
        return {
            "last_pull_at": last_pull_dt,
            "head_sha": head_sha,
            "stale": stale,
            "stale_seconds": stale_seconds,
        }
    except Exception as e:
        logger.warning("ai_head_audit: mirror_status failed: %s", e)
        return {"last_pull_at": None, "head_sha": None, "stale": True, "stale_seconds": -1}


def _safe_read(rel_path: str) -> str:
    """Return file content or empty string on any failure."""
    try:
        from vault_mirror import read_ops_file
        result = read_ops_file(rel_path)
        if result.get("error"):
            logger.warning(
                "ai_head_audit: read_ops_file('%s') returned error=%s",
                rel_path, result.get("error"),
            )
            return ""
        return result.get("content_utf8", "") or ""
    except Exception as e:
        logger.warning("ai_head_audit: read_ops_file('%s') raised: %s", rel_path, e)
        return ""


def _classify_drift(
    operating_content: str,
    longterm_content: str,
    archive_content: str,
    reference_now: datetime,
) -> list[dict]:
    """Return list of {category, file, detail} drift items.

    Heuristics (v1 — coarse; weekly audit tolerates false positives):
      - OPERATING entries whose last embedded date is >7 days old
      - LONGTERM frontmatter ``updated:`` field >30 days old
      - Tier A items in OPERATING that aren't referenced in any ARCHIVE
        block from the past 4 weeks (possibly retired)
    """
    items: list[dict] = []

    op_date = _latest_date_in(operating_content)
    if op_date and (reference_now.date() - op_date).days > _OPERATING_STALE_THRESHOLD_DAYS:
        items.append({
            "category": "operating_stale",
            "file": "OPERATING.md",
            "detail": f"Latest date reference {op_date.isoformat()} is "
                      f"{(reference_now.date() - op_date).days} days old; "
                      f"rewrite candidate.",
        })

    lt_updated = _frontmatter_date(longterm_content, "updated")
    if lt_updated and (reference_now.date() - lt_updated).days > _LONGTERM_STALE_THRESHOLD_DAYS:
        items.append({
            "category": "longterm_stale",
            "file": "LONGTERM.md",
            "detail": f"Frontmatter updated={lt_updated.isoformat()} is "
                      f"{(reference_now.date() - lt_updated).days} days old; "
                      f"review for fact changes.",
        })

    tier_a_items = _extract_tier_a_items(operating_content)
    recent_archive = _archive_window(archive_content, reference_now, weeks=4)
    for item in tier_a_items:
        if item not in recent_archive:
            items.append({
                "category": "tier_a_unreferenced",
                "file": "OPERATING.md",
                "detail": f"Tier A '{item[:80]}' not referenced in any ARCHIVE "
                          f"block from past 4 weeks; candidate for retirement.",
            })

    return items


def _count_recent_lesson_patterns(
    archive_content: str,
    reference_now: datetime,
) -> list[dict]:
    """Return list of {pattern, count} across past week's Lessons blocks."""
    window_text = _archive_window_text(
        archive_content, reference_now, days=_ARCHIVE_LESSONS_WINDOW_DAYS
    )

    lessons: list[str] = []
    for match in re.finditer(
        r"\*\*Lessons\s*/?\s*will change:\*\*\s*\n((?:\s*[-*]\s+.+\n?)+)",
        window_text, flags=re.IGNORECASE,
    ):
        block = match.group(1)
        for bullet_match in _LESSON_LINE_RE.finditer(block):
            lessons.append(bullet_match.group(1).strip().lower())

    counts: dict[str, int] = {}
    for lesson in lessons:
        key = re.sub(r"\s+", " ", lesson).strip()
        if len(key) < 10:
            continue
        counts[key] = counts.get(key, 0) + 1

    return [
        {"pattern": pat, "count": cnt}
        for pat, cnt in sorted(counts.items(), key=lambda x: -x[1])
        if cnt >= 1
    ][:10]


def _compose_summary(
    drift_items: list[dict],
    lesson_patterns: list[dict],
    mirror_info: dict,
) -> str:
    """Plain English, ≤3 sentences, no markdown. Director DM format."""
    drift_n = len(drift_items)
    pattern_n = len(lesson_patterns)
    stale_note = ""
    if mirror_info.get("stale"):
        stale_note = " (note: vault mirror was stale at audit time; re-check next cycle)"

    line1 = (
        f"AI Head weekly audit: {drift_n} drift item"
        + ("s" if drift_n != 1 else "")
        + f", {pattern_n} recurring lesson pattern"
        + ("s" if pattern_n != 1 else "")
        + f" in past 7 days{stale_note}."
    )
    line2 = (
        "See ai_head_audits table in Baker PG (latest row) for details."
        if drift_n or pattern_n else
        "No action needed — memory triplet within thresholds."
    )
    line3 = "Paper trail: vault commit 373551e (AI Head consolidation)."
    return f"{line1}\n{line2}\n{line3}"


# --------- Date parsing helpers -----------------------------------------

def _latest_date_in(content: str) -> Optional[Any]:
    if not content:
        return None
    dates = []
    for m in _DATE_RE.finditer(content):
        try:
            dates.append(datetime.strptime(m.group(1), "%Y-%m-%d").date())
        except ValueError:
            continue
    return max(dates) if dates else None


def _frontmatter_date(content: str, key: str) -> Optional[Any]:
    if not content:
        return None
    m = re.search(
        r"^---\s*\n(.*?)\n---",
        content, flags=re.DOTALL | re.MULTILINE,
    )
    if not m:
        return None
    frontmatter = m.group(1)
    m2 = re.search(
        rf"^\s*{re.escape(key)}\s*:\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*$",
        frontmatter, flags=re.MULTILINE,
    )
    if not m2:
        return None
    try:
        return datetime.strptime(m2.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_tier_a_items(operating_content: str) -> list[str]:
    """Return bullet contents under '## Standing Tier A' header, if present."""
    if not operating_content:
        return []
    m = re.search(
        r"^##\s+Standing Tier A.*?\n(.*?)(?=\n^##\s+|\Z)",
        operating_content, flags=re.DOTALL | re.MULTILINE,
    )
    if not m:
        return []
    block = m.group(1)
    return [bm.group(1).strip() for bm in _LESSON_LINE_RE.finditer(block)]


def _archive_window(archive_content: str, reference_now: datetime, weeks: int) -> str:
    """Return concatenated text of ARCHIVE session blocks within window."""
    return _archive_window_text(archive_content, reference_now, days=weeks * 7)


def _archive_window_text(archive_content: str, reference_now: datetime, days: int) -> str:
    if not archive_content:
        return ""
    window_start = (reference_now - timedelta(days=days)).date()
    blocks = re.split(r"^(## Session .*?$)", archive_content, flags=re.MULTILINE)
    accumulated = []
    i = 1
    while i < len(blocks) - 1:
        header = blocks[i]
        body = blocks[i + 1] if i + 1 < len(blocks) else ""
        date_match = _DATE_RE.search(header)
        if date_match:
            try:
                d = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
                if d >= window_start:
                    accumulated.append(header + body)
            except ValueError:
                pass
        i += 2
    return "\n".join(accumulated)


# --------- PG writers ---------------------------------------------------

def _write_audit_record(
    *,
    ran_at: datetime,
    drift_items: list[dict],
    lesson_patterns: list[dict],
    summary_text: str,
    slack_cockpit_ok: bool,
    slack_dm_ok: bool,
    mirror_info: dict,
) -> Optional[int]:
    """Insert one row; return id, or None on failure."""
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return None
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO ai_head_audits
                    (ran_at, drift_items, lesson_patterns, summary_text,
                     slack_cockpit_ok, slack_dm_ok,
                     mirror_last_pull_at, mirror_head_sha)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    ran_at,
                    json.dumps(drift_items),
                    json.dumps(lesson_patterns),
                    summary_text,
                    slack_cockpit_ok,
                    slack_dm_ok,
                    mirror_info.get("last_pull_at"),
                    mirror_info.get("head_sha"),
                ),
            )
            row = cur.fetchone()
            conn.commit()
            cur.close()
            return row[0] if row else None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("ai_head_audit: write failed: %s", e)
            return None
        finally:
            store._put_conn(conn)
    except Exception as e:
        logger.warning("ai_head_audit: get_store_back failed: %s", e)
        return None


def _update_slack_outcomes(
    record_id: Optional[int], cockpit_ok: bool, dm_ok: bool,
) -> None:
    if record_id is None:
        return
    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        conn = store._get_conn()
        if not conn:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE ai_head_audits SET slack_cockpit_ok=%s, slack_dm_ok=%s WHERE id=%s",
                (cockpit_ok, dm_ok, record_id),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("ai_head_audit: UPDATE outcomes failed: %s", e)
        finally:
            store._put_conn(conn)
    except Exception:
        pass  # best-effort only


# --------- Slack pushers ------------------------------------------------

def _safe_post_cockpit(summary: str) -> bool:
    try:
        from outputs.slack_notifier import post_to_channel
        from config.settings import config
        cockpit = getattr(config.slack, "cockpit_channel_id", None)
        if not cockpit:
            logger.warning("ai_head_audit: cockpit_channel_id not configured")
            return False
        return post_to_channel(cockpit, summary)
    except Exception as e:
        logger.warning("ai_head_audit: cockpit post raised: %s", e)
        return False


def _safe_post_dm(summary: str) -> bool:
    try:
        from outputs.slack_notifier import post_to_channel
        return post_to_channel(_DIRECTOR_DM_CHANNEL, summary)
    except Exception as e:
        logger.warning("ai_head_audit: DM post raised: %s", e)
        return False
