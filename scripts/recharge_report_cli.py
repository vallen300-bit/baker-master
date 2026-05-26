#!/usr/bin/env python3
"""Recharge-report CLI. Reads facts from stdin (or --facts-file), writes
rendered markdown to stdout (or --output). Validates before writing.

Usage:
  python scripts/recharge_report_cli.py --tier high --output report.md < facts.txt
  python scripts/recharge_report_cli.py --tier routine --facts-file facts.txt \\
      --output report.md
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
        description="Generate canonical Pichler/HEAD-4 recharge report."
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
        help="Output markdown path (default: stdout)",
    )
    p.add_argument(
        "--template",
        type=Path,
        help="Override canonical template path",
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
        markdown = generate_recharge_report(
            facts, model_tier=args.tier, **template_kwargs
        )
    except RechargeReportGenerationError as e:
        print(f"ERROR: report generation failed:\n{e}", file=sys.stderr)
        return 3

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
        print(f"OK: wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
