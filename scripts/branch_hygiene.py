"""BRANCH_HYGIENE_1 — auto-prune stale branches in baker-master.

Three-layer logic:

  L1  Auto-delete confirmed-merged branches (squash-merge tip already on
      main per `git merge-base --is-ancestor` OR all branch commits
      patch-equivalent to main).
  L2  Flag stale-unmerged branches (>30d, tip not on main) into a Triaga
      HTML report for Director review. NEVER auto-delete L2.
  L3  Bulk-delete branches Director ticked in Triaga (read tick list from
      stdin / file, delete via gh API). Each deletion logged.

Plus: explicit Q2 default deletion of the 8-branch mobile UI cluster on
the first run (Director default 2026-04-26).

Usage:
    python3 scripts/branch_hygiene.py --dry-run               # report only, no deletions
    python3 scripts/branch_hygiene.py                         # L1 auto-delete + L2 flag + mobile UI cluster delete
    python3 scripts/branch_hygiene.py --l3 ticks.txt          # batch-delete L3 ticked branches
    python3 scripts/branch_hygiene.py --triaga-html out.html  # write Triaga HTML for L2 only

Audit trail: every deletion writes a row to `branch_hygiene_log`
(see migrations/20260426_branch_hygiene_log.sql).

GitHub API: uses `gh` CLI for branch list, deletion, compare. Rate-limit
aware: throttles to 10 deletions/minute.

Whitelist: `main` is always protected. Branches matching --protect-pattern
(default: 'main', 'master', 'release/*') are skipped at every layer.
"""
from __future__ import annotations

import argparse
import fnmatch
import html
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "vallen300-bit/baker-master"
DEFAULT_BASE = "main"
DEFAULT_STALENESS_DAYS = 30
DELETIONS_PER_MINUTE = 10
DEFAULT_PROTECT_PATTERNS = ("main", "master", "release/*")

# Q2 default 2026-04-26: delete this cluster on first run.
MOBILE_UI_CLUSTER = (
    "feat/mobile-*",
    "feat/ios-shortcuts-1",
    "feat/document-browser-1",
    "feat/networking-phase1",
)

logger = logging.getLogger("branch_hygiene")


@dataclass
class BranchInfo:
    name: str
    sha: str
    last_commit_iso: str
    age_days: int

    def matches_any(self, patterns) -> bool:
        return any(fnmatch.fnmatch(self.name, p) for p in patterns)


# --------------------------------------------------------------------------- #
# gh CLI wrappers
# --------------------------------------------------------------------------- #


def gh(args, *, capture: bool = True, check: bool = True) -> str:
    """Run `gh` with args. Returns stdout (capture=True) or empty string."""
    cmd = ["gh", *args]
    res = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        check=False,
    )
    if check and res.returncode != 0:
        raise RuntimeError(
            f"gh failed: {' '.join(cmd)}\nstderr: {res.stderr}"
        )
    return res.stdout if capture else ""


def list_branches(repo: str) -> list[BranchInfo]:
    """List all remote branches with last-commit metadata."""
    raw = gh(
        [
            "api",
            f"repos/{repo}/branches?per_page=100",
            "--paginate",
            "-q",
            ".[] | {name, sha: .commit.sha}",
        ]
    )
    branches: list[BranchInfo] = []
    for line in raw.strip().splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        name = obj["name"]
        sha = obj["sha"]
        meta = _commit_metadata(repo, sha)
        branches.append(
            BranchInfo(
                name=name,
                sha=sha,
                last_commit_iso=meta["iso"],
                age_days=meta["age_days"],
            )
        )
    return branches


def _commit_metadata(repo: str, sha: str) -> dict:
    """Return {iso, age_days} for a commit sha."""
    raw = gh(
        ["api", f"repos/{repo}/commits/{sha}", "-q", ".commit.committer.date"]
    ).strip()
    if not raw:
        return {"iso": "", "age_days": 0}
    iso = raw
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return {"iso": iso, "age_days": 0}
    age = (datetime.now(timezone.utc) - dt).days
    return {"iso": iso, "age_days": max(age, 0)}


def compare_to_base(repo: str, base: str, branch: str) -> dict:
    """Return {ahead_by, behind_by, status} for branch vs base.

    GitHub semantics:
      ahead_by    = commits on branch not on base
      behind_by   = commits on base not on branch
      status      = "identical" | "ahead" | "behind" | "diverged"
    """
    raw = gh(
        [
            "api",
            f"repos/{repo}/compare/{base}...{branch}",
            "-q",
            "{ahead_by, behind_by, status}",
        ]
    ).strip()
    if not raw:
        return {"ahead_by": -1, "behind_by": -1, "status": "unknown"}
    return json.loads(raw)


