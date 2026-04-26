"""Check 6 — contradiction_within_matter (warn, LLM-assisted).

Per spec: ``call_pro()`` reads all ``.md`` in a matter dir in one call
(2M context fits 100+ files). Asks Gemini Pro to surface conflicting
factual claims (status, parties, financial amounts, dates) with file
paths and quoted excerpts.

Output contract from the LLM (single line per finding):
  ``CONFLICT | <fileA>:<excerptA> || <fileB>:<excerptB>``
Anything else is logged but not emitted as a hit. ``NO_CONFLICTS`` is
the explicit "clean" sentinel.

Tests inject ``llm_caller``.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from . import _common as C

logger = logging.getLogger("kbl.wiki_lint.contradiction")

CHECK_NAME = "contradiction_within_matter"


def _matter_blob(m: C.MatterDir, max_chars: int = 200_000) -> str:
    parts: list[str] = []
    used = 0
    for f in sorted(m.path.rglob("*.md")):
        rel = f.relative_to(m.path)
        if any(p == "_inbox" for p in rel.parts):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Skip pure signal-stub pastes.
        if text.lstrip().startswith("<!-- stub:signal_id="):
            continue
        chunk = f"\n\n===FILE: {rel}===\n{text}"
        if used + len(chunk) > max_chars:
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts)


def _default_llm_caller(messages, max_tokens=2000, system=None):
    from orchestrator.gemini_client import call_pro
    return call_pro(messages=messages, max_tokens=max_tokens, system=system)


def _parse_conflicts(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip().lstrip("-* ").strip()
        if not line:
            continue
        if line.upper().startswith("NO_CONFLICTS"):
            return []
        if line.upper().startswith("CONFLICT"):
            out.append(line)
    return out


def run(
    vault_path: Path,
    registries: dict,
    llm_caller: Callable | None = None,
) -> list[C.LintHit]:
    if registries.get("_aborted") == "token_ceiling_exceeded":
        return []

    caller = llm_caller or _default_llm_caller
    cost_log: list[tuple[int, int]] = registries.setdefault("_llm_token_log", [])
    token_ceiling = int(registries.get("token_ceiling", 200_000))

    hits: list[C.LintHit] = []
    for m in C.discover_matter_dirs(vault_path):
        blob = _matter_blob(m)
        if not blob.strip() or len(blob) < 200:
            continue
        estimated = sum(t[0] + t[1] for t in cost_log) + len(blob) // 4
        if estimated > token_ceiling:
            registries["_aborted"] = "token_ceiling_exceeded"
            logger.warning("contradiction_within_matter: token ceiling reached, aborting check")
            break

        prompt = (
            "You audit a Brisen-Group wiki matter directory for INTERNAL CONTRADICTIONS.\n"
            f"MATTER: {m.slug}\n\n"
            "Find pairs of factual claims (status, parties, financial amounts, dates)\n"
            "that conflict with each other. Quote ≤15 words per excerpt.\n\n"
            "Output format — one line per finding, exactly:\n"
            "  CONFLICT | <fileA>:<excerptA> || <fileB>:<excerptB>\n"
            "If no contradictions found, output a single line:\n"
            "  NO_CONFLICTS\n\n"
            "MATTER CONTENT FOLLOWS:\n" + blob
        )
        try:
            resp = caller(messages=[{"role": "user", "content": prompt}], max_tokens=2000)
        except Exception as exc:
            logger.warning("contradiction_within_matter: LLM call failed for %s: %s", m.slug, exc)
            continue
        cost_log.append((
            getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0,
            getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0,
        ))
        for line in _parse_conflicts(getattr(resp, "text", "") or ""):
            hits.append(C.LintHit(
                check=CHECK_NAME,
                severity=C.Severity.WARN,
                path=m.rel,
                line=None,
                message=line,
            ))

    if cost_log and not registries.get("_skip_cost_log"):
        try:
            from orchestrator.cost_monitor import log_api_cost
            ti = sum(t[0] for t in cost_log)
            to = sum(t[1] for t in cost_log)
            if (ti + to) > 0:
                log_api_cost("gemini-2.5-pro", ti, to, source="wiki_lint_contradiction")
        except Exception:
            pass
    if os.getenv("WIKI_LINT_DEBUG"):  # pragma: no cover
        logger.info("contradiction_within_matter: %d hits", len(hits))
    return hits
