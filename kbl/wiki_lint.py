"""Wiki lint entrypoint — WIKI_LINT_1 (V1).

Single-entrypoint runner. Walks ``BAKER_VAULT_PATH/wiki/``, runs the 7
checks (4 deterministic, 1 hybrid filesystem+Postgres, 2 LLM-assisted),
writes a markdown report to ``outputs/lint/YYYY-MM-DD.md`` (V1 location
— see V1/V2 carve-out in ``briefs/BRIEF_WIKI_LINT_1.md``), and posts a
Slack summary tagged by severity.

Scheduler entrypoint: ``run()``. CLI entrypoint: ``python -m kbl.wiki_lint
[--vault-path PATH] [--dry-run] [--no-slack]``.

Per spec output path V1/V2 carve-out (CHANDA #9): V1 writes inside the
baker-master tree at ``outputs/lint/``; V2 mirrors to ``baker-vault/lint/``
via a separate Mac Mini SSH-mirror brief.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import time
from collections import Counter
from pathlib import Path
from typing import Callable

from kbl.lint_checks import _common as C
from kbl.lint_checks import (
    contradiction_within_matter,
    inbox_overdue,
    missing_required_files,
    one_way_cross_ref,
    orphan_matter_dir,
    retired_slug_reference,
    stale_active_matter,
)

logger = logging.getLogger("kbl.wiki_lint")

# Order matters — checks 1 + 2 are filename/path-driven; 3 + 4 build the
# graph; 5 + 6 are LLM-assisted (after token-ceiling pre-flight); 7 is
# inbox hygiene. The top-level `run()` enforces this ordering so token
# accounting accumulates correctly across 5 + 6.
DETERMINISTIC_CHECKS = (
    ("retired_slug_reference", retired_slug_reference.run),
    ("missing_required_files", missing_required_files.run),
    ("orphan_matter_dir", orphan_matter_dir.run),
    ("one_way_cross_ref", one_way_cross_ref.run),
    ("inbox_overdue", inbox_overdue.run),
)
LLM_CHECKS = (
    ("stale_active_matter", stale_active_matter.run),
    ("contradiction_within_matter", contradiction_within_matter.run),
)
ALL_CHECK_NAMES = [n for n, _ in DETERMINISTIC_CHECKS] + [n for n, _ in LLM_CHECKS]


# ---------------------------------------------------------------------------
# Severity gating + Slack
# ---------------------------------------------------------------------------

def _severity_tag(counts: Counter, aborted: str | None) -> str:
    if aborted:
        return f"⚠️ wiki lint aborted ({aborted})"
    if counts.get(C.Severity.ERROR.value, 0) > 0:
        return "🔴 wiki lint errors"
    if counts.get(C.Severity.WARN.value, 0) > 0:
        return "🟡 wiki lint warnings"
    return "ℹ️ wiki lint clean (info only)"


def _slack_summary(report_path: str, counts: Counter, aborted: str | None) -> str:
    tag = _severity_tag(counts, aborted)
    e = counts.get(C.Severity.ERROR.value, 0)
    w = counts.get(C.Severity.WARN.value, 0)
    i = counts.get(C.Severity.INFO.value, 0)
    return (
        f"{tag}\n"
        f"`{report_path}`\n"
        f"{e} errors · {w} warnings · {i} info"
    )


def _post_slack(text: str) -> bool:
    if os.getenv("WIKI_LINT_SLACK_DRY", "").lower() in ("1", "true", "yes"):
        logger.info("wiki_lint_slack_dry: %s", text)
        return True
    try:
        from outputs.slack_notifier import post_to_channel
        from config.settings import config as _cfg
        channel = os.getenv("WIKI_LINT_SLACK_CHANNEL")
        if not channel:
            channel = getattr(getattr(_cfg, "slack", None), "cockpit_channel_id", None)
        if not channel:
            logger.warning("wiki_lint: no Slack channel configured (WIKI_LINT_SLACK_CHANNEL or cockpit_channel_id)")
            return False
        return bool(post_to_channel(channel, text))
    except Exception as exc:
        logger.warning("wiki_lint: Slack post failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def _format_report(
    today: _dt.date,
    hits_by_check: dict[str, list[C.LintHit]],
    counts: Counter,
    runtime_seconds: float,
    aborted: str | None,
) -> str:
    e = counts.get(C.Severity.ERROR.value, 0)
    w = counts.get(C.Severity.WARN.value, 0)
    i = counts.get(C.Severity.INFO.value, 0)
    out: list[str] = [
        f"# Wiki lint — {today.isoformat()}",
        "",
        "## Summary",
        f"- {e} errors, {w} warnings, {i} info items",
        f"- Runtime: {runtime_seconds:.1f}s",
    ]
    if aborted:
        out.append(f"- ABORTED: {aborted}")
    out.append("")

    def _section(title: str, sev: C.Severity) -> None:
        out.append(f"## {title}")
        wrote = False
        for name in ALL_CHECK_NAMES:
            relevant = [h for h in hits_by_check.get(name, []) if h.severity == sev]
            if not relevant:
                continue
            wrote = True
            out.append(f"### Check: {name} ({len(relevant)} hit{'s' if len(relevant) != 1 else ''})")
            for h in relevant:
                line = f":{h.line}" if h.line else ""
                out.append(f"- `{h.path}{line}` — {h.message}")
            out.append("")
        if not wrote:
            out.append("_(none)_")
            out.append("")

    _section("Errors", C.Severity.ERROR)
    _section("Warnings", C.Severity.WARN)
    _section("Info", C.Severity.INFO)

    out.append("## Checks executed")
    for name in ALL_CHECK_NAMES:
        n = len(hits_by_check.get(name, []))
        out.append(f"- {name}: {n} hit{'s' if n != 1 else ''}")
    out.append("")
    return "\n".join(out)


def _write_report(report_dir: Path, today: _dt.date, body: str) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{today.isoformat()}.md"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Core runner
# ---------------------------------------------------------------------------

def _retired_slugs() -> set[str]:
    try:
        from kbl.slug_registry import _get_registry  # type: ignore[attr-defined]
        reg = _get_registry()
        return {s for s, e in reg.entries.items() if e.status == "retired"}
    except Exception as exc:
        logger.warning("wiki_lint: slug registry unavailable (%s) — skipping check 1", exc)
        return set()


def run(
    vault_path: Path | str | None = None,
    *,
    dry_run: bool = False,
    post_slack: bool = True,
    llm_caller: Callable | None = None,
    today: _dt.date | None = None,
    output_dir: Path | None = None,
    overrides: dict | None = None,
) -> dict:
    """Execute one full lint cycle. Returns a result dict.

    ``llm_caller`` injects a stub for tests. ``overrides`` lets callers
    pre-seed ``signal_last_seen`` / ``token_ceiling`` etc. for tests.
    """
    started = time.monotonic()
    if vault_path is None:
        vp = os.getenv("BAKER_VAULT_PATH")
        if not vp:
            logger.warning("wiki_lint: BAKER_VAULT_PATH not set — skipping run")
            return {"ok": False, "skipped": "BAKER_VAULT_PATH not set"}
        vault_path = vp
    vault = Path(vault_path).expanduser()
    if not (vault / "wiki").is_dir():
        logger.warning("wiki_lint: %s/wiki/ missing — skipping run", vault)
        return {"ok": False, "skipped": f"{vault}/wiki/ missing"}

    today = today or _dt.datetime.utcnow().date()
    out_dir = output_dir or Path(__file__).resolve().parents[1] / "outputs" / "lint"

    registries: dict = {
        "retired_slugs": _retired_slugs(),
        "stale_days": int(os.getenv("WIKI_LINT_STALE_DAYS", "60")),
        "inbox_days": int(os.getenv("WIKI_LINT_INBOX_DAYS", "14")),
        "orphan_days": int(os.getenv("WIKI_LINT_ORPHAN_DAYS", "90")),
        "token_ceiling": int(os.getenv("WIKI_LINT_TOKEN_CEILING", "200000")),
        "today_utc": today.isoformat(),
        "now_utc": _dt.datetime.utcnow().isoformat(),
    }
    if overrides:
        registries.update(overrides)

    hits_by_check: dict[str, list[C.LintHit]] = {}

    for name, fn in DETERMINISTIC_CHECKS:
        try:
            hits_by_check[name] = list(fn(vault, registries) or [])
        except Exception as exc:
            logger.error("wiki_lint: check %s raised: %s", name, exc, exc_info=True)
            hits_by_check[name] = []

    for name, fn in LLM_CHECKS:
        try:
            hits_by_check[name] = list(fn(vault, registries, llm_caller=llm_caller) or [])
        except Exception as exc:
            logger.error("wiki_lint: check %s raised: %s", name, exc, exc_info=True)
            hits_by_check[name] = []

    counts: Counter = Counter()
    for hits in hits_by_check.values():
        for h in hits:
            counts[h.severity.value] += 1

    aborted = registries.get("_aborted")
    runtime = time.monotonic() - started
    body = _format_report(today, hits_by_check, counts, runtime, aborted)

    report_path = _write_report(out_dir, today, body)
    rel_report = str(report_path)
    logger.info("wiki_lint: report at %s (%s errors, %s warnings, %s info)",
                rel_report,
                counts.get("error", 0), counts.get("warn", 0), counts.get("info", 0))

    slack_ok = False
    if post_slack and not dry_run:
        slack_ok = _post_slack(_slack_summary(rel_report, counts, aborted))
    elif dry_run:
        logger.info("wiki_lint dry-run: skipped Slack post")

    return {
        "ok": True,
        "errors": counts.get("error", 0),
        "warnings": counts.get("warn", 0),
        "info": counts.get("info", 0),
        "report_path": rel_report,
        "runtime_seconds": runtime,
        "aborted": aborted,
        "slack_ok": slack_ok,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wiki lint runner (WIKI_LINT_1)")
    parser.add_argument("--vault-path", default=None, help="Vault root (defaults to BAKER_VAULT_PATH)")
    parser.add_argument("--dry-run", action="store_true", help="Skip Slack post")
    parser.add_argument("--no-slack", action="store_true", help="Skip Slack post (alias for --dry-run for posting)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=os.getenv("WIKI_LINT_LOG", "INFO"))
    res = run(
        vault_path=args.vault_path,
        dry_run=args.dry_run or args.no_slack,
        post_slack=not (args.dry_run or args.no_slack),
    )
    if not res.get("ok"):
        return 1
    if res.get("errors", 0) > 0:
        # Errors don't fail the CLI by default — Slack + report are the
        # delivery channel. Director may flip later.
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