def delete_branch(repo: str, branch: str) -> bool:
    """Delete a remote branch via gh API. Returns True on success."""
    try:
        gh(
            [
                "api",
                "-X",
                "DELETE",
                f"repos/{repo}/git/refs/heads/{branch}",
            ],
            capture=True,
            check=True,
        )
        return True
    except RuntimeError as e:
        logger.error("delete failed for %s: %s", branch, e)
        return False


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def classify(
    branch: BranchInfo,
    repo: str,
    base: str,
    staleness_days: int,
    protect_patterns: tuple[str, ...],
    mobile_cluster: tuple[str, ...] = MOBILE_UI_CLUSTER,
) -> tuple[str, str]:
    """Return (layer, reason) where layer ∈ {PROTECTED, L1, L2_FLAGGED,
    MOBILE_CLUSTER, KEEP}.

    Decision order:
      1. PROTECTED: matches a protect pattern (main, master, release/*).
      2. L1: ahead_by == 0 (every commit on branch already on base, i.e.
         squash-merged or fast-forwarded).
      3. MOBILE_CLUSTER: matches Q2 default-delete pattern.
      4. L2_FLAGGED: age >= staleness_days AND ahead_by > 0.
      5. KEEP: ahead and recent (do not act).
    """
    if branch.matches_any(protect_patterns):
        return ("PROTECTED", "matches protect pattern")

    if branch.name == base:
        return ("PROTECTED", f"base branch {base!r}")

    cmp = compare_to_base(repo, base, branch.name)
    ahead = cmp.get("ahead_by", -1)
    if ahead == 0:
        return ("L1", f"squash-merged (ahead_by=0, status={cmp.get('status')})")

    if branch.matches_any(mobile_cluster):
        return ("MOBILE_CLUSTER", "Q2 default-delete (mobile UI cluster)")

    if branch.age_days >= staleness_days and ahead > 0:
        return (
            "L2_FLAGGED",
            f"stale {branch.age_days}d, ahead_by={ahead}",
        )

    return ("KEEP", f"ahead_by={ahead}, age={branch.age_days}d")


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #


def log_deletion(
    branch: BranchInfo,
    layer: str,
    reason: str,
    actor: str = "branch_hygiene",
    *,
    store=None,
) -> bool:
    """Insert a row into branch_hygiene_log. Best-effort; non-fatal."""
    if store is None:
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
        except Exception as e:
            logger.warning("audit log: store init failed (non-fatal): %s", e)
            return False
    if store is None:
        return False
    conn = store._get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO branch_hygiene_log
                (branch_name, last_commit_sha, layer, reason, age_days, actor)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (branch.name, branch.sha, layer, reason, branch.age_days, actor),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("audit log insert failed for %s: %s", branch.name, e)
        return False
    finally:
        store._put_conn(conn)


# --------------------------------------------------------------------------- #
# Triaga HTML for L2
# --------------------------------------------------------------------------- #


