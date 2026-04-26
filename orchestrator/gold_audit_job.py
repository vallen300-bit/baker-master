"""GOLD_COMMENT_WORKFLOW_1 — weekly audit job body.

Registered by triggers/embedded_scheduler as `gold_audit_sentinel`
(Mon 09:30 UTC, behind GOLD_AUDIT_ENABLED env flag).

Flow:
  1. gold_parser.emit_audit_report(vault_root) → structured report.
  2. INSERT row into gold_audits (issues_count + payload_jsonb).
  3. If issues_count > 0, push a Slack DM via the canonical
     triggers.ai_head_audit._safe_post_dm helper.

Failures are logged but never crash the scheduler.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("baker.gold_audit_sentinel")


def _gold_audit_sentinel_job() -> None:
    try:
        from kbl import gold_parser
        vault = Path(
            os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault"))
        )
        report = gold_parser.emit_audit_report(vault)

        _persist(report)

        if report.get("issues_count", 0) > 0:
            _push_slack_dm(report)
    except Exception as e:
        logger.error("gold_audit_sentinel_job failed: %s", e, exc_info=True)


def _persist(report: dict) -> None:
    """Insert the audit report into gold_audits. Best-effort."""
    try:
        from memory.store_back import SentinelStoreBack
        sb = SentinelStoreBack._get_global_instance()
        sb._ensure_gold_audits_table()
        conn = sb._get_conn()
        if conn is None:
            return
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO gold_audits (issues_count, payload_jsonb) "
                "VALUES (%s, %s::jsonb)",
                (
                    int(report.get("issues_count", 0)),
                    json.dumps(report.get("payload", {})),
                ),
            )
            conn.commit()
            cur.close()
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("gold_audits insert failed (non-fatal): %s", e)
        finally:
            sb._put_conn(conn)
    except Exception as e:
        logger.warning("gold_audits persist outer failed (non-fatal): %s", e)


def _push_slack_dm(report: dict) -> None:
    """Slack-DM the AI Head if drift issues found. Reuses the canonical helper."""
    by_code = report.get("by_code", {}) or {}
    summary = (
        f"Gold audit weekly ({report.get('issues_count', 0)} issues): "
        + ", ".join(f"{k}={v}" for k, v in sorted(by_code.items()))
        + ". See gold_audits table latest row for full payload."
    )
    try:
        from triggers.ai_head_audit import _safe_post_dm
        _safe_post_dm(summary)
    except Exception as e:
        logger.warning("gold_audit Slack DM failed (non-fatal): %s", e)
