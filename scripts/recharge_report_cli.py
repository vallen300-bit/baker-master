#!/usr/bin/env python3
"""Recharge-report CLI. Reads facts from stdin (or --facts-file), writes
rendered HTML (canonical Pichler V3 register) to stdout (or --output).
Validates the rendered HTML before writing.

Usage:
  python scripts/recharge_report_cli.py --tier high --output report.html < facts.txt
  python scripts/recharge_report_cli.py --tier routine --facts-file facts.txt \\
      --output report.html
"""
import argparse
import sys
from pathlib import Path

from claimsmax.recharge_report.generator import (
    RechargeReportGenerationError,
    generate_recharge_report,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate canonical Pichler V3 EN recharge-failure HTML report."
    )
    p.add_argument("--tier", choices=["high", "routine"], default="high")
    p.add_argument(
        "--facts-file",
        type=Path,
        help="Path to facts text file (default: stdin)",
    )
    p.add_argument(
        "--output",
        type=Path,
        help="Output HTML path (default: stdout)",
    )
    p.add_argument(
        "--template",
        type=Path,
        help="Override canonical V3 HTML template path",
    )
    args = p.parse_args(argv)

    facts = (
        args.facts_file.read_text(encoding="utf-8") if args.facts_file else sys.stdin.read()
    )
    if not facts.strip():
        print("ERROR: no facts provided", file=sys.stderr)
        return 2

    template_kwargs = {"template_path": args.template} if args.template else {}
    try:
        rendered_html = generate_recharge_report(
            facts, model_tier=args.tier, **template_kwargs
        )
    except RechargeReportGenerationError as e:
        print(f"ERROR: report generation failed:\n{e}", file=sys.stderr)
        return 3

    if args.output:
        args.output.write_text(rendered_html, encoding="utf-8")
        print(f"OK: wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(rendered_html)
    return 0


if __name__ == "__main__":
    sys.exit(main())
