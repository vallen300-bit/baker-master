"""GOLD_COMMENT_WORKFLOW_1 — read + audit aggregator.

Wraps `gold_drift_detector.audit_all()` and emits a structured report
(count by code, list of files affected). Returns a dict suitable for
storage in the `gold_audits.payload_jsonb` column.

Distinct consumer from `kbl.loop.load_gold_context_by_matter` (Cortex
Leg 1 prompt-context loader): this module is for audit + integrity
reporting; that one is for in-prompt content concat.
"""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from kbl import gold_drift_detector

logger = logging.getLogger("baker.gold_parser")


def emit_audit_report(vault_root: Path) -> dict:
    """Run a full-corpus audit and return a serialisable summary.

    Returns:
        {
            "issues_count":     <int>,
            "by_code":          {"SCHEMA": <int>, "DV_ONLY": <int>, ...},
            "files":            [<path>, ...]   # unique file paths with issues
            "payload":          {"issues": [{"code", "message", "file_path"}, ...]},
        }

    Empty `issues_count == 0` → clean corpus.
    """
    issues = gold_drift_detector.audit_all(vault_root)

    by_code = Counter(i.code for i in issues)
    files = sorted({i.file_path for i in issues if i.file_path})

    payload = {
        "issues": [
            {
                "code": i.code,
                "message": i.message,
                "file_path": i.file_path,
            }
            for i in issues
        ],
    }

    return {
        "issues_count": len(issues),
        "by_code": dict(by_code),
        "files": files,
        "payload": payload,
    }
