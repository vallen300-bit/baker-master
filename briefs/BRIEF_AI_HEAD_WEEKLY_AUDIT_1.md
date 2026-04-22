# BRIEF: AI_HEAD_WEEKLY_AUDIT_1 — Weekly self-audit job for AI Head memory files

## Context

AI Head is Baker's primary execution agent, canonically defined at `baker-vault/_ops/skills/ai-head/SKILL.md` (vault commit 373551e, 2026-04-22) with a 3-file memory triplet under `baker-vault/_ops/agents/ai-head/` (OPERATING / LONGTERM / ARCHIVE).

SKILL.md §Weekly Self-Audit mandates a weekly job that:
1. Scans the triplet for drift (stale OPERATING entries, old LONGTERM facts, retired Tier A items)
2. Reviews past-week ARCHIVE "Lessons / will change" blocks for recurring patterns worth upgrading into SKILL.md or LONGTERM.md
3. Writes an audit record and pushes a plain-English summary to Director via Slack (#cockpit + Director DM)

The audit is a hedge against the exact entropy that made the 2026-04-22 consolidation necessary in the first place.

Director ratified the embedded-scheduler implementation path on 2026-04-22 (quote: *"option 4"*) after rejecting /schedule (claude.ai OAuth blocker) and Render cron (unnecessary new infra). Pattern to mirror: existing `_hot_md_weekly_nudge_job` at `triggers/embedded_scheduler.py:684`.

## Estimated time: ~2-3h
## Complexity: Medium
## Prerequisites:
- `SLACK_BOT_TOKEN` env var already set on Render (verify via `curl -s <service>/env-vars | grep SLACK_BOT_TOKEN`)
- `im:write` scope on the bot token (Director confirmed live 2026-04-22, DM channel `D0AFY28N030` open, logged to `baker_actions` per Invariant S2)
- `baker-vault` read-only mirror already present on Render (via `vault_mirror.sync_tick`, fires every 5min)
- Python 3.11+, APScheduler, slack_sdk, psycopg2 all already in `requirements.txt` — **no new dependencies**

---

## Fix/Feature 1: New PG table `ai_head_audits` + bootstrap DDL

### Problem

No persistence layer exists for audit records. Findings must be queryable (`SELECT * FROM ai_head_audits ORDER BY ran_at DESC LIMIT 10`) and survive Render restarts.

### Current State

`memory/store_back.py` owns all PostgreSQL bootstrap DDL via `_ensure_*_table` methods (e.g., `_ensure_baker_insights_table` at line 464; pattern shared by 20+ tables). Initialization calls these methods in the `__init__` path around lines 64-145.

### Implementation

Add new method to `memory/store_back.py`:

```python
def _ensure_ai_head_audits_table(self):
    """BRIEF_AI_HEAD_WEEKLY_AUDIT_1: Weekly self-audit records for AI Head.

    Populated by the embedded_scheduler _ai_head_weekly_audit_job.
    One row per audit run (Mondays 09:00 UTC).
    """
    conn = self._get_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_head_audits (
                id SERIAL PRIMARY KEY,
                ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                drift_items JSONB NOT NULL DEFAULT '[]'::jsonb,
                lesson_patterns JSONB NOT NULL DEFAULT '[]'::jsonb,
                summary_text TEXT NOT NULL,
                slack_cockpit_ok BOOLEAN NOT NULL DEFAULT FALSE,
                slack_dm_ok BOOLEAN NOT NULL DEFAULT FALSE,
                mirror_last_pull_at TIMESTAMPTZ,
                mirror_head_sha TEXT
            )
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_head_audits_ran_at "
            "ON ai_head_audits(ran_at DESC)"
        )
        conn.commit()
        cur.close()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning(f"Could not ensure ai_head_audits table: {e}")
    finally:
        self._put_conn(conn)
```

Wire the call into `__init__`. Add this line alongside the other `self._ensure_*` calls (after line 145 `self._ensure_baker_insights_table()` — co-locate with other single-table bootstraps):

```python
self._ensure_ai_head_audits_table()
```

### Key Constraints

- `JSONB` for structured drift/lesson data — queryable, indexable, no ORM needed
- `TIMESTAMPTZ` + `NOW()` — Baker convention
- Index on `ran_at DESC` — fast recent-N query
- NOT NULL on `summary_text` — every audit produces a human-readable summary even if drift/lesson lists are empty

### Verification

After deploy, run on Render PostgreSQL:
```sql
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'ai_head_audits' ORDER BY ordinal_position;
```
Expect 9 columns with types matching the CREATE TABLE above.

---

## Fix/Feature 2: DM helper in `outputs/slack_notifier.py`

### Problem

`SlackNotifier._post` (line 265) hardcodes `channel=self._channel` (= cockpit). Director DM requires posting to a different channel ID (`D0AFY28N030`). Need a minimal module-level helper to avoid subclassing for a one-line variation.

### Current State

`outputs/slack_notifier.py`:
- `_get_webclient()` at line 105 — lazy Slack WebClient factory
- `class SlackNotifier` at line 111 — targets `config.slack.cockpit_channel_id`
- `_post` at line 265 — calls `client.chat_postMessage(channel=self._channel, …)`

No existing helper for arbitrary-channel posts. Closest is `post_thread_reply` at line 198 (takes `channel_id` but requires `thread_ts`).

### Implementation

Add a new **module-level** function to `outputs/slack_notifier.py` (not a method on SlackNotifier — keep surface additive, scope-minimal):

```python
def post_to_channel(channel_id: str, text: str) -> bool:
    """Post plain text to an arbitrary Slack channel (DMs included).

    BRIEF_AI_HEAD_WEEKLY_AUDIT_1: used by the weekly self-audit job to
    post to Director's DM (D0AFY28N030) alongside #cockpit. Uses the
    existing ``_get_webclient`` lazy factory; returns ``False`` on any
    failure (non-fatal — matches SlackNotifier invariant).

    Args:
        channel_id: Slack channel ID (C… for channels, D… for DMs).
        text: Plain text body. Max 3000 chars recommended for push
              notifications; not Block Kit — caller ensures no markdown
              surprises on mobile.
    Returns:
        True on Slack API ok=true; False otherwise.
    """
    if not config.outputs.slack_bot_token:
        logger.warning("post_to_channel skipped: SLACK_BOT_TOKEN not configured")
        return False
    try:
        client = _get_webclient()
        resp = client.chat_postMessage(
            channel=channel_id,
            text=text[:3000],
        )
        if resp.get("ok"):
            return True
        logger.warning(
            f"post_to_channel failed ({channel_id}): {resp.get('error')}"
        )
        return False
    except Exception as e:
        logger.warning(f"post_to_channel raised ({channel_id}): {e}")
        return False
```

### Key Constraints

- **No Block Kit.** Director's spec (2026-04-22): plain English, ≤3 sentences, no markdown. Block Kit on DMs renders inconsistently on iPhone for simple messages — plain text is the right call here.
- **Non-fatal on any failure.** Match the invariant documented in SlackNotifier's docstring: "All operations are non-fatal — failures are logged but never raise."
- **Truncate at 3000 chars.** Same limit as `post_thread_reply`.
- **Do NOT modify SlackNotifier class.** Additive only — avoids churn in existing alert/briefing/pipeline paths.

### Verification

Manual smoke test after deploy (Render shell or equivalent):
```python
from outputs.slack_notifier import post_to_channel
assert post_to_channel("D0AFY28N030", "test from smoke") is True
```

---

## Fix/Feature 3: Audit logic module `triggers/ai_head_audit.py`

### Problem

Audit logic (drift detection + lesson pattern counting + PG write + Slack push) is ~100 lines. Inlining into `embedded_scheduler.py` bloats that file and makes the unit test harder (would need to mock too many things at once).

### Current State

No module exists. `vault_mirror.list_ops_files` (line 304) and `vault_mirror.read_ops_file` (line 342) are the canonical read API. `vault_mirror.mirror_status` (line 247) exposes `last_pull_at` for the staleness check.

### Implementation

Create new file `triggers/ai_head_audit.py`:

```python
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

_COCKPIT_CHANNEL = None  # resolved from config at call time
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

    # 1. Mirror health check
    mirror_info = _safe_mirror_status()

    # 2. Read triplet
    operating_content = _safe_read(f"{_AI_HEAD_PREFIX}OPERATING.md")
    longterm_content = _safe_read(f"{_AI_HEAD_PREFIX}LONGTERM.md")
    archive_content = _safe_read(f"{_AI_HEAD_PREFIX}ARCHIVE.md")

    # 3. Classify drift
    drift_items = _classify_drift(
        operating_content=operating_content,
        longterm_content=longterm_content,
        archive_content=archive_content,
        reference_now=started_at,
    )

    # 4. Count lesson patterns from past week's ARCHIVE blocks
    lesson_patterns = _count_recent_lesson_patterns(
        archive_content=archive_content,
        reference_now=started_at,
    )

    # 5. Compose summary (≤3 lines, plain English, no markdown)
    summary = _compose_summary(
        drift_items=drift_items,
        lesson_patterns=lesson_patterns,
        mirror_info=mirror_info,
    )

    # 6. Write PG row
    slack_cockpit_ok = False
    slack_dm_ok = False
    record_id = _write_audit_record(
        ran_at=started_at,
        drift_items=drift_items,
        lesson_patterns=lesson_patterns,
        summary_text=summary,
        slack_cockpit_ok=slack_cockpit_ok,  # updated post-push in follow-up UPDATE
        slack_dm_ok=slack_dm_ok,
        mirror_info=mirror_info,
    )

    # 7. Push summary — #cockpit + Director DM, independent calls
    slack_cockpit_ok = _safe_post_cockpit(summary)
    slack_dm_ok = _safe_post_dm(summary)

    # 8. Update the row with Slack outcomes (best-effort; don't raise on failure)
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

    NOTE: vault_mirror.mirror_status() returns
    ``{vault_mirror_last_pull: ISO-string | None, vault_mirror_commit_sha: str | None}``
    (verified 2026-04-22 at vault_mirror.py:247). We unpack + parse here,
    not in the caller.
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

    # OPERATING staleness
    op_date = _latest_date_in(operating_content)
    if op_date and (reference_now.date() - op_date).days > _OPERATING_STALE_THRESHOLD_DAYS:
        items.append({
            "category": "operating_stale",
            "file": "OPERATING.md",
            "detail": f"Latest date reference {op_date.isoformat()} is "
                      f"{(reference_now.date() - op_date).days} days old; "
                      f"rewrite candidate.",
        })

    # LONGTERM updated field
    lt_updated = _frontmatter_date(longterm_content, "updated")
    if lt_updated and (reference_now.date() - lt_updated).days > _LONGTERM_STALE_THRESHOLD_DAYS:
        items.append({
            "category": "longterm_stale",
            "file": "LONGTERM.md",
            "detail": f"Frontmatter updated={lt_updated.isoformat()} is "
                      f"{(reference_now.date() - lt_updated).days} days old; "
                      f"review for fact changes.",
        })

    # Tier A referenced-in-recent-ARCHIVE
    # Conservative: only flag entries with literal text patterns that haven't
    # appeared in any ARCHIVE block. Brief §Follow-on: refine with semantic
    # match in v2.
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
    """Return list of {pattern, count, first_seen} across past week's Lessons blocks."""
    window_start = reference_now - timedelta(days=_ARCHIVE_LESSONS_WINDOW_DAYS)
    window_text = _archive_window_text(archive_content, reference_now, days=_ARCHIVE_LESSONS_WINDOW_DAYS)

    # Extract bullet lines under any "Lessons" header in the window
    lessons: list[str] = []
    for match in re.finditer(
        r"\*\*Lessons\s*/?\s*will change:\*\*\s*\n((?:\s*[-*]\s+.+\n?)+)",
        window_text, flags=re.IGNORECASE,
    ):
        block = match.group(1)
        for bullet_match in _LESSON_LINE_RE.finditer(block):
            lessons.append(bullet_match.group(1).strip().lower())

    # Count repeated themes — naive: normalized exact-string match
    counts: dict[str, int] = {}
    for lesson in lessons:
        # Collapse whitespace + lowercase; strip leading date tokens
        key = re.sub(r"\s+", " ", lesson).strip()
        if len(key) < 10:  # skip trivial bullets
            continue
        counts[key] = counts.get(key, 0) + 1

    return [
        {"pattern": pat, "count": cnt}
        for pat, cnt in sorted(counts.items(), key=lambda x: -x[1])
        if cnt >= 1
    ][:10]  # top 10 — keep JSONB payload bounded


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
        rf"^---\s*\n(.*?)\n---",
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
    # Split on H2 session headers (## Session N — YYYY-MM-DD)
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
        store = SentinelStoreBack()
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
        store = SentinelStoreBack()
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
```

### Key Constraints

- **Non-fatal everywhere.** Any failure logs + continues. Weekly audit failing loud = worse than failing quiet (can mask a real issue by making Baker scheduler look broken).
- **Read-only against vault mirror.** No push; v1 does not write to baker-vault.
- **JSONB payloads bounded.** Top-10 lesson patterns only; drift_items unbounded but heuristics cap it naturally.
- **`get_store_back()` is the canonical factory.** Do NOT instantiate SentinelStoreBack directly. If `get_store_back` doesn't exist yet, grep for how other modules access it — fallback is `from memory.store_back import SentinelStoreBack; SentinelStoreBack()`.
- **Lazy imports.** Same pattern as `_hot_md_weekly_nudge_job` — avoid module-load-time side effects.
- **Plain text summary only.** No Block Kit. Mobile rendering is the pass criterion.

### Verification

Unit test (see Fix/Feature 5 below).

---

## Fix/Feature 4: Scheduler registration in `triggers/embedded_scheduler.py`

### Problem

APScheduler must know to run the audit job.

### Current State

`embedded_scheduler.py` registers jobs in a sequence around lines 204-641. Relevant existing examples:
- Line 207: `waha_weekly_restart` on Sunday 04:00 UTC — `CronTrigger(day_of_week="sun", hour=4, minute=0, timezone="UTC")`
- Line 232: `ao_pm_lint` on Sunday 06:00 UTC — same pattern
- Line 614-622: `hot_md_weekly_nudge` — exact pattern to mirror
- Line 684: `_hot_md_weekly_nudge_job` — wrapper function to mirror

### Implementation

In `triggers/embedded_scheduler.py`, directly after the existing `hot_md_weekly_nudge` registration block (around line 624, right before the `# SOT_OBSIDIAN_1_PHASE_D` comment block), add:

```python
    # BRIEF_AI_HEAD_WEEKLY_AUDIT_1: Monday morning AI Head self-audit.
    # Scans baker-vault/_ops/agents/ai-head/ triplet for drift; reviews
    # past-week ARCHIVE Lessons blocks for patterns; writes to PG
    # ai_head_audits table; pushes plain-English summary to #cockpit
    # + Director DM (D0AFY28N030). Fires Mon 09:00 UTC (10:00 CET /
    # 11:00 CEST). Env gate ``AI_HEAD_AUDIT_ENABLED`` (default ``true``).
    _audit_enabled = _os.environ.get("AI_HEAD_AUDIT_ENABLED", "true").lower()
    if _audit_enabled not in ("false", "0", "no", "off"):
        scheduler.add_job(
            _ai_head_weekly_audit_job,
            CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
            id="ai_head_weekly_audit",
            name="AI Head weekly self-audit (Monday 09:00 UTC)",
            coalesce=True, max_instances=1, replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered: ai_head_weekly_audit (Mon 09:00 UTC)")
    else:
        logger.info("Skipped: ai_head_weekly_audit (AI_HEAD_AUDIT_ENABLED=false)")
```

And add the job wrapper (adjacent to `_hot_md_weekly_nudge_job`, around line 711):

```python
def _ai_head_weekly_audit_job():
    """APScheduler wrapper: Monday AI Head self-audit.

    BRIEF_AI_HEAD_WEEKLY_AUDIT_1. Lazy-imports the audit module; swallows
    top-level exceptions as WARN so a single bad week doesn't knock out
    the scheduler. ``run_weekly_audit`` is already non-fatal per step,
    so reaching the outer except here genuinely indicates module-load
    or config failure.
    """
    try:
        from triggers.ai_head_audit import run_weekly_audit
    except Exception as e:
        logger.error("ai_head_weekly_audit: import failed: %s", e)
        return
    try:
        result = run_weekly_audit()
        logger.info("ai_head_weekly_audit: %s", result)
    except Exception as e:
        logger.warning("ai_head_weekly_audit: run raised: %s", e)
```

### Key Constraints

- **Explicit `timezone="UTC"`.** Do NOT rely on scheduler default. `hot_md_weekly_nudge` gets away with it historically, but the canonical pattern (see `waha_weekly_restart`, `ao_pm_lint`) is explicit UTC.
- **`coalesce=True, max_instances=1, replace_existing=True`.** Mirrors all existing weekly jobs. Prevents double-fire on Render rolling deploys.
- **`misfire_grace_time=3600`.** Hour-long tolerance — matches hot_md pattern.
- **Env gate `AI_HEAD_AUDIT_ENABLED`.** Allows Director to kill-switch without redeploy.
- **Add AFTER hot_md_weekly_nudge block, BEFORE vault_sync_tick block.** Preserves logical grouping: weekly one-shots together.

### Verification

On deploy, grep Render logs for:
```
Registered: ai_head_weekly_audit (Mon 09:00 UTC)
```

---

## Fix/Feature 5: Test `tests/test_ai_head_weekly_audit.py` — **SHIP GATE**

### Problem

Ship gate is literal `pytest` output. No "pass by inspection." Brief writer owns the ship-gate test.

### Current State

`tests/` has existing pattern examples:
- `tests/test_hot_md_weekly_nudge.py` — closest analog for a scheduler-driven weekly job
- `tests/test_silver_schema.py` — DDL verification pattern
- `tests/test_mcp_vault_tools.py` — vault_mirror mocking

### Implementation

Create `tests/test_ai_head_weekly_audit.py`:

```python
"""Ship gate for BRIEF_AI_HEAD_WEEKLY_AUDIT_1.

Covers:
  1. Module imports cleanly (registered scheduler + job wrapper)
  2. run_weekly_audit() composes a plain-text ≤3-line summary with no
     markdown tokens (iPhone-safe)
  3. Drift classification: OPERATING >7d old → flagged; LONGTERM <30d
     old → not flagged
  4. Non-fatal on Slack failure: returns a result dict, writes a PG row
     (mocked), and does NOT raise
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _fresh_operating() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "---\nupdated: " + today + "\n---\n\n"
        "# AI Head — Operating Memory\n\n"
        "Last touched " + today + ".\n\n"
        "## Standing Tier A\n"
        "- PR merges on B2 APPROVE + green CI\n"
        "- Mailbox dispatches\n"
    )


def _stale_operating() -> str:
    stale = (datetime.now(timezone.utc) - timedelta(days=14)).date().isoformat()
    return (
        "---\nupdated: " + stale + "\n---\n\n"
        "# AI Head — Operating Memory\n\n"
        "Last touched " + stale + ".\n\n"
        "## Standing Tier A\n"
        "- Old entry from " + stale + "\n"
    )


def _fresh_longterm() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return "---\nupdated: " + today + "\n---\n\n# Longterm\n"


def _archive() -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "---\ntype: ops\n---\n\n# Archive\n\n"
        "## Session 1 — " + today + "\n\n"
        "**Lessons / will change:**\n"
        "- Always pull-rebase before push\n"
        "- Always verify column names against information_schema\n"
    )


def test_module_imports():
    from triggers import ai_head_audit  # noqa: F401
    from triggers.embedded_scheduler import _ai_head_weekly_audit_job  # noqa: F401


def test_summary_is_plain_text_three_lines_max():
    from triggers.ai_head_audit import _compose_summary
    s = _compose_summary(
        drift_items=[{"category": "x", "file": "y", "detail": "z"}],
        lesson_patterns=[{"pattern": "a", "count": 3}],
        mirror_info={"stale": False},
    )
    # No markdown tokens that render oddly on iPhone
    assert "**" not in s
    assert "```" not in s
    assert s.count("\n") <= 2  # ≤3 lines
    assert "audit" in s.lower()


def test_fresh_operating_yields_no_operating_stale_flag():
    from triggers.ai_head_audit import _classify_drift
    now = datetime.now(timezone.utc)
    items = _classify_drift(
        operating_content=_fresh_operating(),
        longterm_content=_fresh_longterm(),
        archive_content=_archive(),
        reference_now=now,
    )
    assert not any(i["category"] == "operating_stale" for i in items)
    assert not any(i["category"] == "longterm_stale" for i in items)


def test_stale_operating_yields_flag():
    from triggers.ai_head_audit import _classify_drift
    now = datetime.now(timezone.utc)
    items = _classify_drift(
        operating_content=_stale_operating(),
        longterm_content=_fresh_longterm(),
        archive_content=_archive(),
        reference_now=now,
    )
    assert any(i["category"] == "operating_stale" for i in items)


def test_run_weekly_audit_is_non_fatal_on_slack_failure():
    """End-to-end non-fatal path: mock everything except the logic itself."""
    # Arrange: mock vault mirror — keys match actual mirror_status() return
    vault_mirror_mock = MagicMock()
    vault_mirror_mock.mirror_status.return_value = {
        "vault_mirror_last_pull": datetime.now(timezone.utc).isoformat(),
        "vault_mirror_commit_sha": "abc123",
    }
    vault_mirror_mock.read_ops_file.side_effect = lambda p: {
        "content_utf8": _fresh_operating()
        if p.endswith("OPERATING.md") else
        _fresh_longterm() if p.endswith("LONGTERM.md") else _archive()
    }
    sys.modules["vault_mirror"] = vault_mirror_mock

    # Mock store_back — canonical pattern is SentinelStoreBack() direct instantiation
    store_instance = MagicMock()
    conn_mock = MagicMock()
    cur_mock = MagicMock()
    cur_mock.fetchone.return_value = (42,)
    conn_mock.cursor.return_value = cur_mock
    store_instance._get_conn.return_value = conn_mock
    store_instance._put_conn = MagicMock()
    store_class_mock = MagicMock(return_value=store_instance)
    store_back_mock = MagicMock()
    store_back_mock.SentinelStoreBack = store_class_mock
    sys.modules["memory.store_back"] = store_back_mock

    # Mock slack — both pushes FAIL
    slack_notifier_mock = MagicMock()
    slack_notifier_mock.post_to_channel.return_value = False
    sys.modules["outputs.slack_notifier"] = slack_notifier_mock

    config_mock = MagicMock()
    config_mock.config.slack.cockpit_channel_id = "C0AF4FVN3FB"
    sys.modules["config.settings"] = config_mock

    # Act
    from triggers.ai_head_audit import run_weekly_audit
    result = run_weekly_audit()

    # Assert: non-fatal — result dict returned, Slack outcomes False
    assert result["record_id"] == 42
    assert result["slack_cockpit_ok"] is False
    assert result["slack_dm_ok"] is False

    # Two Slack posts attempted (cockpit + DM)
    assert slack_notifier_mock.post_to_channel.call_count == 2


def test_ship_gate_verifies_scheduler_registration():
    """Static check: scheduler file references the audit job."""
    from pathlib import Path
    src = Path("triggers/embedded_scheduler.py").read_text()
    assert "ai_head_weekly_audit" in src
    assert 'CronTrigger(day_of_week="mon"' in src
    assert 'timezone="UTC"' in src
    assert "_ai_head_weekly_audit_job" in src
```

### Key Constraints

- **No hitting real DB.** All PG access mocked via `sys.modules` injection.
- **No hitting real Slack.** `post_to_channel` mocked.
- **No hitting real vault mirror.** `vault_mirror` mocked at module level.
- **Ship gate = `pytest tests/test_ai_head_weekly_audit.py -v` prints 6 passed.**

### Verification

```bash
cd ~/bm-b3 && pytest tests/test_ai_head_weekly_audit.py -v
```
Expected: `6 passed`. Paste literal output in CODE_3_RETURN.md.

---

## Files Modified

- `memory/store_back.py` — add `_ensure_ai_head_audits_table` (new method around line 498, right after `_ensure_baker_insights_table`) + wire `self._ensure_ai_head_audits_table()` call into `__init__` (add after the existing line 145 `self._ensure_baker_insights_table()` call)
- `outputs/slack_notifier.py` — add module-level `post_to_channel(channel_id, text)` function (after `_get_webclient` at line 109, before `class SlackNotifier` at line 111)
- `triggers/embedded_scheduler.py` — add scheduler registration block (after line 624 hot_md registration) + add `_ai_head_weekly_audit_job` wrapper (after line 711, adjacent to `_hot_md_weekly_nudge_job`)
- **NEW** `triggers/ai_head_audit.py` — audit logic module
- **NEW** `tests/test_ai_head_weekly_audit.py` — ship gate

## Do NOT Touch

- `vault_mirror.py` — read-only invariant is load-bearing. No push mechanism here in v1.
- Any file under `/Users/dimitry/baker-vault/` — audit reads from the Render mirror only; no vault write-back.
- `SlackNotifier` class — additive module function only.
- `ingest_vault_matter.py`, `lint_ao_pm_vault.py`, `vault_sync_tick` — unrelated.
- Other `_ensure_*_table` methods — additive only.

## Quality Checkpoints

1. **DDL sanity.** On deploy, run `SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'ai_head_audits'` — expect 9 columns.
2. **Scheduler registration log.** Grep Render logs for `Registered: ai_head_weekly_audit (Mon 09:00 UTC)`.
3. **Dry-run smoke test** (Render shell or `python -c`):
   ```python
   from triggers.ai_head_audit import run_weekly_audit
   result = run_weekly_audit()
   print(result)
   ```
   Expect `{record_id: int, drift_count: N, lesson_pattern_count: M, slack_cockpit_ok: True, slack_dm_ok: True, mirror_stale: False}`.
4. **PG row landed.** `SELECT * FROM ai_head_audits ORDER BY ran_at DESC LIMIT 1` — expect recent row.
5. **Slack delivery** — #cockpit should show a message; Director DM D0AFY28N030 should show same message. Mobile rendering clean (no stray asterisks or backticks).
6. **Env gate works.** Set `AI_HEAD_AUDIT_ENABLED=false` → redeploy → grep logs for `Skipped: ai_head_weekly_audit` → unset env var → redeploy → grep `Registered:` again.
7. **Kill-switch intact.** `BAKER_CLICKUP_READONLY=true` doesn't need to affect this path (no ClickUp involvement).
8. **Silent-failure monitoring.** If audit runs but writes no PG row AND Slack shows nothing for 2 consecutive Mondays, B-code alert should fire — document in `sentinel_health` or add a detector in follow-on brief.

## Verification SQL

```sql
-- Confirm table exists with expected schema
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'ai_head_audits'
ORDER BY ordinal_position
LIMIT 20;

-- Check latest audit row
SELECT id, ran_at, jsonb_array_length(drift_items) AS drift_n,
       jsonb_array_length(lesson_patterns) AS pattern_n,
       slack_cockpit_ok, slack_dm_ok, mirror_head_sha
FROM ai_head_audits
ORDER BY ran_at DESC
LIMIT 5;

-- Summary text visibility
SELECT summary_text FROM ai_head_audits ORDER BY ran_at DESC LIMIT 1;
```

## Follow-on / deferred to v2 (document — do not implement)

1. **Vault write-back.** Audit report as markdown written to `baker-vault/_ops/agents/ai-head/AUDIT_<date>.md`. Blocked on Mac Mini push pipeline (doesn't exist).
2. **Semantic drift detection.** V1 uses literal string match for Tier A referenced-in-ARCHIVE; v2 can use embedding-based semantic match (cheap Flash call or local Gemma).
3. **SKILL.md upgrade suggestions.** Audit findings that repeat 3+ weeks should emit a draft diff for Director review. Track via `ai_head_audits.lesson_patterns.count >= 3` over rolling 3 weeks.
4. **Scheduler health assertion.** Add a sentinel that alerts if `ai_head_weekly_audit` job misses 2+ consecutive Mondays (Slack + whatsapp escalation). Ties into broader "silent failure monitoring" gap in existing scheduler.

## Ship Gate (literal pytest output required in CODE_3_RETURN.md)

```bash
cd ~/bm-b3
pytest tests/test_ai_head_weekly_audit.py -v
# Expected: 6 passed
python3 -c "import py_compile; py_compile.compile('triggers/ai_head_audit.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('outputs/slack_notifier.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"
```

Paste the `pytest -v` output literally — no "pass by inspection."

## Code Brief Standards (mandatory fields)

| Field | Value |
|---|---|
| API version / endpoint | APScheduler (Cron/IntervalTrigger), slack_sdk WebClient.chat_postMessage, psycopg2 (via existing pool) |
| Deprecation check date | 2026-04-22 — all deps current, none deprecated |
| Fallback | `post_to_channel` returns False non-fatally on any API failure; audit logs warning + returns result dict with `slack_*_ok=False` |
| Migration vs bootstrap | Bootstrap only (via `_ensure_ai_head_audits_table` in store_back.py). No one-off migration. Grepped `store_back.py` — zero pre-existing references to `ai_head_audits`. |
| Ship gate | Literal `pytest -v` output, 6 tests passing. Syntax check on all 4 touched Python files. |