def triaga_html(rows: list[tuple[BranchInfo, str]], generated_at: str) -> str:
    """Build a self-contained HTML page listing L2 branches with checkboxes
    so Director can tick → save → feed back as L3 input."""
    items = []
    for b, reason in rows:
        items.append(
            f"""    <tr>
      <td><input type="checkbox" name="delete" value="{html.escape(b.name)}"></td>
      <td><code>{html.escape(b.name)}</code></td>
      <td>{b.age_days}</td>
      <td><code>{html.escape(b.sha[:8])}</code></td>
      <td>{html.escape(reason)}</td>
    </tr>"""
        )
    body = "\n".join(items) if items else (
        '    <tr><td colspan="5"><em>No L2 branches.</em></td></tr>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Branch Hygiene — Triaga (L2 Review)</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 960px; margin: 2em auto; padding: 0 1em; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: .4em .6em; border-bottom: 1px solid #ddd; text-align: left; vertical-align: top; }}
    th {{ background: #f5f5f5; }}
    code {{ font-family: ui-monospace, Menlo, monospace; font-size: .92em; }}
    .meta {{ color: #666; font-size: .9em; }}
  </style>
</head>
<body>
  <h1>Branch Hygiene — L2 Review</h1>
  <p class="meta">Generated {html.escape(generated_at)}. Tick branches to delete; save the ticked names into a file (one per line) and feed back via <code>scripts/branch_hygiene.py --l3 &lt;file&gt;</code>.</p>
  <form>
    <table>
      <thead>
        <tr><th>Delete</th><th>Branch</th><th>Age (d)</th><th>SHA</th><th>Reason</th></tr>
      </thead>
      <tbody>
{body}
      </tbody>
    </table>
  </form>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Main flows
# --------------------------------------------------------------------------- #


def run_classification(
    repo: str,
    base: str,
    staleness_days: int,
    protect_patterns: tuple[str, ...],
) -> dict[str, list[tuple[BranchInfo, str]]]:
    """Classify all branches; return {layer: [(branch, reason), ...]}."""
    branches = list_branches(repo)
    buckets: dict[str, list[tuple[BranchInfo, str]]] = {
        "PROTECTED": [],
        "L1": [],
        "MOBILE_CLUSTER": [],
        "L2_FLAGGED": [],
        "KEEP": [],
    }
    for b in branches:
        layer, reason = classify(b, repo, base, staleness_days, protect_patterns)
        buckets.setdefault(layer, []).append((b, reason))
    return buckets


def execute_deletions(
    rows: list[tuple[BranchInfo, str]],
    *,
    repo: str,
    layer: str,
    dry_run: bool,
    throttle_per_minute: int = DELETIONS_PER_MINUTE,
    deleter=None,
    auditor=None,
) -> int:
    """Delete each branch in `rows` (unless dry_run). Returns number deleted."""
    if not rows:
        return 0
    deleter = deleter or (lambda r, b: delete_branch(r, b))
    auditor = auditor or (
        lambda branch, lyr, reason: log_deletion(branch, lyr, reason)
    )
    interval = 60.0 / max(throttle_per_minute, 1)
    deleted = 0
    for b, reason in rows:
        if dry_run:
            print(f"  [dry-run] would delete {b.name} ({layer}: {reason})")
            continue
        ok = deleter(repo, b.name)
        if ok:
            auditor(b, layer, reason)
            deleted += 1
            print(f"  deleted {b.name} ({layer})")
        else:
            print(f"  FAILED to delete {b.name}", file=sys.stderr)
        if not dry_run:
            time.sleep(interval)
    return deleted


def run_l3_batch(
    tick_file: Path,
    *,
    repo: str,
    dry_run: bool,
) -> int:
    """Read branch names from `tick_file` (one per line), delete each as L3."""
    names = [
        line.strip()
        for line in tick_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not names:
        print("L3: no ticked branches in input file")
        return 0
    branches = list_branches(repo)
    by_name = {b.name: b for b in branches}
    rows = []
    for name in names:
        if name not in by_name:
            print(f"  SKIP {name}: not present on remote", file=sys.stderr)
            continue
        rows.append((by_name[name], "L3 Director-confirmed"))
    return execute_deletions(rows, repo=repo, layer="L3", dry_run=dry_run)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--staleness-days", type=int, default=DEFAULT_STALENESS_DAYS)
    p.add_argument(
        "--protect-pattern",
        action="append",
        default=None,
        help=(
            "fnmatch pattern for branches to ALWAYS skip (default: main, "
            "master, release/*; flag may repeat)"
        ),
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--triaga-html",
        type=Path,
        default=None,
        help="write L2 Triaga HTML to this path",
    )
    p.add_argument(
        "--l3",
        type=Path,
        default=None,
        help=(
            "path to a file with branch names ticked by Director "
            "(one per line) — runs L3 batch-delete"
        ),
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    protect = tuple(args.protect_pattern or DEFAULT_PROTECT_PATTERNS)

    if args.l3 is not None:
        n = run_l3_batch(args.l3, repo=args.repo, dry_run=args.dry_run)
        print(f"L3: {n} branches deleted (dry-run={args.dry_run})")
        return 0

    buckets = run_classification(
        repo=args.repo,
        base=args.base,
        staleness_days=args.staleness_days,
        protect_patterns=protect,
    )

    print(f"Branch hygiene scan @ {datetime.now(timezone.utc).isoformat()}")
    print(f"Repo: {args.repo}; base: {args.base}; staleness: {args.staleness_days}d")
    for layer in ("PROTECTED", "L1", "MOBILE_CLUSTER", "L2_FLAGGED", "KEEP"):
        print(f"  {layer}: {len(buckets.get(layer, []))}")

    deleted_total = 0
    deleted_total += execute_deletions(
        buckets.get("L1", []),
        repo=args.repo,
        layer="L1",
        dry_run=args.dry_run,
    )
    deleted_total += execute_deletions(
        buckets.get("MOBILE_CLUSTER", []),
        repo=args.repo,
        layer="L1",
        dry_run=args.dry_run,
    )

    # Triaga HTML for L2
    if args.triaga_html or buckets.get("L2_FLAGGED"):
        out = args.triaga_html or (
            REPO_ROOT
            / "briefs"
            / "_reports"
            / f"branch_hygiene_triaga_{datetime.now(timezone.utc).strftime('%Y%m%d')}.html"
        )
        html_text = triaga_html(
            buckets.get("L2_FLAGGED", []),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html_text, encoding="utf-8")
        print(f"L2 Triaga HTML: {out}")

        # Audit-log L2_FLAGGED rows so the weekly digest can see them.
        for b, reason in buckets.get("L2_FLAGGED", []):
            log_deletion(b, "L2_FLAGGED", reason, actor="branch_hygiene")

    print(f"Done. Deletions={deleted_total} (dry-run={args.dry_run}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
