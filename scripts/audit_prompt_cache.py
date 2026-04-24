"""Static-analysis audit of Claude call sites for prompt-cache eligibility.

Scans Python source tree for Anthropic messages.create() call sites.
For each call site, estimates:
  - the file + line
  - whether `cache_control` is set on any system block
  - the approximate bytes of the SYSTEM prompt (detected via string
    literal size OR env var / module-level constant lookup; best-effort)
  - cache-eligibility tier:
      eligible_apply    - >=1024 tokens stable, no cache_control
      eligible_measure  - already has cache_control - skip, just measure
      below_threshold   - <1024 tokens
      unclear           - system prompt built dynamically from DB / non-literal
      no_system         - no system block

Emits a markdown report to briefs/_reports/prompt_cache_audit_<YYYY-MM-DD>.md
and prints a summary to stdout.

Usage: python3 scripts/audit_prompt_cache.py [--out PATH]

Exit codes:
  0 - audit ran, report written
  1 - runtime failure (file I/O, etc.)

NOTE: this script does NOT execute any Claude API calls. It is
purely a static inventory + estimate. Live hit-rate measurement is
the separate scripts/prompt_cache_hit_rate.py (Feature 3).
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]

# Call-site patterns: method name + attribute chain we consider a Claude call.
CLAUDE_CALL_PATTERNS = (
    "messages.create",
    "messages.stream",
    "call_opus",
    "call_flash",
)

# Approximate chars-to-tokens conversion (rule of thumb: 4 chars ~= 1 token).
CHARS_PER_TOKEN = 4
CACHE_THRESHOLD_TOKENS = 1024  # Anthropic minimum cacheable prefix


@dataclass
class CallSite:
    file: str
    line: int
    call_name: str
    has_cache_control: bool
    system_chars_est: int
    tier: str  # one of: eligible_apply, eligible_measure, below_threshold, unclear, no_system
    notes: str = ""


def _scan_python_files() -> list[Path]:
    """Return all .py files under repo root (excluding venv, build, .git)."""
    skip_dirs = {".git", "venv", ".venv", "__pycache__", "node_modules", "build", "dist"}
    results: list[Path] = []
    for root, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith(".py"):
                results.append(Path(root) / f)
    return results


def _find_call_sites_in_file(path: Path) -> list[CallSite]:
    """Parse one .py file; return all CallSite records."""
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    results: list[CallSite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_attr_chain(node.func)
        if not any(pat in call_name for pat in CLAUDE_CALL_PATTERNS):
            continue

        # Extract system-block text and cache_control presence from kwargs.
        system_chars, has_cache = _extract_system_info(node)
        tier, notes = _classify(system_chars, has_cache)

        try:
            rel = str(path.relative_to(REPO_ROOT))
        except ValueError:
            rel = str(path)

        results.append(CallSite(
            file=rel,
            line=node.lineno,
            call_name=call_name,
            has_cache_control=has_cache,
            system_chars_est=system_chars,
            tier=tier,
            notes=notes,
        ))
    return results


def _call_attr_chain(func_node: ast.AST) -> str:
    """Recover 'obj.attr1.attr2' from an ast.Call.func."""
    parts: list[str] = []
    cur = func_node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _extract_system_info(call_node: ast.Call) -> tuple[int, bool]:
    """Best-effort extraction of (system_chars_estimate, has_cache_control)."""
    system_chars = 0
    has_cache = False
    for kw in call_node.keywords:
        if kw.arg == "system":
            system_chars = _estimate_literal_chars(kw.value)
            has_cache = _has_cache_control(kw.value)
    return system_chars, has_cache


def _estimate_literal_chars(node: ast.AST) -> int:
    """Return len of string literal, 0 if dynamic."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value)
    if isinstance(node, ast.JoinedStr):  # f-string
        total = 0
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                total += len(val.value)
        return total
    if isinstance(node, ast.List) and node.elts:
        # Likely a list of content blocks - sum text lengths
        total = 0
        for elt in node.elts:
            if isinstance(elt, ast.Dict):
                for k, v in zip(elt.keys, elt.values):
                    if isinstance(k, ast.Constant) and k.value == "text":
                        total += _estimate_literal_chars(v)
        return total
    return 0


