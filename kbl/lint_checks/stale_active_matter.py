"""Check 5 — stale_active_matter (warn, LLM-assisted).

Two gates:

1. **Filesystem mtime** — newest mtime across the matter dir (excluding
   ``.DS_Store``, files under ``_inbox/``, and stub-tagged signal pastes
   that begin with ``<!-- stub:signal_id=…``). If newest mtime is within
   ``WIKI_LINT_STALE_DAYS``, no LLM call.

2. **Gemini Pro classification** — when filesystem says "stale", read
   ``gold.md`` (or the matter's most recent 3 ``.md`` files for flat
   patterns) and ask Pro to classify ``still_relevant`` vs
   ``drifted_past_current_reality``. Only the latter raises a warn.

Tests inject ``llm_caller`` to avoid live API calls.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
from pathlib import Path
from typing import Callable

from . import _common as C

logger = logging.getLogger("kbl.wiki_lint.stale")

CHECK_NAME = "stale_active_matter"

_SIGNAL_STUB_PREFIX = "<!-- stub:signal_id="


def _newest_authored_mtime(p: Path) -> _dt.datetime | None:
    newest: float | None = None
    for f in p.rglob("*.md"):
        rel_parts = f.relative_to(p).parts
        if any(part == "_inbox" for part in rel_parts):
            continue
        try:
            head = f.read_text(encoding="utf-8", errors="replace")[:80]
        except OSError:
            continue
        if head.lstrip().startswith(_SIGNAL_STUB_PREFIX):
            continue
        try:
            ts = f.stat().st_mtime
        except OSError:
            continue
        if newest is None or ts > newest:
            newest = ts
    if newest is None:
        return None
    return _dt.datetime.utcfromtimestamp(newest)


def _gather_context(m: C.MatterDir, max_chars: int = 30_000) -> str:
    parts: list[str] = []
    if m.nested:
        for fname in ("gold.md", "_overview.md"):
            f = m.path / fname
            if f.is_file():
                try:
                    parts.append(f"### {fname}\n" + f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
        inter = m.path / "interactions"
        if inter.is_dir():
            files = sorted(inter.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
            for f in files[:3]:
                try:
                    parts.append(f"### {f.relative_to(m.path)}\n" + f.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass
    else:
        files = sorted(m.path.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
        for f in files[:3]:
            try:
                parts.append(f"### {f.name}\n" + f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    blob = "\n\n".join(parts)
    if len(blob) > max_chars:
        blob = blob[:max_chars]
    return blob


def _default_llm_caller(messages, max_tokens=400, system=None):
    from orchestrator.gemini_client import call_pro
    return call_pro(messages=messages, max_tokens=max_tokens, system=system)


def run(
    vault_path: Path,
    registries: dict,
    llm_caller: Callable | None = None,
) -> list[C.LintHit]:
    days = int(registries.get("stale_days", 60))
    now = registries.get("now_utc")
    if isinstance(now, str):
        now = _dt.datetime.fromisoformat(now)
    elif now is None:
        now = _dt.datetime.utcnow()
    cutoff = now - _dt.timedelta(days=days)

    caller = llm_caller or _default_llm_caller
    cost_log: list[tuple[int, int]] = registries.setdefault("_llm_token_log", [])
    token_ceiling = int(registries.get("token_ceiling", 200_000))

    hits: list[C.LintHit] = []
    for m in C.discover_matter_dirs(vault_path):
        newest = _newest_authored_mtime(m.path)
        if newest is not None and newest > cutoff:
            continue
        blob = _gather_context(m)
        if not blob.strip():
            continue
        # Token-ceiling pre-check (rough estimate).
        estimated = sum(t[0] + t[1] for t in cost_log) + len(blob) // 4
        if estimated > token_ceiling:
            registries["_aborted"] = "token_ceiling_exceeded"
            logger.warning("stale_active_matter: token ceiling reached, aborting check")
            break

        prompt = (
            "You audit Brisen-Group wiki matter directories for staleness.\n"
            f"MATTER: {m.slug}\n"
            f"NEWEST DIRECTOR-AUTHORED CONTENT: "
            f"{newest.isoformat() if newest else 'unknown'}\n\n"
            "Read the content below and answer with ONE WORD only:\n"
            "  STILL_RELEVANT — gold/overview reflect current reality\n"
            "  DRIFTED       — gold/overview describe a state of the world that has clearly moved on\n"
            "If the matter looks active and not drifted, output STILL_RELEVANT.\n"
            "---\n" + blob
        )
        try:
            resp = caller(messages=[{"role": "user", "content": prompt}], max_tokens=10)
        except Exception as exc:
            logger.warning("stale_active_matter: LLM call failed for %s: %s", m.slug, exc)
            continue
        cost_log.append((
            getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0,
            getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0,
        ))
        verdict = (getattr(resp, "text", "") or "").strip().upper()
        if "DRIFT" not in verdict:
            continue
        last_iso = newest.date().isoformat() if newest else "unknown"
        hits.append(C.LintHit(
            check=CHECK_NAME,
            severity=C.Severity.WARN,
            path=m.rel,
            line=None,
            message=f"stale active matter: newest authored content {last_iso} (>{days}d), Gemini Pro classified DRIFTED",
        ))

    # Cost logging hook (best-effort).
    if cost_log and not registries.get("_skip_cost_log"):
        try:
            from orchestrator.cost_monitor import log_api_cost
            ti = sum(t[0] for t in cost_log)
            to = sum(t[1] for t in cost_log)
            if (ti + to) > 0:
                log_api_cost("gemini-2.5-pro", ti, to, source="wiki_lint_stale")
        except Exception:
            pass
    if os.getenv("WIKI_LINT_DEBUG"):  # pragma: no cover
        logger.info("stale_active_matter: %d hits, %d LLM calls", len(hits), len(cost_log))
    return hits