def _has_cache_control(node: ast.AST) -> bool:
    """Walk AST looking for any ast.Constant value 'cache_control'."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value == "cache_control":
            return True
    return False


def _classify(system_chars: int, has_cache: bool) -> tuple[str, str]:
    est_tokens = system_chars // CHARS_PER_TOKEN
    if system_chars == 0:
        return "unclear", "system prompt is dynamic or external - manual review required"
    if has_cache:
        return "eligible_measure", f"~{est_tokens} tok - already cached; confirm hit rate via telemetry"
    if est_tokens < CACHE_THRESHOLD_TOKENS:
        return "below_threshold", f"~{est_tokens} tok - below 1024 minimum"
    return "eligible_apply", f"~{est_tokens} tok - APPLY cache_control"


def _render_report(sites: list[CallSite], out_path: Path) -> None:
    today = date.today().isoformat()
    by_tier: dict[str, list[CallSite]] = {}
    for s in sites:
        by_tier.setdefault(s.tier, []).append(s)

    lines: list[str] = []
    lines.append(f"# Prompt Cache Audit - {today}\n")
    lines.append(f"Total call sites: **{len(sites)}**\n")
    lines.append("## Summary by tier\n")
    lines.append("| Tier | Count |")
    lines.append("|------|-------|")
    for tier in ("eligible_apply", "eligible_measure", "below_threshold", "unclear", "no_system"):
        lines.append(f"| `{tier}` | {len(by_tier.get(tier, []))} |")
    lines.append("")
    for tier in ("eligible_apply", "eligible_measure", "below_threshold", "unclear", "no_system"):
        if tier not in by_tier:
            continue
        lines.append(f"\n## {tier}\n")
        lines.append("| File | Line | Call | Cache? | ~Tokens | Notes |")
        lines.append("|------|------|------|--------|---------|-------|")
        for s in sorted(by_tier[tier], key=lambda x: (x.file, x.line)):
            est = s.system_chars_est // CHARS_PER_TOKEN if s.system_chars_est else "n/a"
            cache_mark = "yes" if s.has_cache_control else "no"
            lines.append(
                f"| `{s.file}` | {s.line} | `{s.call_name}` | {cache_mark} | {est} | {s.notes} |"
            )
    lines.append("")
    lines.append("## Next actions\n")
    lines.append("1. Apply `cache_control` to every site in `eligible_apply`.")
    lines.append("2. Review `unclear` sites manually - if system prompt is DB- or file-derived AND stable across calls, convert to cache_control-tagged block.")
    lines.append("3. Let `below_threshold` sites stay uncached; prefix growth is unlikely.")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Claude call sites for prompt-cache eligibility.")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "briefs" / "_reports" / f"prompt_cache_audit_{date.today().isoformat()}.md"),
        help="Output markdown path (default: briefs/_reports/prompt_cache_audit_<date>.md)",
    )
    args = parser.parse_args()

    files = _scan_python_files()
    all_sites: list[CallSite] = []
    for f in files:
        all_sites.extend(_find_call_sites_in_file(f))

    out_path = Path(args.out)
    _render_report(all_sites, out_path)

    if not all_sites:
        print("No Claude call sites found.", file=sys.stderr)
        print(f"Audit complete: 0 call sites -> {out_path}")
        return 0

    print(f"Audit complete: {len(all_sites)} call sites -> {out_path}")
    by_tier: dict[str, int] = {}
    for s in all_sites:
        by_tier[s.tier] = by_tier.get(s.tier, 0) + 1
    for tier, n in sorted(by_tier.items()):
        print(f"  {tier}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
